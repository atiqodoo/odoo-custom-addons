# -*- coding: utf-8 -*-
"""
Wizard: Distribute base profit (percent or fixed) - TIER 2
"""
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PosBaseProfitDistributionWizard(models.TransientModel):
    _name = 'pos.base.profit.distribution.wizard'
    _description = 'POS Base Profit Distribution Wizard'
    
    # === ORDER INFO ===
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        readonly=True
    )
    
    total_base_profit = fields.Monetary(
        string='Total Base Profit',
        readonly=True,
        currency_field='currency_id',
        help="Total base profit from this order (excl VAT)"
    )
    
    remaining_base_profit = fields.Monetary(
        string='Remaining Base Profit',
        readonly=True,
        currency_field='currency_id',
        help="Available base profit for distribution"
    )
    
    # === INPUT METHOD ===
    input_method = fields.Selection([
        ('percent', 'Percentage'),
        ('amount', 'Fixed Amount')
    ], string='Input Method', required=True, default='percent')
    
    percent = fields.Float(
        string='Percentage (%)',
        digits=(5, 2),
        help="Percentage of remaining base profit to distribute"
    )
    
    amount = fields.Monetary(
        string='Fixed Amount',
        currency_field='currency_id',
        help="Fixed amount to distribute from base profit"
    )
    
    # === COMPUTED DISTRIBUTION ===
    distribution_amount = fields.Monetary(
        string='Distribution Amount',
        compute='_compute_distribution_amount',
        store=True,
        readonly=True,
        currency_field='currency_id',
        help="Calculated distribution amount from base profit"
    )
    
    # === PAYMENT & RECIPIENT ===
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        required=True,
        domain="[('type', 'in', ['cash', 'bank'])]",
        help="Journal for payout"
    )
    
    cogs_commission_account_id = fields.Many2one(
        'account.account',
        string='Base Commission COGS Account',
        required=True,
        domain="[('account_type', '=', 'cogs')]",
        help="COGS account to debit (separate from extra commission)"
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Recipient',
        required=True,
        help="Partner receiving the base profit share"
    )
    
    # === CURRENCY & COMPANY ===
    currency_id = fields.Many2one(
        related='pos_order_id.currency_id'
    )
    company_id = fields.Many2one(
        related='pos_order_id.company_id'
    )
    
    # === DEFAULT GET ===
    @api.model
    def default_get(self, fields_list):
        """Load default base commission COGS account from settings."""
        res = super().default_get(fields_list)
        
        # Get default account from config (TIER 2 account)
        account_id = self.env['ir.config_parameter'].sudo().get_param(
            'pos_extra_amount_manager.base_profit_cogs_commission_account_id'
        )
        if 'cogs_commission_account_id' in fields_list and account_id:
            res['cogs_commission_account_id'] = int(account_id)
        
        return res
    
    # === COMPUTE DISTRIBUTION AMOUNT ===
    @api.depends('input_method', 'percent', 'amount', 'remaining_base_profit')
    def _compute_distribution_amount(self):
        """Calculate distribution amount based on input method."""
        for wiz in self:
            if wiz.input_method == 'percent' and wiz.percent:
                wiz.distribution_amount = wiz.remaining_base_profit * (wiz.percent / 100)
            elif wiz.input_method == 'amount':
                wiz.distribution_amount = wiz.amount
            else:
                wiz.distribution_amount = 0.0
    
    # === VALIDATION ===
    @api.constrains('percent', 'amount', 'distribution_amount')
    def _check_amounts(self):
        """Validate input amounts."""
        for wiz in self:
            # Validate percentage
            if wiz.input_method == 'percent':
                if wiz.percent <= 0 or wiz.percent > 100:
                    raise ValidationError('Percentage must be between 0 and 100.')
            
            # Validate fixed amount
            if wiz.input_method == 'amount':
                if wiz.amount <= 0:
                    raise ValidationError('Amount must be greater than zero.')
            
            # Validate distribution doesn't exceed remaining
            if wiz.distribution_amount > wiz.remaining_base_profit:
                raise ValidationError(
                    f'Distribution amount ({wiz.distribution_amount:.2f}) '
                    f'exceeds remaining base profit ({wiz.remaining_base_profit:.2f}).'
                )
    
    # === ACTION: DISTRIBUTE ===
    def action_distribute(self):
        """Create base profit distribution and post journal entry."""
        self.ensure_one()
        
        if not self.distribution_amount:
            raise UserError('Please enter a valid distribution amount.')
        
        # Create distribution record
        dist = self.env['pos.base.profit.distribution'].create({
            'pos_order_id': self.pos_order_id.id,
            'distribution_amount': self.distribution_amount,
            'percent': self.percent if self.input_method == 'percent' else 0.0,
            'payment_journal_id': self.payment_journal_id.id,
            'cogs_commission_account_id': self.cogs_commission_account_id.id,
            'partner_id': self.partner_id.id,
        })
        
        # Post journal entry
        dist.action_create_journal_entries()
        
        # Return to distribution record
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pos.base.profit.distribution',
            'res_id': dist.id,
            'view_mode': 'form',
            'target': 'current',
        }
