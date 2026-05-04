# -*- coding: utf-8 -*-
"""
POS Extra Amount Distribution Model (TIER 1)
Records commission payouts from extra amounts charged above pricelist.

Journal Entry per distribution (VAT split):
  Dr COGS Commission     [Amount Excl VAT]
  Dr Output VAT Payable  [VAT Amount]       ← only if VAT > 0
      Cr Cash/Bank       [Total Incl VAT]

Post-distribution:
  Proportional loyalty points deduction is applied automatically
  if the source POS order awarded loyalty points to the customer.
"""

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PosExtraDistribution(models.Model):
    """
    Records of extra amount distributions with full VAT-split journal entries.

    Tier 1 of the two-tier commission system. Must be fully distributed
    before Tier 2 (base profit) becomes accessible.

    Loyalty Integration:
        After posting, if the linked POS order awarded loyalty points,
        a proportional deduction is automatically created via
        loyalty.points.adjustment (soft dependency).

    Proportion Formula:
        proportion       = distribution_amount / order_total_incl_vat
        points_to_deduct = order_loyalty_points_awarded * proportion
    """

    _name = 'pos.extra.distribution'
    _description = 'POS Extra Amount Distribution'
    _inherit = ['mail.thread']
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # =========================================================================
    # RELATIONS
    # =========================================================================

    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        ondelete='cascade',
        index=True,
        help="Source POS order for this extra amount distribution."
    )

    # =========================================================================
    # DISPLAY
    # =========================================================================

    display_name = fields.Char(
        compute='_compute_display_name',
        store=True
    )

    # =========================================================================
    # AMOUNTS
    # =========================================================================

    distribution_amount = fields.Monetary(
        string='Distribution Amount (Incl VAT)',
        required=True,
        currency_field='currency_id',
        help="Total distribution amount including VAT."
    )

    distribution_amount_excl_vat = fields.Monetary(
        string='Amount Excl VAT',
        compute='_compute_vat_amounts',
        store=True,
        currency_field='currency_id',
        help="Distribution amount excluding VAT (used in journal entry debit line)."
    )

    vat_amount = fields.Monetary(
        string='VAT Amount',
        compute='_compute_vat_amounts',
        store=True,
        currency_field='currency_id',
        help="VAT portion extracted from distribution amount."
    )

    vat_rate = fields.Float(
        string='VAT Rate (%)',
        compute='_compute_vat_amounts',
        store=True,
        help="Effective VAT rate derived from the first order line product taxes."
    )

    distribution_cogs = fields.Monetary(
        string='Proportional COGS',
        compute='_compute_proportional_cogs',
        store=True,
        currency_field='currency_id',
        help="COGS proportion relative to this distribution vs total extra amount."
    )

    percent = fields.Float(
        string='Percent (%)',
        digits=(5, 2),
        help="Percentage input used to calculate this distribution (0 if fixed amount used)."
    )

    # =========================================================================
    # LOYALTY INTEGRATION
    # =========================================================================

    loyalty_adjustment_id = fields.Many2one(
        'loyalty.points.adjustment',
        string='Loyalty Points Adjustment',
        readonly=True,
        copy=False,
        help=(
            "Auto-created loyalty.points.adjustment record that deducted "
            "proportional loyalty points from the customer after this "
            "Tier 1 distribution was posted."
        )
    )

    loyalty_points_deducted = fields.Float(
        string='Loyalty Points Deducted',
        readonly=True,
        default=0.0,
        help=(
            "Actual loyalty points deducted from the customer proportional "
            "to this distribution amount vs total POS order amount."
        )
    )

    # =========================================================================
    # PAYMENT & ACCOUNTING
    # =========================================================================

    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        required=True,
        domain="[('type', 'in', ['cash', 'bank'])]",
        help="Journal used for cash/bank payout."
    )

    cogs_commission_account_id = fields.Many2one(
        'account.account',
        string='Commission COGS Account',
        required=True,
        domain="[('account_type', '=', 'cogs')]",
        help="COGS account debited for the commission (excl VAT)."
    )

    output_vat_account_id = fields.Many2one(
        'account.account',
        string='Output VAT Account',
        required=True,
        domain="[('account_type', '=', 'liability_current')]",
        help="Liability account for VAT payable to tax authority on this commission."
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Recipient',
        required=True,
        help="Partner receiving this extra commission payout."
    )

    # =========================================================================
    # JOURNAL ENTRY
    # =========================================================================

    commission_move_id = fields.Many2one(
        'account.move',
        string='Commission Journal Entry',
        readonly=True,
        help="Generated accounting entry for this distribution."
    )

    # =========================================================================
    # STATE
    # =========================================================================

    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='draft', tracking=True)

    # =========================================================================
    # CURRENCY & COMPANY
    # =========================================================================

    currency_id = fields.Many2one(related='pos_order_id.currency_id', store=True)
    company_id = fields.Many2one(related='pos_order_id.company_id', store=True)

    # =========================================================================
    # METADATA
    # =========================================================================

    create_date = fields.Datetime(string='Created On', readonly=True)
    create_uid = fields.Many2one('res.users', string='Created By', readonly=True)

    # =========================================================================
    # COMPUTED: DISPLAY NAME
    # =========================================================================

    @api.depends('pos_order_id', 'distribution_amount', 'create_date')
    def _compute_display_name(self):
        """
        Compute a human-readable display name for the distribution record.

        Format: '<POS Order Name> - <Currency Symbol><Amount>'
        Example: 'POS/2025/0042 - KES260.00'
        """
        for record in self:
            if record.pos_order_id:
                symbol = record.currency_id.symbol or ''
                record.display_name = (
                    f"{record.pos_order_id.name} - {symbol}{record.distribution_amount:.2f}"
                )
            else:
                record.display_name = "New Distribution"

    # =========================================================================
    # COMPUTED: VAT SPLIT
    # =========================================================================

    @api.depends(
        'distribution_amount',
        'pos_order_id',
        'pos_order_id.lines',
        'pos_order_id.lines.product_id'
    )
    def _compute_vat_amounts(self):
        """
        Split the distribution amount (incl VAT) into base and VAT components.

        VAT rate is derived from percent-type taxes on the first order line product.
        If no VAT taxes exist, the full distribution amount is treated as excl VAT.

        Formula:
            amount_excl_vat = distribution_amount / (1 + vat_rate)
            vat_amount      = distribution_amount - amount_excl_vat

        Example (KES 260 @ 16% VAT):
            amount_excl_vat = 260 / 1.16 = 224.14
            vat_amount      = 260 - 224.14 = 35.86
        """
        for record in self:
            _logger.debug(
                "[Tier1][%s] _compute_vat_amounts | distribution_amount=%.2f | "
                "order=%s",
                record.id,
                record.distribution_amount,
                record.pos_order_id.name if record.pos_order_id else 'N/A',
            )

            vat_rate = 0.0
            if record.pos_order_id and record.pos_order_id.lines:
                first_line = record.pos_order_id.lines[0]
                if first_line.product_id and first_line.product_id.taxes_id:
                    taxes = first_line.product_id.taxes_id.filtered(
                        lambda t: t.amount_type == 'percent'
                    )
                    vat_rate = sum(taxes.mapped('amount')) / 100.0 if taxes else 0.0
                    _logger.debug(
                        "[Tier1][%s] VAT rate resolved from product '%s': %.4f (%.2f%%)",
                        record.id,
                        first_line.product_id.name,
                        vat_rate,
                        vat_rate * 100,
                    )

            record.vat_rate = vat_rate * 100

            if vat_rate > 0:
                record.distribution_amount_excl_vat = (
                    record.distribution_amount / (1.0 + vat_rate)
                )
                record.vat_amount = (
                    record.distribution_amount - record.distribution_amount_excl_vat
                )
            else:
                record.distribution_amount_excl_vat = record.distribution_amount
                record.vat_amount = 0.0

            _logger.debug(
                "[Tier1][%s] VAT split result | excl_vat=%.2f | vat=%.2f | rate=%.2f%%",
                record.id,
                record.distribution_amount_excl_vat,
                record.vat_amount,
                record.vat_rate,
            )

    # =========================================================================
    # COMPUTED: PROPORTIONAL COGS
    # =========================================================================

    @api.depends(
        'distribution_amount',
        'pos_order_id.total_extra_amount',
        'pos_order_id.total_extra_cogs'
    )
    def _compute_proportional_cogs(self):
        """
        Compute the COGS portion attributable to this specific distribution.

        Proportion is calculated as:
            proportion        = distribution_amount / total_extra_amount
            distribution_cogs = total_extra_cogs * proportion

        If total_extra_amount is zero, distribution_cogs defaults to 0.0
        to prevent division by zero.
        """
        for record in self:
            total = record.pos_order_id.total_extra_amount
            _logger.debug(
                "[Tier1][%s] _compute_proportional_cogs | "
                "distribution_amount=%.2f | total_extra_amount=%.2f | total_extra_cogs=%.2f",
                record.id,
                record.distribution_amount,
                total,
                record.pos_order_id.total_extra_cogs,
            )
            if total and total > 0:
                proportion = record.distribution_amount / total
                record.distribution_cogs = record.pos_order_id.total_extra_cogs * proportion
                _logger.debug(
                    "[Tier1][%s] COGS proportion=%.6f | distribution_cogs=%.2f",
                    record.id, proportion, record.distribution_cogs,
                )
            else:
                record.distribution_cogs = 0.0
                _logger.debug(
                    "[Tier1][%s] total_extra_amount is zero — distribution_cogs set to 0.0",
                    record.id,
                )

    # =========================================================================
    # VALIDATION
    # =========================================================================

    @api.constrains('distribution_amount')
    def _check_distribution_amount(self):
        """
        Validate that the distribution amount is positive and does not exceed
        the remaining undistributed extra amount on the POS order.

        Raises:
            ValidationError: If amount <= 0 or exceeds available extra amount.
        """
        for record in self:
            if record.distribution_amount <= 0:
                raise ValidationError('Distribution amount must be greater than zero.')

            posted = record.pos_order_id.extra_distribution_ids.filtered(
                lambda d: d.id != record.id and d.state == 'posted'
            )
            total_posted = sum(posted.mapped('distribution_amount'))
            available = record.pos_order_id.total_extra_amount - total_posted

            _logger.debug(
                "[Tier1][%s] _check_distribution_amount | "
                "requested=%.2f | total_posted=%.2f | available=%.2f",
                record.id,
                record.distribution_amount,
                total_posted,
                available,
            )

            if record.distribution_amount > available:
                raise ValidationError(
                    f'Distribution ({record.distribution_amount:.2f}) '
                    f'exceeds available ({available:.2f}).'
                )

    # =========================================================================
    # ACTION: CREATE JOURNAL ENTRY + LOYALTY DEDUCTION
    # =========================================================================

    def action_create_journal_entries(self):
        """
        Post the Tier 1 extra commission journal entry (VAT split) and
        trigger proportional loyalty points deduction if applicable.

        Journal Entry Structure:
            Dr COGS Commission Account  [distribution_amount_excl_vat]
            Dr Output VAT Account       [vat_amount]          ← if VAT > 0
                Cr Cash/Bank Account    [distribution_amount]  (total incl VAT)

        After posting:
            Calls _handle_loyalty_deduction() to proportionally deduct
            loyalty points awarded on the source POS order.

        Raises:
            UserError: If already posted, cash account missing, or VAT
                       account missing when VAT amount exists.

        Returns:
            dict: Odoo client action displaying a success notification
                  with distribution and loyalty deduction details.
        """
        self.ensure_one()

        _logger.info(
            "[Tier1][%s] action_create_journal_entries START | "
            "order=%s | partner=%s | amount=%.2f",
            self.id,
            self.pos_order_id.name,
            self.partner_id.name,
            self.distribution_amount,
        )

        if self.state == 'posted':
            raise UserError('Journal entry already posted.')

        # --- Resolve cash/bank account ---
        cash_account = self.payment_journal_id.default_account_id
        if not cash_account:
            raise UserError(
                f'No default account configured for journal: '
                f'{self.payment_journal_id.name}'
            )
        _logger.debug(
            "[Tier1][%s] Cash account resolved: [%s] %s",
            self.id, cash_account.code, cash_account.name,
        )

        # --- VAT account check ---
        if self.vat_amount > 0 and not self.output_vat_account_id:
            raise UserError(
                'Output VAT Account is required when VAT amount exists.'
            )

        move_date = fields.Date.context_today(self)
        _logger.debug(
            "[Tier1][%s] Journal entry date: %s", self.id, move_date
        )

        # --- Build journal entry lines ---
        line_ids = [
            # LINE 1: Debit COGS Commission (excl VAT)
            (0, 0, {
                'account_id': self.cogs_commission_account_id.id,
                'name': (
                    f'Extra Commission (Excl VAT) - '
                    f'{self.pos_order_id.name} - {self.partner_id.name}'
                ),
                'debit': self.distribution_amount_excl_vat,
                'credit': 0.0,
                'partner_id': self.partner_id.id,
            }),
        ]

        if self.vat_amount > 0:
            # LINE 2: Debit Output VAT
            line_ids.append((0, 0, {
                'account_id': self.output_vat_account_id.id,
                'name': (
                    f'Output VAT on Extra Commission - '
                    f'{self.pos_order_id.name} ({self.vat_rate:.1f}%)'
                ),
                'debit': self.vat_amount,
                'credit': 0.0,
                'partner_id': self.partner_id.id,
            }))
            _logger.debug(
                "[Tier1][%s] VAT line added: account=[%s] amount=%.2f",
                self.id,
                self.output_vat_account_id.code,
                self.vat_amount,
            )

        # LINE 3: Credit Cash/Bank (total incl VAT)
        line_ids.append((0, 0, {
            'account_id': cash_account.id,
            'name': (
                f'Commission Payout (Incl VAT) - {self.pos_order_id.name}'
            ),
            'debit': 0.0,
            'credit': self.distribution_amount,
            'partner_id': self.partner_id.id,
        }))

        _logger.debug(
            "[Tier1][%s] Journal entry lines built: %d lines | "
            "debit_total=%.2f | credit_total=%.2f",
            self.id,
            len(line_ids),
            self.distribution_amount_excl_vat + self.vat_amount,
            self.distribution_amount,
        )

        # --- Create journal entry ---
        move = self.env['account.move'].create({
            'journal_id': self.payment_journal_id.id,
            'date': move_date,
            'ref': f'Extra Commission (VAT Split) - {self.pos_order_id.name}',
            'line_ids': line_ids,
        })
        self.commission_move_id = move.id
        self.state = 'posted'

        _logger.info(
            "[Tier1][%s] Journal entry created and posted: move_id=%s | ref=%s",
            self.id, move.id, move.ref,
        )

        # --- Update order extra state ---
        if self.pos_order_id.extra_state != 'distributed':
            self.pos_order_id.extra_state = 'distributed'
            _logger.debug(
                "[Tier1][%s] POS order extra_state updated to 'distributed'",
                self.id,
            )

        # --- Proportional loyalty deduction ---
        loyalty_msg = self._handle_loyalty_deduction()

        # --- Build success notification ---
        vat_msg = (
            f" (Excl VAT: {self.distribution_amount_excl_vat:.2f}, "
            f"VAT: {self.vat_amount:.2f})"
            if self.vat_amount > 0 else ""
        )

        _logger.info(
            "[Tier1][%s] action_create_journal_entries COMPLETE | "
            "amount=%.2f%s | loyalty_msg=%s",
            self.id, self.distribution_amount, vat_msg, loyalty_msg,
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': (
                    f'Extra commission posted: '
                    f'{self.distribution_amount:.2f}{vat_msg} '
                    f'to {self.partner_id.name}. {loyalty_msg}'
                ),
                'type': 'success',
                'sticky': False,
            }
        }

    # =========================================================================
    # LOYALTY: PROPORTIONAL DEDUCTION HANDLER
    # =========================================================================

    def _handle_loyalty_deduction(self):
        """
        Proportionally deduct loyalty points from the POS order customer
        based on the ratio of this distribution to the total order amount.

        This method uses a soft dependency on the 'loyalty.points.adjustment'
        model. If the model is not installed, the method exits silently without
        raising any error, allowing the module to function independently.

        Proportion Formula:
            proportion       = distribution_amount / order.amount_total
            points_to_deduct = order_loyalty_points_awarded * proportion

        Loyalty points awarded on the order are read from:
            pos_order_id.loyalty_points  (standard Odoo POS field)

        If points_to_deduct rounds to 0 after applying the proportion,
        no adjustment record is created and the method exits silently.

        The created loyalty.points.adjustment record is:
            - Automatically confirmed (no manual step)
            - Linked back to this distribution via loyalty_adjustment_id
            - Auditable via chatter on the adjustment record

        Args:
            None (operates on self, single record enforced by caller)

        Returns:
            str: A human-readable message describing the deduction outcome,
                 intended for inclusion in the success notification.
                 Returns empty string if no deduction was applicable.
        """
        self.ensure_one()

        _logger.info(
            "[Tier1][%s][Loyalty] _handle_loyalty_deduction START | "
            "order=%s | partner=%s",
            self.id,
            self.pos_order_id.name,
            self.pos_order_id.partner_id.name if self.pos_order_id.partner_id else 'N/A',
        )

        # --- Soft dependency check ---
        loyalty_model = 'loyalty.points.adjustment'
        if loyalty_model not in self.env:
            _logger.warning(
                "[Tier1][%s][Loyalty] Model '%s' not found in registry. "
                "loyalty_points_manager module may not be installed. "
                "Skipping loyalty deduction silently.",
                self.id, loyalty_model,
            )
            return ''

        # --- Check if order has a customer ---
        order = self.pos_order_id
        if not order.partner_id:
            _logger.info(
                "[Tier1][%s][Loyalty] POS order '%s' has no linked customer. "
                "No loyalty deduction applicable.",
                self.id, order.name,
            )
            return ''

                # --- Check if loyalty points were awarded on this order ---
                # --- Detect loyalty points awarded on this order ---
        # pos.order does NOT reliably store loyalty points in Odoo 18.
        # Points are tracked in loyalty.card and its history lines.
        # We use a two-pass strategy:
        #   Pass 1: Search loyalty.card where source_pos_order_id = order.id
        #           (covers newly created cards from this order)
        #   Pass 2: Search loyalty card history lines where order_id = order.id
        #           (covers points added to existing cards on this order)

        order_loyalty_points = 0.0

        # --- Pass 1: Cards created by this order ---
        cards_from_order = self.env['loyalty.card'].search([
            ('source_pos_order_id', '=', order.id),
            ('program_id.program_type', '=', 'loyalty'),
        ])
        _logger.debug(
            "[Tier1][%s][Loyalty] Pass 1 — loyalty.card with source_pos_order_id=%s: "
            "found %d card(s)",
            self.id, order.id, len(cards_from_order),
        )
        if cards_from_order:
            # Sum initial points on cards created by this order
            order_loyalty_points = sum(cards_from_order.mapped('points'))
            _logger.debug(
                "[Tier1][%s][Loyalty] Pass 1 points from new cards: %.4f",
                self.id, order_loyalty_points,
            )

        # --- Pass 2: History lines on existing cards for this order ---
        # Try known history model names (Odoo 18 uses loyalty.history internally)
        history_model = None
        for candidate in ['loyalty.history', 'loyalty.card.history']:
            if candidate in self.env:
                history_model = candidate
                _logger.debug(
                    "[Tier1][%s][Loyalty] History model found: '%s'",
                    self.id, candidate,
                )
                break

        if history_model:
            history_lines = self.env[history_model].search([
                ('order_id', '=', order.id),
            ])
            issued_from_history = sum(
                line.issued for line in history_lines
                if hasattr(line, 'issued') and (line.issued or 0.0) > 0
            )
            _logger.debug(
                "[Tier1][%s][Loyalty] Pass 2 — history lines for order_id=%s: "
                "found %d line(s) | total issued=%.4f",
                self.id, order.id,
                len(history_lines),
                issued_from_history,
            )
            # Use whichever is greater — avoid double counting if Pass 1 already found points
            if issued_from_history > order_loyalty_points:
                order_loyalty_points = issued_from_history
                _logger.debug(
                    "[Tier1][%s][Loyalty] Using history-based points: %.4f",
                    self.id, order_loyalty_points,
                )
        else:
            _logger.warning(
                "[Tier1][%s][Loyalty] No history model found in registry. "
                "Pass 2 skipped. Only Pass 1 result used.",
                self.id,
            )

        # --- Fallback: Check partner's card for points linked to this order ---
        # If both passes return 0, try checking if partner has a card whose
        # source_pos_order_id matches — handles edge case where program_type
        # filter excluded a valid card above
        if order_loyalty_points <= 0 and order.partner_id:
            fallback_cards = self.env['loyalty.card'].search([
                ('source_pos_order_id', '=', order.id),
            ])
            if fallback_cards:
                order_loyalty_points = sum(fallback_cards.mapped('points'))
                _logger.debug(
                    "[Tier1][%s][Loyalty] Fallback Pass — cards without program_type filter: "
                    "%.4f pts from %d card(s)",
                    self.id, order_loyalty_points, len(fallback_cards),
                )

        _logger.info(
            "[Tier1][%s][Loyalty] Total loyalty points attributed to order '%s': %.4f",
            self.id, order.name, order_loyalty_points,
        )

        if order_loyalty_points <= 0:
            _logger.info(
                "[Tier1][%s][Loyalty] No loyalty points detected on order '%s' "
                "after all passes. Skipping deduction.",
                self.id, order.name,
            )
            return ''

        # --- Resolve order total for proportion base ---
        order_total = order.amount_total
        if not order_total or order_total <= 0:
            _logger.warning(
                "[Tier1][%s][Loyalty] order.amount_total=%.2f is zero or negative "
                "for order '%s'. Cannot calculate proportion. Skipping.",
                self.id, order_total, order.name,
            )
            return ''

        # --- Calculate proportion and points to deduct ---
        proportion = self.distribution_amount / order_total
        points_to_deduct = order_loyalty_points * proportion

        _logger.debug(
            "[Tier1][%s][Loyalty] Proportion calculation | "
            "distribution_amount=%.2f / order_total=%.2f = proportion=%.6f | "
            "order_loyalty_points=%.4f * proportion = points_to_deduct=%.4f",
            self.id,
            self.distribution_amount,
            order_total,
            proportion,
            order_loyalty_points,
            points_to_deduct,
        )

        # --- Round to 2 decimal places ---
        points_to_deduct = round(points_to_deduct, 2)

        if points_to_deduct <= 0:
            _logger.info(
                "[Tier1][%s][Loyalty] Calculated points_to_deduct=%.2f rounds to zero. "
                "No adjustment created.",
                self.id, points_to_deduct,
            )
            return ''

        # --- Check current customer loyalty balance ---
        loyalty_card = self.env['loyalty.card'].search([
            ('partner_id', '=', order.partner_id.id),
            ('program_id.program_type', '=', 'loyalty'),
        ], limit=1)

        current_balance = loyalty_card.points if loyalty_card else 0.0
        _logger.debug(
            "[Tier1][%s][Loyalty] Customer '%s' current loyalty balance=%.4f | "
            "loyalty_card_id=%s",
            self.id,
            order.partner_id.name,
            current_balance,
            loyalty_card.id if loyalty_card else 'None',
        )

        if current_balance < points_to_deduct:
            # Deduct whatever is available rather than blocking the distribution
            _logger.warning(
                "[Tier1][%s][Loyalty] Insufficient loyalty balance! "
                "Requested deduction=%.2f but current_balance=%.4f for customer '%s'. "
                "Deduction capped at current balance.",
                self.id,
                points_to_deduct,
                current_balance,
                order.partner_id.name,
            )
            points_to_deduct = round(current_balance, 2)

        if points_to_deduct <= 0:
            _logger.info(
                "[Tier1][%s][Loyalty] After cap, points_to_deduct=%.2f. "
                "No adjustment created.",
                self.id, points_to_deduct,
            )
            return ''

        # --- Create loyalty.points.adjustment record ---
        adjustment_vals = {
            'partner_id': order.partner_id.id,
            'operation_type': 'reduce',
            'points_amount': points_to_deduct,
            'balance_before': current_balance,
            'reason': (
                f'Auto-deduction: Tier 1 extra commission distributed on '
                f'POS Order {order.name}. '
                f'Proportion: {proportion:.4f} '
                f'({self.distribution_amount:.2f} / {order_total:.2f}).'
            ),
            'company_id': self.company_id.id,
        }

        _logger.debug(
            "[Tier1][%s][Loyalty] Creating loyalty.points.adjustment with vals: %s",
            self.id, adjustment_vals,
        )

        try:
            adjustment = self.env[loyalty_model].create(adjustment_vals)
            _logger.info(
                "[Tier1][%s][Loyalty] loyalty.points.adjustment created: id=%s",
                self.id, adjustment.id,
            )

            # --- Auto-confirm the adjustment ---
            adjustment.action_confirm()
            _logger.info(
                "[Tier1][%s][Loyalty] loyalty.points.adjustment id=%s confirmed. "
                "New customer balance=%.4f",
                self.id,
                adjustment.id,
                adjustment.balance_after,
            )

            # --- Link adjustment back to this distribution ---
            self.loyalty_adjustment_id = adjustment.id
            self.loyalty_points_deducted = points_to_deduct

            loyalty_msg = (
                f'Loyalty points deducted: {points_to_deduct:.2f} pts '
                f'from {order.partner_id.name} '
                f'(proportion: {proportion * 100:.2f}% of order).'
            )
            _logger.info(
                "[Tier1][%s][Loyalty] _handle_loyalty_deduction COMPLETE | %s",
                self.id, loyalty_msg,
            )
            return loyalty_msg

        except Exception as exc:
            # Log but do not re-raise — loyalty failure must not roll back distribution
            _logger.error(
                "[Tier1][%s][Loyalty] FAILED to create/confirm loyalty adjustment. "
                "Distribution will remain posted. Error: %s",
                self.id, str(exc),
                exc_info=True,
            )
            return 'Loyalty deduction could not be applied (see logs).'

    # =========================================================================
    # VIEW JOURNAL ENTRY
    # =========================================================================

    def action_view_journal_entries(self):
        """
        Open the commission journal entry form view.

        Raises:
            UserError: If no journal entry exists on this record.

        Returns:
            dict: Odoo window action opening account.move form.
        """
        self.ensure_one()
        if not self.commission_move_id:
            raise UserError('No journal entry.')
        return {
            'name': 'Journal Entry',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.commission_move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # =========================================================================
    # PREVENT DELETE
    # =========================================================================

    def unlink(self):
        """
        Prevent deletion of posted distribution records.

        Raises:
            UserError: If any record in the recordset has state 'posted'.
        """
        for rec in self:
            if rec.state == 'posted':
                _logger.warning(
                    "[Tier1][%s] Attempted deletion of posted distribution. Blocked.",
                    rec.id,
                )
                raise UserError('Cannot delete posted distributions.')
        return super().unlink()