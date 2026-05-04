# -*- coding: utf-8 -*-
"""
POS Order Line Extension
========================
Tracks both:
    1. TIER 1: Extra amounts charged above pricelist price (incl VAT split)
    2. TIER 2: Base profit on the pricelist price itself (excl VAT)

Supports a calc_qty picker: enter the number of units to calculate
(maximum = ceil(ordered qty) for forward sales). Defaults to 1 unit.

Refund Line Handling:
    Lines with negative qty (refund/return lines) are excluded entirely
    from commission and profit calculations. Returning a product is not
    a revenue event — no extra amount or base profit should be computed,
    distributed, or journalised on a return line.

    The _check_calc_qty constraint is also bypassed for refund lines
    because the concept of "calc_qty cannot exceed ordered qty" is
    meaningless when ordered qty is negative.

Calculation Flow:
    For each forward sales line (qty > 0):
        TIER 1:
            paid_price_per_unit      = price_subtotal_incl / qty
            pricelist_price_incl     = pricelist._get_product_price(...)
            extra_amount_per_unit    = paid_price_per_unit - pricelist_price_incl
            effective_qty            = min(calc_qty, int(abs(qty)) or 1)
            total_extra_amount       = extra_amount_per_unit * effective_qty
            product_cost             = standard_price * effective_qty

        TIER 2:
            vat_rate                 = sum of percent-type taxes / 100
            pricelist_price_excl_vat = pricelist_price_incl / (1 + vat_rate)
            base_profit_per_unit     = pricelist_price_excl_vat - standard_price
            total_base_profit        = base_profit_per_unit * effective_qty

Dependencies:
    - Requires pos.order with a linked pricelist for TIER 1/2 calculations.
    - Requires product taxes configured as 'percent' type for VAT extraction.
"""

import math
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PosOrderLine(models.Model):
    """
    Extension of pos.order.line to support two-tier commission calculations.

    Adds a qty picker (calc_qty) and computed monetary fields for both the
    TIER 1 extra amount (premium above pricelist) and TIER 2 base profit
    (pricelist margin above purchase cost, excl VAT).

    Refund lines (qty < 0) are treated as non-revenue events:
        - _check_calc_qty constraint is skipped entirely.
        - _compute_extra_and_profit resets all monetary fields to zero
          and returns early without performing any calculations.

    This ensures that credit notes and product returns do not generate
    phantom commission or profit figures that could corrupt Tier 1/2
    distribution workflows or overstate distributable amounts.

    Fractional Quantity Handling:
        Products sold in fractional quantities (e.g. 0.5 sheets of sandpaper)
        are fully supported. The calc_qty upper bound uses math.ceil(qty) so
        that a qty=0.5 line correctly allows calc_qty=1.
        The compute method already handles this via `int(abs(qty)) or 1`.
    """

    _inherit = 'pos.order.line'

    # =========================================================================
    # QTY PICKER: Applies to BOTH extra and base profit
    # =========================================================================

    calc_qty = fields.Integer(
        string='Calc Qty',
        default=1,
        help=(
            "Number of units to use in extra amount and base profit calculations. "
            "For forward sales lines: cannot exceed ceil(ordered quantity), minimum 1. "
            "For fractional qty lines (e.g. qty=0.5): calc_qty=1 is valid. "
            "For refund lines (qty < 0): this field is ignored entirely — "
            "no commission or profit is computed on returns."
        )
    )

    # =========================================================================
    # TIER 1: EXTRA AMOUNT FIELDS
    # =========================================================================

    pricelist_price_incl = fields.Monetary(
        string='Pricelist Price (Incl VAT)',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help=(
            "The standard pricelist price for this product (incl VAT) "
            "at the time of sale. Used as the baseline for extra amount "
            "calculation: any price above this is considered 'extra'."
        )
    )

    paid_price_per_unit = fields.Monetary(
        string='Paid Price Per Unit',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help=(
            "Actual price paid per unit: price_subtotal_incl / qty. "
            "Compared against pricelist_price_incl to determine extra."
        )
    )

    extra_amount_per_unit = fields.Monetary(
        string='Extra Per Unit',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help=(
            "Premium charged per unit above the pricelist price (incl VAT). "
            "Formula: paid_price_per_unit - pricelist_price_incl. "
            "Zero when sold at exactly pricelist price."
        )
    )

    total_extra_amount = fields.Monetary(
        string='Total Extra',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help=(
            "Total extra amount for this line: extra_amount_per_unit * effective_qty. "
            "effective_qty is min(calc_qty, int(abs(qty)) or 1). "
            "Always zero for refund lines."
        )
    )

    product_cost = fields.Monetary(
        string='Product Cost (AVCO)',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help=(
            "Total purchase cost (AVCO/standard_price) for the effective qty. "
            "Formula: standard_price * effective_qty. "
            "Used as COGS reference in Tier 1 distribution. "
            "Always zero for refund lines."
        )
    )

    # =========================================================================
    # TIER 2: BASE PROFIT FIELDS
    # =========================================================================

    pricelist_price_excl_vat = fields.Monetary(
        string='Pricelist Price (Excl VAT)',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help=(
            "Pricelist price after stripping VAT. "
            "Formula: pricelist_price_incl / (1 + vat_rate). "
            "If no percent-type taxes exist on the product, "
            "equals pricelist_price_incl unchanged."
        )
    )

    base_profit_per_unit = fields.Monetary(
        string='Base Profit Per Unit',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help=(
            "Margin per unit on the pricelist price (excl VAT): "
            "pricelist_price_excl_vat - standard_price. "
            "Represents the pure product margin before any extra premium."
        )
    )

    total_base_profit = fields.Monetary(
        string='Total Base Profit',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help=(
            "Total base margin for this line: base_profit_per_unit * effective_qty. "
            "Uses the same effective_qty as Tier 1. "
            "Always zero for refund lines."
        )
    )

    currency_id = fields.Many2one(
        related='order_id.currency_id',
        store=True
    )

    # =========================================================================
    # CONSTRAINT: calc_qty must be within valid range (forward sales only)
    # =========================================================================

    @api.constrains('calc_qty', 'qty')
    def _check_calc_qty(self):
        """
        Validate that calc_qty is between 1 and ceil(ordered quantity).

        Uses math.ceil() instead of int() so that fractional quantities
        (e.g. qty=0.5 for half a sheet of sandpaper) correctly allow
        calc_qty=1. Without ceil, int(0.5)=0 would always raise a false
        ValidationError for any product sold in a fractional qty < 1.

        Examples:
            qty=1.0  → max_allowed=1  → calc_qty=1 ✓
            qty=2.0  → max_allowed=2  → calc_qty=1 or 2 ✓
            qty=0.5  → max_allowed=1  → calc_qty=1 ✓  (was broken with int())
            qty=0.25 → max_allowed=1  → calc_qty=1 ✓

        Refund lines (qty < 0) are explicitly excluded from this constraint
        because:
            1. calc_qty is irrelevant for returns — no commission is computed.
            2. Comparing calc_qty (default 1) against ceil(negative) would
               always raise a false ValidationError, blocking refund saves.

        Raises:
            ValidationError: If calc_qty < 1 on a forward sales line.
            ValidationError: If calc_qty > ceil(qty) on a forward sales line.
        """
        for line in self:
            _logger.debug(
                "[PosOrderLine][_check_calc_qty] line_id=%s | product=%s | "
                "qty=%.4f | calc_qty=%d",
                line.id,
                line.product_id.display_name if line.product_id else 'N/A',
                line.qty or 0.0,
                line.calc_qty or 0,
            )

            # --- Skip constraint entirely for refund/return lines ---
            if line.qty and line.qty < 0:
                _logger.debug(
                    "[PosOrderLine][_check_calc_qty] line_id=%s | "
                    "Refund line detected (qty=%.4f) — constraint skipped.",
                    line.id, line.qty,
                )
                continue

            # --- Minimum check ---
            if line.calc_qty < 1:
                _logger.warning(
                    "[PosOrderLine][_check_calc_qty] line_id=%s | product=%s | "
                    "calc_qty=%d is below minimum of 1. Raising ValidationError.",
                    line.id,
                    line.product_id.display_name if line.product_id else 'N/A',
                    line.calc_qty,
                )
                raise ValidationError(
                    f"Calc Qty must be at least 1 (line: {line.product_id.display_name})."
                )

            # --- Maximum check: use ceil() to support fractional quantities ---
            # e.g. qty=0.5 → ceil=1 → calc_qty=1 is valid
            # e.g. qty=2.0 → ceil=2 → calc_qty up to 2 is valid
            if line.qty:
                max_allowed = math.ceil(line.qty)
                if line.calc_qty > max_allowed:
                    _logger.warning(
                        "[PosOrderLine][_check_calc_qty] line_id=%s | product=%s | "
                        "calc_qty=%d exceeds max_allowed=%d (qty=%.4f). "
                        "Raising ValidationError.",
                        line.id,
                        line.product_id.display_name if line.product_id else 'N/A',
                        line.calc_qty,
                        max_allowed,
                        line.qty,
                    )
                    raise ValidationError(
                        f"Calc Qty ({line.calc_qty}) cannot exceed ordered quantity "
                        f"({max_allowed}) on line: {line.product_id.display_name}."
                    )

                _logger.debug(
                    "[PosOrderLine][_check_calc_qty] line_id=%s | "
                    "calc_qty=%d is valid (max_allowed=%d, ordered qty=%.4f). "
                    "Constraint passed.",
                    line.id, line.calc_qty, max_allowed, line.qty,
                )

    # =========================================================================
    # ONCHANGE: Real-time update when qty picker changes
    # =========================================================================

    @api.onchange('calc_qty')
    def _onchange_calc_qty(self):
        """
        Recompute extra and profit amounts when the calc_qty picker changes.

        Triggered in real time in the form view as the user adjusts the
        quantity toggle. Delegates entirely to _compute_extra_and_profit
        so that the same logic path is used for both onchange and stored
        compute.
        """
        _logger.debug(
            "[PosOrderLine][_onchange_calc_qty] product=%s | new calc_qty=%d",
            self.product_id.display_name if self.product_id else 'N/A',
            self.calc_qty or 0,
        )
        self._compute_extra_and_profit()

    # =========================================================================
    # UNIFIED COMPUTATION: Both Extra AND Base Profit
    # =========================================================================

    @api.depends(
        'price_subtotal_incl', 'qty', 'product_id', 'product_id.standard_price',
        'product_id.taxes_id', 'order_id.pricelist_id', 'calc_qty'
    )
    def _compute_extra_and_profit(self):
        """
        Compute all TIER 1 (extra amount) and TIER 2 (base profit) fields
        for each order line.

        Logic Overview:
            1. If the line is missing qty, price, or product → reset all fields.
            2. If the line is a REFUND (qty < 0) → reset all fields and skip.
               No commission or profit is applicable on a return.
            3. For forward sales lines (qty > 0):
               a. TIER 1: Calculate extra amount above pricelist.
               b. TIER 2: Calculate base margin on pricelist excl VAT.

        Effective Qty:
            effective_qty = min(calc_qty or 1, int(abs(qty)) or 1)
            Uses abs() as a safety net; the primary refund guard (step 2)
            ensures refund lines never reach this point.

            Note: For fractional qty (e.g. 0.5), int(abs(0.5))=0, so the
            `or 1` fallback ensures effective_qty is at minimum 1. This is
            consistent with the ceil() logic in _check_calc_qty.

        VAT Extraction (TIER 2):
            VAT rate is sourced from percent-type taxes on the product.
            If no such taxes exist, vat_rate = 0 and pricelist_price_excl_vat
            equals pricelist_price_incl unchanged.

        Pricelist Lookup (TIER 1):
            Uses pricelist._get_product_price() with qty=1.0 to obtain
            the unit pricelist price. Falls back to 0.0 if no pricelist
            is linked to the order.

        All monetary results are stored (store=True) for use by the
        Tier 1 and Tier 2 distribution models and wizards.
        """
        for line in self:
            _logger.debug(
                "[PosOrderLine][_compute_extra_and_profit] START | "
                "line_id=%s | product=%s | qty=%.4f | "
                "price_subtotal_incl=%.4f | calc_qty=%d",
                line.id,
                line.product_id.display_name if line.product_id else 'N/A',
                line.qty or 0.0,
                line.price_subtotal_incl or 0.0,
                line.calc_qty or 0,
            )

            # --- Guard: missing required fields ---
            if not (line.qty and line.price_subtotal_incl and line.product_id):
                _logger.debug(
                    "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                    "Missing qty/price/product — resetting all fields.",
                    line.id,
                )
                line._reset_all_fields()
                continue

            # --- Guard: refund / return lines ---
            # Returning a product is not a revenue event.
            # No extra amount or base profit should be computed, distributed,
            # or journalised on a credit/return line.
            if line.qty < 0:
                _logger.info(
                    "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                    "product=%s | qty=%.4f — REFUND LINE detected. "
                    "Resetting all commission/profit fields to zero and skipping.",
                    line.id,
                    line.product_id.display_name,
                    line.qty,
                )
                line._reset_all_fields()
                continue

            # =====================================================================
            # TIER 1: EXTRA AMOUNT CALCULATION
            # =====================================================================

            # 1. Paid price per unit (incl VAT)
            line.paid_price_per_unit = line.price_subtotal_incl / line.qty
            _logger.debug(
                "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                "paid_price_per_unit=%.4f (price_subtotal_incl=%.4f / qty=%.4f)",
                line.id, line.paid_price_per_unit,
                line.price_subtotal_incl, line.qty,
            )

            # 2. Pricelist price (incl VAT) at qty=1
            pricelist = line.order_id.pricelist_id
            if pricelist and line.product_id:
                line.pricelist_price_incl = pricelist._get_product_price(
                    product=line.product_id,
                    quantity=1.0,
                    uom=line.product_id.uom_id,
                    date=line.order_id.date_order,
                )
                _logger.debug(
                    "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                    "pricelist='%s' | pricelist_price_incl=%.4f",
                    line.id,
                    pricelist.name,
                    line.pricelist_price_incl,
                )
            else:
                _logger.warning(
                    "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                    "No pricelist linked to order '%s'. "
                    "pricelist_price_incl defaulting to 0.0.",
                    line.id,
                    line.order_id.name if line.order_id else 'N/A',
                )
                line.pricelist_price_incl = 0.0

            # 3. Extra per unit
            line.extra_amount_per_unit = line.paid_price_per_unit - line.pricelist_price_incl
            _logger.debug(
                "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                "extra_amount_per_unit=%.4f "
                "(paid=%.4f - pricelist=%.4f)",
                line.id,
                line.extra_amount_per_unit,
                line.paid_price_per_unit,
                line.pricelist_price_incl,
            )

            # 4. Effective quantity — capped at actual ordered qty, min 1
            #    abs() used as safety net; refund lines never reach this point.
            #    For fractional qty (e.g. 0.5): int(0.5)=0 → or 1 → effective_qty=1
            #    This is consistent with _check_calc_qty using math.ceil(qty).
            ordered_qty = int(abs(line.qty)) or 1
            effective_qty = min(line.calc_qty or 1, ordered_qty)
            _logger.debug(
                "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                "calc_qty=%d | ordered_qty=%d | effective_qty=%d",
                line.id, line.calc_qty or 1, ordered_qty, effective_qty,
            )

            # 5. Total extra amount and product cost
            line.total_extra_amount = line.extra_amount_per_unit * effective_qty
            line.product_cost = line.product_id.standard_price * effective_qty
            _logger.debug(
                "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                "total_extra_amount=%.4f | product_cost=%.4f "
                "(standard_price=%.4f * effective_qty=%d)",
                line.id,
                line.total_extra_amount,
                line.product_cost,
                line.product_id.standard_price,
                effective_qty,
            )

            # =====================================================================
            # TIER 2: BASE PROFIT CALCULATION
            # =====================================================================

            # 6. Pricelist price excl VAT — strip VAT from pricelist_price_incl
            taxes = line.product_id.taxes_id.filtered(lambda t: t.amount_type == 'percent')
            vat_rate = sum(taxes.mapped('amount')) / 100.0 if taxes else 0.0

            if vat_rate > 0:
                line.pricelist_price_excl_vat = line.pricelist_price_incl / (1.0 + vat_rate)
                _logger.debug(
                    "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                    "vat_rate=%.4f (%.2f%%) | "
                    "pricelist_price_excl_vat=%.4f "
                    "(pricelist_incl=%.4f / (1 + %.4f))",
                    line.id,
                    vat_rate, vat_rate * 100,
                    line.pricelist_price_excl_vat,
                    line.pricelist_price_incl,
                    vat_rate,
                )
            else:
                _logger.warning(
                    "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                    "product='%s' has no percent-type taxes. "
                    "pricelist_price_excl_vat = pricelist_price_incl = %.4f",
                    line.id,
                    line.product_id.display_name,
                    line.pricelist_price_incl,
                )
                line.pricelist_price_excl_vat = line.pricelist_price_incl

            # 7. Base profit per unit
            line.base_profit_per_unit = (
                line.pricelist_price_excl_vat - line.product_id.standard_price
            )
            _logger.debug(
                "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                "base_profit_per_unit=%.4f "
                "(pricelist_excl_vat=%.4f - standard_price=%.4f)",
                line.id,
                line.base_profit_per_unit,
                line.pricelist_price_excl_vat,
                line.product_id.standard_price,
            )

            # 8. Total base profit
            line.total_base_profit = line.base_profit_per_unit * effective_qty
            _logger.debug(
                "[PosOrderLine][_compute_extra_and_profit] line_id=%s | "
                "total_base_profit=%.4f "
                "(base_profit_per_unit=%.4f * effective_qty=%d)",
                line.id,
                line.total_base_profit,
                line.base_profit_per_unit,
                effective_qty,
            )

            _logger.info(
                "[PosOrderLine][_compute_extra_and_profit] COMPLETE | "
                "line_id=%s | product=%s | qty=%.4f | effective_qty=%d | "
                "TIER1: extra_per_unit=%.4f total_extra=%.4f product_cost=%.4f | "
                "TIER2: base_profit_per_unit=%.4f total_base_profit=%.4f",
                line.id,
                line.product_id.display_name,
                line.qty,
                effective_qty,
                line.extra_amount_per_unit,
                line.total_extra_amount,
                line.product_cost,
                line.base_profit_per_unit,
                line.total_base_profit,
            )

    # =========================================================================
    # HELPER: Reset all computed fields
    # =========================================================================

    def _reset_all_fields(self):
        """
        Reset all TIER 1 and TIER 2 computed monetary fields to zero and
        restore calc_qty to its default of 1.

        Called when:
            - A required field (qty, price, product) is missing.
            - The line is identified as a refund/return (qty < 0).

        Ensures that distribution models and wizards never receive stale
        or garbage values from lines that are ineligible for calculation.
        Also resets calc_qty to 1 so the picker is in a clean state if the
        line is later converted or corrected.
        """
        _logger.debug(
            "[PosOrderLine][_reset_all_fields] line_id=%s | "
            "Resetting all TIER 1 and TIER 2 fields to zero.",
            self.id,
        )

        # TIER 1: Extra amount fields
        self.paid_price_per_unit = 0.0
        self.pricelist_price_incl = 0.0
        self.extra_amount_per_unit = 0.0
        self.total_extra_amount = 0.0
        self.product_cost = 0.0

        # TIER 2: Base profit fields
        self.pricelist_price_excl_vat = 0.0
        self.base_profit_per_unit = 0.0
        self.total_base_profit = 0.0

        # Reset qty picker to default
        self.calc_qty = 1