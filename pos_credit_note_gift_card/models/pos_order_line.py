# -*- coding: utf-8 -*-
"""
pos_order_line.py — POS order-line extension
=============================================
Adds helper methods used by the credit-note workflow to:

  1. Detect whether a return line references a non-returnable product.
  2. Compute the net refund amount for a single line after applying
     the configured discount-distribution method.
  3. Determine the commission amount to deduct from a single return line
     by reading commission data from pos_extra_amount_manager_extended
     when that module is installed (soft dependency — gracefully absent).
  4. Override _load_pos_data_fields to inject commission fields into the
     POS session payload so that the JS layer can read them on original
     (forward-sale) order lines.

Why the _load_pos_data_fields override is needed
-------------------------------------------------
Odoo 18's base pos.order.line._load_pos_data_fields returns an explicit
whitelist of fields.  total_extra_amount and total_base_profit are custom
fields added by pos_extra_amount_manager_extended and are NOT in that
whitelist.

Furthermore, the extended module intentionally zeros those fields on
refund lines (qty < 0) because a return is not a revenue event.  The
credit-note module needs the commission values from the ORIGINAL (sale)
order line — accessed via the return line's refunded_orderline_id — so
the Odoo 18 JS model must have those values loaded.

This override safely extends the field list only when the fields actually
exist on the model (soft dependency pattern).

Logging
-------
Logger : ``pos_credit_note_gift_card.pos_order_line``
Level  : DEBUG for per-line calculations, INFO for blocked returns.
"""

import logging
from odoo import models

_logger = logging.getLogger('pos_credit_note_gift_card.pos_order_line')

# Fields added by pos_extra_amount_manager_extended that must be included
# in the POS session payload so the JS credit-note computation can read
# the commission values on ORIGINAL (forward-sale) order lines.
_COMMISSION_FIELDS = ('total_extra_amount', 'total_base_profit')


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    # =========================================================================
    # POS session data — inject commission fields
    # =========================================================================

    def _load_pos_data_fields(self, config_id):
        """
        Extend the Odoo 18 field whitelist for pos.order.line to include
        total_extra_amount and total_base_profit when those fields exist
        (i.e. when pos_extra_amount_manager_extended is installed).

        These values are zero on return lines by design, but they are
        correct on original (forward-sale) lines.  The JS computeNetAmount
        helper reads them from the original line via refunded_orderline_id
        to calculate the proportional commission deduction.
        """
        fields = super()._load_pos_data_fields(config_id)
        added = []
        for fname in _COMMISSION_FIELDS:
            if fname in self._fields and fname not in fields:
                fields.append(fname)
                added.append(fname)
        if added:
            _logger.debug(
                "[PosOrderLine][_load_pos_data_fields] "
                "Injected commission fields into POS payload: %s", added,
            )
        return fields

    # =========================================================================
    # Non-returnable guard
    # =========================================================================

    # =========================================================================
    # Commission data fetch — called by the credit-note controller
    # =========================================================================

    @classmethod
    def get_credit_note_commission(cls, env, line_ids):
        """
        Return the ACTUAL PAID-OUT commission amounts attributed to each
        original-sale line, for both Tier 1 (extra amount) and Tier 2
        (base profit).

        Option B logic — deduct what was actually paid, not the pool:

          Both distribution models (pos.extra.distribution and
          pos.base.profit.distribution) link to the POS ORDER, not to
          individual lines.  We attribute the order-level payout to each
          line proportionally using the line's share of the pool:

            line_tier1_proportion = line.total_extra_amount / order.total_extra_amount
            tier1_paid_for_line   = sum(posted Tier-1 distributions) × proportion

            line_tier2_proportion = line.total_base_profit / order.total_base_profit
            tier2_paid_for_line   = sum(posted Tier-2 distributions) × proportion

        The JS layer then scales by (returned_qty / original_qty) and applies
        the configured weight percentages.

        Parameters
        ----------
        env      : Odoo Environment
        line_ids : list[int]   — IDs of ORIGINAL (forward-sale) order lines

        Returns
        -------
        dict  keyed by str(line.id):
            { 'tier1_paid' : float,   — actual Tier-1 payout attributed to line
              'tier2_paid' : float,   — actual Tier-2 payout attributed to line
              'qty'        : float }  — original qty (for scale calc in JS)
        """
        if not line_ids:
            return {}

        lines = env['pos.order.line'].browse(line_ids)
        result = {}

        for line in lines:
            order = line.order_id

            # ----------------------------------------------------------------
            # Commission — Tier 1 (extra amount) and Tier 2 (base profit)
            # Deduct what was ACTUALLY PAID OUT, attributed proportionally
            # to this line's share of the order-level pool.
            # ----------------------------------------------------------------
            line_extra_pool  = getattr(line,  'total_extra_amount', 0.0) or 0.0
            line_base_pool   = getattr(line,  'total_base_profit',  0.0) or 0.0
            order_extra_pool = getattr(order, 'total_extra_amount', 0.0) or 0.0
            order_base_pool  = getattr(order, 'total_base_profit',  0.0) or 0.0

            extra_proportion = (line_extra_pool / order_extra_pool) if order_extra_pool > 0 else 0.0
            base_proportion  = (line_base_pool  / order_base_pool)  if order_base_pool  > 0 else 0.0

            tier1_distributions = getattr(order, 'extra_distribution_ids',
                                          env['pos.extra.distribution'])
            tier1_total_paid = sum(
                d.distribution_amount for d in tier1_distributions if d.state == 'posted'
            )

            tier2_distributions = getattr(order, 'base_profit_distribution_ids',
                                          env['pos.base.profit.distribution'])
            tier2_total_paid = sum(
                d.distribution_amount for d in tier2_distributions if d.state == 'posted'
            )

            tier1_paid_for_line = tier1_total_paid * extra_proportion
            tier2_paid_for_line = tier2_total_paid * base_proportion

            # ----------------------------------------------------------------
            # Global discount — any line on the original order with a
            # negative price_subtotal_incl.  This covers BOTH:
            #   • is_reward_line=True  lines (Odoo loyalty/coupon rewards)
            #   • is_reward_line=False lines (custom discount products, e.g.
            #     product "GENERAL DISCOUNT APPLIED" with negative price_unit)
            #
            # Proportion = this line's revenue / total positive-revenue lines.
            # The attributed discount is qty-scaled by the JS layer.
            # ----------------------------------------------------------------
            discount_lines = order.lines.filtered(
                lambda l: (l.price_subtotal_incl or 0.0) < 0
            )
            total_global_discount = sum(
                abs(l.price_subtotal_incl) for l in discount_lines
            )

            positive_lines = order.lines.filtered(
                lambda l: (l.price_subtotal_incl or 0.0) > 0
            )
            order_revenue     = sum(
                (l.price_subtotal_incl or 0.0) for l in positive_lines
            )
            line_revenue      = abs(line.price_subtotal_incl or 0.0)
            revenue_proportion = (line_revenue / order_revenue) if order_revenue > 0 else 0.0

            global_discount_for_line = total_global_discount * revenue_proportion

            result[str(line.id)] = {
                'tier1_paid':          tier1_paid_for_line,
                'tier2_paid':          tier2_paid_for_line,
                'global_discount_adj': global_discount_for_line,
                'qty':                 line.qty or 1.0,
            }

            _logger.info(
                "[PosOrderLine][get_credit_note_commission] line_id=%s | order=%s | "
                "tier1: pool=%.4f/%.4f prop=%.4f paid=%.4f → line=%.4f | "
                "tier2: pool=%.4f/%.4f prop=%.4f paid=%.4f → line=%.4f | "
                "global_disc: total=%.4f rev_prop=%.4f → line=%.4f | qty=%.4f",
                line.id, order.name,
                line_extra_pool, order_extra_pool, extra_proportion,
                tier1_total_paid, tier1_paid_for_line,
                line_base_pool, order_base_pool, base_proportion,
                tier2_total_paid, tier2_paid_for_line,
                total_global_discount, revenue_proportion, global_discount_for_line,
                line.qty or 1.0,
            )

        return result

    # =========================================================================
    # Non-returnable guard
    # =========================================================================

    def is_non_returnable(self):
        """
        Return True if the product on this line is flagged as non-returnable.

        Checks ``product_id.product_tmpl_id.pos_not_returnable`` (set by this
        module) so the check works whether the field was set on the template
        or surfaced through the product variant.

        Returns
        -------
        bool
        """
        self.ensure_one()
        product = self.product_id
        result = bool(
            product
            and product.product_tmpl_id
            and product.product_tmpl_id.pos_not_returnable
        )
        if result:
            _logger.info(
                "[PosOrderLine][is_non_returnable] line_id=%s | product='%s' "
                "is flagged non-returnable — blocking return.",
                self.id,
                product.display_name if product else 'N/A',
            )
        else:
            _logger.debug(
                "[PosOrderLine][is_non_returnable] line_id=%s | product='%s' "
                "is returnable.",
                self.id,
                product.display_name if product else 'N/A',
            )
        return result

    # =========================================================================
    # Discount-adjusted refund amount
    # =========================================================================

    def compute_discounted_refund_amount(self, distribution_mode):
        """
        Compute the net refund amount for this line after honouring the
        discount-distribution policy.

        Parameters
        ----------
        distribution_mode : str
            One of 'proportional', 'equal', 'none'.
            When 'equal' is requested the caller is responsible for passing
            the pre-computed equal share; this method handles only
            'proportional' and 'none'.

        Returns
        -------
        float
            Net credit-note amount (positive, representing money back).

        Notes
        -----
        For a refund line ``qty`` is negative; ``price_subtotal_incl`` is
        therefore also negative.  We take the absolute value so the amount
        is always positive and ready to load onto a gift card.
        """
        self.ensure_one()
        gross = abs(self.price_subtotal_incl or 0.0)

        if distribution_mode == 'proportional':
            discount_pct = (self.discount or 0.0) / 100.0
            net = gross * (1.0 - discount_pct)
            _logger.debug(
                "[PosOrderLine][compute_discounted_refund_amount] "
                "line_id=%s | product='%s' | gross=%.4f | discount_pct=%.4f "
                "| net=%.4f (proportional)",
                self.id,
                self.product_id.display_name if self.product_id else 'N/A',
                gross, discount_pct, net,
            )
            return net

        # 'none' — credit the full gross amount
        _logger.debug(
            "[PosOrderLine][compute_discounted_refund_amount] "
            "line_id=%s | product='%s' | gross=%.4f (mode=%s — no deduction)",
            self.id,
            self.product_id.display_name if self.product_id else 'N/A',
            gross, distribution_mode,
        )
        return gross

    # =========================================================================
    # Commission-adjusted refund amount (soft dep on extra_amount_manager)
    # =========================================================================

    def compute_commission_deduction(self, mode, extra_weight, base_weight):
        """
        Compute the commission amount to deduct from this line's credit note.

        Reads TIER-1 (extra_amount) and TIER-2 (base_profit) fields from
        ``pos_extra_amount_manager_extended`` when installed.  Returns 0.0
        safely when the module is absent or the original line had no
        commission data.

        Parameters
        ----------
        mode : str
            'none' | 'extra_amount' | 'base_profit' | 'both'
        extra_weight : float
            0–100; percentage of TIER-1 commission to deduct.
        base_weight : float
            0–100; percentage of TIER-2 commission to deduct.

        Returns
        -------
        float
            Total commission amount to subtract from the credit note (≥ 0).
        """
        self.ensure_one()

        if mode == 'none':
            _logger.debug(
                "[PosOrderLine][compute_commission_deduction] "
                "line_id=%s | mode=none → deduction=0.0", self.id,
            )
            return 0.0

        # --- Soft dependency check ---
        has_extra_fields = (
            hasattr(self, 'total_extra_amount')
            and hasattr(self, 'total_base_profit')
        )
        if not has_extra_fields:
            _logger.debug(
                "[PosOrderLine][compute_commission_deduction] "
                "line_id=%s | pos_extra_amount_manager_extended not installed "
                "— deduction=0.0", self.id,
            )
            return 0.0

        deduction = 0.0

        # For return lines (qty < 0), pos_extra_amount_manager_extended
        # intentionally resets all commission fields to 0.  We fall back to
        # the ORIGINAL line via refunded_orderline_id and scale the commission
        # proportionally to the fraction of units being returned.
        is_return_line = (self.qty or 0.0) < 0
        orig_line      = self.refunded_orderline_id if is_return_line else None
        if orig_line:
            orig_qty = abs(orig_line.qty or 1.0)
            ret_qty  = abs(self.qty)
            scale    = ret_qty / orig_qty if orig_qty else 1.0
            _logger.debug(
                "[PosOrderLine][compute_commission_deduction] "
                "Return line id=%s | orig_line id=%s | "
                "ret_qty=%.4f / orig_qty=%.4f = scale=%.4f",
                self.id, orig_line.id, ret_qty, orig_qty, scale,
            )
        else:
            scale = 1.0

        if mode in ('extra_amount', 'both'):
            tier1_raw = abs(getattr(self, 'total_extra_amount', 0.0) or 0.0)
            if tier1_raw == 0.0 and orig_line:
                tier1_raw = abs(getattr(orig_line, 'total_extra_amount', 0.0) or 0.0) * scale
            tier1_deduction = tier1_raw * (extra_weight / 100.0)
            deduction += tier1_deduction
            _logger.debug(
                "[PosOrderLine][compute_commission_deduction] "
                "line_id=%s | TIER-1 extra=%.4f (scale=%.4f) | weight=%.2f%% "
                "| tier1_deduction=%.4f",
                self.id, tier1_raw, scale, extra_weight, tier1_deduction,
            )

        if mode in ('base_profit', 'both'):
            tier2_raw = abs(getattr(self, 'total_base_profit', 0.0) or 0.0)
            if tier2_raw == 0.0 and orig_line:
                tier2_raw = abs(getattr(orig_line, 'total_base_profit', 0.0) or 0.0) * scale
            tier2_deduction = tier2_raw * (base_weight / 100.0)
            deduction += tier2_deduction
            _logger.debug(
                "[PosOrderLine][compute_commission_deduction] "
                "line_id=%s | TIER-2 base_profit=%.4f (scale=%.4f) | weight=%.2f%% "
                "| tier2_deduction=%.4f",
                self.id, tier2_raw, scale, base_weight, tier2_deduction,
            )

        _logger.info(
            "[PosOrderLine][compute_commission_deduction] "
            "line_id=%s | product='%s' | mode=%s | is_return=%s "
            "| total_deduction=%.4f",
            self.id,
            self.product_id.display_name if self.product_id else 'N/A',
            mode, is_return_line, deduction,
        )
        return deduction
