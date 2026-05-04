# -*- coding: utf-8 -*-
"""
POS Order Extension
Manages two-tier distribution workflow:
TIER 1: Extra amounts (must complete first)
TIER 2: Base profit (unlocked after Tier 1 complete)
"""
from odoo import models, fields, api
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # === TIER 1: EXTRA AMOUNT STATE ===
    extra_state = fields.Selection([
        ('draft', 'Draft'),
        ('calculated', 'Calculated'),
        ('distributed', 'Distributed'),
    ], string='Extra State', default='draft', tracking=True)

    # === TIER 2: BASE PROFIT STATE ===
    profit_state = fields.Selection([
        ('draft', 'Draft'),
        ('calculated', 'Calculated'),
        ('shared', 'Shared'),
    ], string='Profit State', default='draft', tracking=True,
       help="Base profit state (unlocked after extra fully distributed)")

    # === TIER 1: EXTRA AMOUNT TOTALS ===
    total_extra_amount = fields.Monetary(
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )
    total_extra_cogs = fields.Monetary(
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )
    total_distributed_amount = fields.Monetary(
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )
    remaining_extra_amount = fields.Monetary(
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    # === TIER 2: BASE PROFIT TOTALS ===
    total_base_profit = fields.Monetary(
        string='Total Base Profit',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help="Sum of base profit from all lines (excl VAT)"
    )
    total_shared_base_profit = fields.Monetary(
        string='Total Shared Base Profit',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help="Sum of posted base profit distributions"
    )
    remaining_base_profit = fields.Monetary(
        string='Remaining Base Profit',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help="Base profit available for distribution"
    )

    # === RELATIONS ===
    extra_distribution_ids = fields.One2many(
        'pos.extra.distribution',
        'pos_order_id',
        string='Extra Distributions'
    )
    base_profit_distribution_ids = fields.One2many(
        'pos.base.profit.distribution',
        'pos_order_id',
        string='Base Profit Distributions'
    )

    # === COUNTS ===
    distribution_count = fields.Integer(
        string='Extra Distributions Count',
        compute='_compute_distribution_count',
        store=True
    )
    base_profit_distribution_count = fields.Integer(
        string='Base Profit Distributions Count',
        compute='_compute_distribution_count',
        store=True
    )

    # === COMPUTATION ===
    @api.depends(
        'lines.total_extra_amount', 'lines.product_cost', 'lines.total_base_profit',
        'extra_distribution_ids.distribution_amount', 'extra_distribution_ids.state',
        'base_profit_distribution_ids.distribution_amount', 'base_profit_distribution_ids.state'
    )
    def _compute_totals(self):
        for order in self:
            # TIER 1: Extra amount totals
            order.total_extra_amount = sum(order.lines.mapped('total_extra_amount'))
            order.total_extra_cogs = sum(order.lines.mapped('product_cost'))
            order.total_distributed_amount = sum(
                order.extra_distribution_ids.filtered(
                    lambda d: d.state == 'posted'
                ).mapped('distribution_amount')
            )
            order.remaining_extra_amount = order.total_extra_amount - order.total_distributed_amount

            # TIER 2: Base profit totals
            order.total_base_profit = sum(order.lines.mapped('total_base_profit'))
            posted_base = order.base_profit_distribution_ids.filtered(lambda d: d.state == 'posted')
            order.total_shared_base_profit = sum(posted_base.mapped('distribution_amount'))
            order.remaining_base_profit = order.total_base_profit - order.total_shared_base_profit

    @api.depends('extra_distribution_ids', 'base_profit_distribution_ids')
    def _compute_distribution_count(self):
        """Compute distribution counts for both tiers with bulletproof error handling."""
        for order in self:
            # Initialize with defaults
            extra_count = 0
            base_profit_count = 0

            # TIER 1 count - with comprehensive error handling
            try:
                if hasattr(order, 'extra_distribution_ids') and order.extra_distribution_ids is not False:
                    extra_count = len(order.extra_distribution_ids)
            except Exception:
                pass  # Keep default of 0

            # TIER 2 count - with comprehensive error handling
            try:
                if hasattr(order, 'base_profit_distribution_ids') and order.base_profit_distribution_ids is not False:
                    base_profit_count = len(order.base_profit_distribution_ids)
            except Exception:
                pass  # Keep default of 0

            # ALWAYS assign values - this is critical
            order.distribution_count = extra_count
            order.base_profit_distribution_count = base_profit_count

    # === TIER 1 ACTIONS: EXTRA AMOUNT ===

    def action_calculate_extra_amount(self):
        self.ensure_one()
        self.lines._compute_extra_and_profit()
        self.extra_state = 'calculated'
        return self._notify_success('Extra amounts calculated.')

    def action_open_distribution_wizard(self):
        self.ensure_one()
        if self.extra_state == 'draft':
            raise UserError('Calculate extra amounts first.')
        if self.remaining_extra_amount <= 0:
            raise UserError('No remaining extra amount to distribute.')
        return {
            'name': 'Distribute Extra',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.extra.distribution.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context | {
                'default_pos_order_id': self.id,
                'default_total_extra_amount': self.total_extra_amount,
                'default_remaining_extra_amount': self.remaining_extra_amount,
                'default_total_extra_cogs': self.total_extra_cogs,
            }
        }

    def action_view_distributions(self):
        return {
            'name': 'Extra Distributions',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.extra.distribution',
            'view_mode': 'list,form',
            'domain': [('pos_order_id', '=', self.id)],
        }

    def action_reset_extra_state(self):
        self.ensure_one()
        if self.extra_distribution_ids or self.base_profit_distribution_ids:
            raise UserError('Cannot reset with existing distributions.')
        self.extra_state = 'draft'
        self.profit_state = 'draft'
        return self._notify_success('State reset to Draft.')

    # === TIER 2 ACTIONS: BASE PROFIT ===

    def action_calculate_base_profit(self):
        """Calculate base profit - available after extra distributed OR when no extra exists."""
        self.ensure_one()

        # Allow if no extra amount OR if extra fully distributed
        has_no_extra = self.total_extra_amount <= 0
        extra_fully_distributed = (self.extra_state == 'distributed' and self.remaining_extra_amount == 0)

        if not has_no_extra and not extra_fully_distributed:
            # Only block if there IS extra but it's NOT fully distributed
            raise UserError(
                f'Complete extra amount distribution first.\n'
                f'Total Extra: {self.currency_id.symbol}{self.total_extra_amount:.2f}\n'
                f'Remaining: {self.currency_id.symbol}{self.remaining_extra_amount:.2f}'
            )

        # Trigger computation (already done by depends, but ensure fresh)
        self.lines._compute_extra_and_profit()

        # Update state
        self.profit_state = 'calculated'

        return self._notify_success(
            f'Base profit calculated: {self.currency_id.symbol}{self.total_base_profit:.2f}'
        )

    def action_open_base_profit_wizard(self):
        """Open base profit distribution wizard."""
        self.ensure_one()

        # Validation
        if self.profit_state == 'draft':
            raise UserError('Please calculate base profit first using the "Calculate Base Profit" button.')

        if self.remaining_base_profit <= 0:
            raise UserError('No remaining base profit to distribute.')

        # Open wizard
        return {
            'name': 'Share Base Profit',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.base.profit.distribution.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context | {
                'default_pos_order_id': self.id,
                'default_total_base_profit': self.total_base_profit,
                'default_remaining_base_profit': self.remaining_base_profit,
            }
        }

    def action_view_base_profit_distributions(self):
        """View all base profit distributions."""
        return {
            'name': 'Base Profit Distributions',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.base.profit.distribution',
            'view_mode': 'list,form',
            'domain': [('pos_order_id', '=', self.id)],
        }

    # === HELPER ===
    def _notify_success(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': message,
                'type': 'success',
                'sticky': False
            }
        }