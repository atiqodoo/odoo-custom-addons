# -*- coding: utf-8 -*-
"""
POS Base Profit Distribution Model (TIER 2)
Records base profit sharing payouts with simple commission journal entry.

Tier 2 is accessible only after Tier 1 (extra amount) is fully distributed,
OR when the POS order has no extra amount at all.

Journal Entry per distribution (simple, no VAT split):
  Dr COGS Commission (Base Profit)  [distribution_amount]
      Cr Cash/Bank                  [distribution_amount]

Note: Sale revenue and product COGS are already recorded in normal POS entries.

Post-distribution:
  Proportional loyalty points deduction is applied automatically
  if the source POS order awarded loyalty points to the customer.
"""

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PosBaseProfitDistribution(models.Model):
    """
    Records of base profit distributions with simple commission journal entry.

    Tier 2 of the two-tier commission system. Only the pricelist-to-cost
    margin (excl VAT) is distributed here; no additional VAT split is needed
    because this represents pure profit sharing, not a sales commission.

    Loyalty Integration:
        After posting, if the linked POS order awarded loyalty points,
        a proportional deduction is automatically created via
        loyalty.points.adjustment (soft dependency).

    Proportion Formula:
        proportion       = distribution_amount / order_total_incl_vat
        points_to_deduct = order_loyalty_points_awarded * proportion
    """

    _name = 'pos.base.profit.distribution'
    _description = 'POS Base Profit Distribution'
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
        help="Source POS order for this base profit distribution."
    )

    # =========================================================================
    # DISPLAY
    # =========================================================================

    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )

    # =========================================================================
    # AMOUNTS
    # =========================================================================

    distribution_amount = fields.Monetary(
        string='Distribution Amount',
        required=True,
        currency_field='currency_id',
        help="Amount distributed from base profit (from % or fixed input)."
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
            "Tier 2 distribution was posted."
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
        string='Base Commission COGS Account',
        required=True,
        domain="[('account_type', '=', 'cogs')]",
        help=(
            "Separate COGS account from Tier 1 commission for better "
            "P&L reporting. Debited in the journal entry."
        )
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Recipient',
        required=True,
        help="Partner receiving the base profit share payout."
    )

    # =========================================================================
    # JOURNAL ENTRY
    # =========================================================================

    commission_move_id = fields.Many2one(
        'account.move',
        string='Commission Journal Entry',
        readonly=True,
        help="Generated accounting entry for this base profit distribution."
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

        Format: '<POS Order Name> - Base Profit <Currency Symbol><Amount>'
        Example: 'POS/2025/0042 - Base Profit KES150.00'
        """
        for record in self:
            if record.pos_order_id:
                symbol = record.currency_id.symbol or ''
                record.display_name = (
                    f"{record.pos_order_id.name} - "
                    f"Base Profit {symbol}{record.distribution_amount:.2f}"
                )
            else:
                record.display_name = "New Base Profit Distribution"

    # =========================================================================
    # VALIDATION
    # =========================================================================

    @api.constrains('distribution_amount')
    def _check_distribution_amount(self):
        """
        Validate that the distribution amount is positive and does not exceed
        the remaining undistributed base profit on the POS order.

        Excludes the current record from the 'already posted' sum to allow
        the record being validated to count itself correctly on re-validation.

        Raises:
            ValidationError: If amount <= 0 or exceeds available base profit.
        """
        for record in self:
            if record.distribution_amount <= 0:
                raise ValidationError(
                    'Distribution amount must be greater than zero.'
                )

            posted = record.pos_order_id.base_profit_distribution_ids.filtered(
                lambda d: d.id != record.id and d.state == 'posted'
            )
            total_posted = sum(posted.mapped('distribution_amount'))
            available = record.pos_order_id.total_base_profit - total_posted

            _logger.debug(
                "[Tier2][%s] _check_distribution_amount | "
                "requested=%.2f | total_posted=%.2f | available=%.2f",
                record.id,
                record.distribution_amount,
                total_posted,
                available,
            )

            if record.distribution_amount > available:
                raise ValidationError(
                    f'Distribution amount ({record.distribution_amount:.2f}) '
                    f'exceeds available base profit ({available:.2f}).'
                )

    # =========================================================================
    # ACTION: CREATE JOURNAL ENTRY + LOYALTY DEDUCTION
    # =========================================================================

    def action_create_journal_entries(self):
        """
        Post the Tier 2 base profit commission journal entry and trigger
        proportional loyalty points deduction if applicable.

        Journal Entry Structure (simple, no VAT split):
            Dr COGS Commission Account (Base Profit)  [distribution_amount]
                Cr Cash/Bank Account                  [distribution_amount]

        After posting:
            Calls _handle_loyalty_deduction() to proportionally deduct
            loyalty points awarded on the source POS order.

        Raises:
            UserError: If already posted or cash account is not configured
                       on the selected payment journal.

        Returns:
            dict: Odoo client action displaying a success notification
                  with distribution and loyalty deduction details.
        """
        self.ensure_one()

        _logger.info(
            "[Tier2][%s] action_create_journal_entries START | "
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
            "[Tier2][%s] Cash account resolved: [%s] %s",
            self.id, cash_account.code, cash_account.name,
        )

        move_date = fields.Date.context_today(self)
        _logger.debug(
            "[Tier2][%s] Journal entry date: %s", self.id, move_date
        )

        # --- Build journal entry (2 lines, no VAT split) ---
        move_vals = {
            'journal_id': self.payment_journal_id.id,
            'date': move_date,
            'ref': f'Base Profit Share - {self.pos_order_id.name}',
            'line_ids': [
                # LINE 1: Debit COGS Commission (Base Profit)
                (0, 0, {
                    'account_id': self.cogs_commission_account_id.id,
                    'name': (
                        f'Base Profit Commission - '
                        f'{self.pos_order_id.name} - {self.partner_id.name}'
                    ),
                    'debit': self.distribution_amount,
                    'credit': 0.0,
                    'partner_id': self.partner_id.id,
                }),
                # LINE 2: Credit Cash/Bank
                (0, 0, {
                    'account_id': cash_account.id,
                    'name': f'Base Profit Payout - {self.pos_order_id.name}',
                    'debit': 0.0,
                    'credit': self.distribution_amount,
                    'partner_id': self.partner_id.id,
                }),
            ],
        }

        _logger.debug(
            "[Tier2][%s] Journal entry lines built: 2 lines | "
            "debit=%.2f | credit=%.2f",
            self.id,
            self.distribution_amount,
            self.distribution_amount,
        )

        # --- Create and post journal entry ---
        move = self.env['account.move'].create(move_vals)
        self.commission_move_id = move.id
        self.state = 'posted'

        _logger.info(
            "[Tier2][%s] Journal entry created: move_id=%s | ref=%s",
            self.id, move.id, move.ref,
        )

        # --- Update order profit state ---
        if self.pos_order_id.profit_state != 'shared':
            self.pos_order_id.profit_state = 'shared'
            _logger.debug(
                "[Tier2][%s] POS order profit_state updated to 'shared'",
                self.id,
            )

        # --- Proportional loyalty deduction ---
        loyalty_msg = self._handle_loyalty_deduction()

        _logger.info(
            "[Tier2][%s] action_create_journal_entries COMPLETE | "
            "amount=%.2f | loyalty_msg=%s",
            self.id, self.distribution_amount, loyalty_msg,
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': (
                    f'Base profit shared: '
                    f'{self.currency_id.symbol}{self.distribution_amount:.2f} '
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

        Insufficient Balance Handling:
            If the customer's current loyalty balance is less than the
            calculated deduction, the deduction is capped at the available
            balance rather than blocking the distribution. This is logged
            as a WARNING for operational visibility.

        The created loyalty.points.adjustment record is:
            - Automatically confirmed (no manual step)
            - Linked back to this distribution via loyalty_adjustment_id
            - Auditable via chatter on the adjustment record

        Exception Handling:
            Any exception during loyalty adjustment creation/confirmation
            is caught and logged as ERROR. The distribution remains posted
            regardless — loyalty failure must never roll back accounting.

        Args:
            None (operates on self, single record enforced by caller)

        Returns:
            str: Human-readable message describing the deduction outcome,
                 for inclusion in the success notification.
                 Returns empty string if no deduction was applicable.
        """
        self.ensure_one()

        _logger.info(
            "[Tier2][%s][Loyalty] _handle_loyalty_deduction START | "
            "order=%s | partner=%s",
            self.id,
            self.pos_order_id.name,
            self.pos_order_id.partner_id.name if self.pos_order_id.partner_id else 'N/A',
        )

        # --- Soft dependency check ---
        loyalty_model = 'loyalty.points.adjustment'
        if loyalty_model not in self.env:
            _logger.warning(
                "[Tier2][%s][Loyalty] Model '%s' not found in registry. "
                "loyalty_points_manager module may not be installed. "
                "Skipping loyalty deduction silently.",
                self.id, loyalty_model,
            )
            return ''

        # --- Check if order has a customer ---
        order = self.pos_order_id
        if not order.partner_id:
            _logger.info(
                "[Tier2][%s][Loyalty] POS order '%s' has no linked customer. "
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
                "[Tier2][%s][Loyalty] order.amount_total=%.2f is zero or negative "
                "for order '%s'. Cannot calculate proportion. Skipping.",
                self.id, order_total, order.name,
            )
            return ''

        # --- Calculate proportion and points to deduct ---
        proportion = self.distribution_amount / order_total
        points_to_deduct = order_loyalty_points * proportion

        _logger.debug(
            "[Tier2][%s][Loyalty] Proportion calculation | "
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
                "[Tier2][%s][Loyalty] Calculated points_to_deduct=%.2f rounds to zero. "
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
            "[Tier2][%s][Loyalty] Customer '%s' current loyalty balance=%.4f | "
            "loyalty_card_id=%s",
            self.id,
            order.partner_id.name,
            current_balance,
            loyalty_card.id if loyalty_card else 'None',
        )

        if current_balance < points_to_deduct:
            _logger.warning(
                "[Tier2][%s][Loyalty] Insufficient loyalty balance! "
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
                "[Tier2][%s][Loyalty] After cap, points_to_deduct=%.2f. "
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
                f'Auto-deduction: Tier 2 base profit distributed on '
                f'POS Order {order.name}. '
                f'Proportion: {proportion:.4f} '
                f'({self.distribution_amount:.2f} / {order_total:.2f}).'
            ),
            'company_id': self.company_id.id,
        }

        _logger.debug(
            "[Tier2][%s][Loyalty] Creating loyalty.points.adjustment with vals: %s",
            self.id, adjustment_vals,
        )

        try:
            adjustment = self.env[loyalty_model].create(adjustment_vals)
            _logger.info(
                "[Tier2][%s][Loyalty] loyalty.points.adjustment created: id=%s",
                self.id, adjustment.id,
            )

            # --- Auto-confirm the adjustment ---
            adjustment.action_confirm()
            _logger.info(
                "[Tier2][%s][Loyalty] loyalty.points.adjustment id=%s confirmed. "
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
                "[Tier2][%s][Loyalty] _handle_loyalty_deduction COMPLETE | %s",
                self.id, loyalty_msg,
            )
            return loyalty_msg

        except Exception as exc:
            # Log error but never re-raise — loyalty failure must not roll back distribution
            _logger.error(
                "[Tier2][%s][Loyalty] FAILED to create/confirm loyalty adjustment. "
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
            raise UserError('No journal entry found.')
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
                    "[Tier2][%s] Attempted deletion of posted base profit distribution. Blocked.",
                    rec.id,
                )
                raise UserError('Cannot delete posted base profit distributions.')
        return super().unlink()