# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class LoyaltyPointsWizard(models.TransientModel):
    _name = 'loyalty.points.wizard'
    _description = 'Loyalty Points Management Wizard'

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        domain=[('customer_rank', '>', 0)],
    )
    current_balance = fields.Float(
        string='Current Balance',
        readonly=True,
        compute='_compute_current_balance',
    )
    operation_type = fields.Selection([
        ('add', 'Add Points'),
        ('reduce', 'Reduce Points'),
    ], string='Operation Type', required=True, default='add')
    
    points_amount = fields.Float(
        string='Points Amount',
        required=True,
        default=0.0,
    )
    new_balance = fields.Float(
        string='New Balance',
        readonly=True,
        compute='_compute_new_balance',
    )
    reason = fields.Text(
        string='Reason',
        required=True,
    )
    
    # Accounting fields
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        domain=[('type', '=', 'general')],
    )
    debit_account_id = fields.Many2one(
        'account.account',
        string='Debit Account',
        help='Account to debit when adding points (e.g., Loyalty Expense)',
    )
    credit_account_id = fields.Many2one(
        'account.account',
        string='Credit Account',
        help='Account to credit when adding points (e.g., Loyalty Liability)',
    )
    points_value = fields.Monetary(
        string='Monetary Value',
        currency_field='currency_id',
        help='Monetary value of the points (for accounting purposes)',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    
    @api.depends('partner_id')
    def _compute_current_balance(self):
        """Compute the current loyalty points balance for the selected customer"""
        for wizard in self:
            if wizard.partner_id:
                loyalty_card = self.env['loyalty.card'].search([
                    ('partner_id', '=', wizard.partner_id.id),
                    ('program_id.program_type', '=', 'loyalty'),
                ], limit=1)
                wizard.current_balance = loyalty_card.points if loyalty_card else 0.0
            else:
                wizard.current_balance = 0.0

    @api.depends('current_balance', 'operation_type', 'points_amount')
    def _compute_new_balance(self):
        """Calculate the new balance based on operation type and points amount"""
        for wizard in self:
            if wizard.operation_type == 'add':
                wizard.new_balance = wizard.current_balance + wizard.points_amount
            elif wizard.operation_type == 'reduce':
                wizard.new_balance = wizard.current_balance - wizard.points_amount
            else:
                wizard.new_balance = wizard.current_balance

    @api.constrains('points_amount')
    def _check_points_amount(self):
        """Validate points amount"""
        for wizard in self:
            if wizard.points_amount <= 0:
                raise ValidationError(_('Points amount must be greater than zero.'))

    @api.constrains('operation_type', 'points_amount', 'current_balance')
    def _check_sufficient_points(self):
        """Check if customer has sufficient points for reduction"""
        for wizard in self:
            if wizard.operation_type == 'reduce' and wizard.points_amount > wizard.current_balance:
                raise ValidationError(
                    _('Insufficient points! Customer has %.2f points but you are trying to reduce %.2f points.') %
                    (wizard.current_balance, wizard.points_amount)
                )

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Reset fields when partner changes"""
        if self.partner_id:
            # Trigger recompute of current_balance
            self._compute_current_balance()
        else:
            self.current_balance = 0.0
            self.new_balance = 0.0

    @api.onchange('operation_type', 'points_amount')
    def _onchange_operation_or_amount(self):
        """Recalculate new balance when operation type or amount changes"""
        self._compute_new_balance()

    def action_apply(self):
        """Apply the loyalty points adjustment"""
        self.ensure_one()
        
        # Validate required fields
        if not self.partner_id:
            raise ValidationError(_('Please select a customer.'))
        
        if not self.operation_type:
            raise ValidationError(_('Please select an operation type.'))
        
        if self.points_amount <= 0:
            raise ValidationError(_('Points amount must be greater than zero.'))
        
        if not self.reason:
            raise ValidationError(_('Please provide a reason for this adjustment.'))
        
        # Check sufficient points for reduction
        if self.operation_type == 'reduce' and self.points_amount > self.current_balance:
            raise ValidationError(
                _('Insufficient points! Customer has %.2f points.') % self.current_balance
            )
        
        # Create loyalty points adjustment record
        adjustment_vals = {
            'partner_id': self.partner_id.id,
            'operation_type': self.operation_type,
            'points_amount': self.points_amount,
            'balance_before': self.current_balance,
            'reason': self.reason,
            'journal_id': self.journal_id.id if self.journal_id else False,
            'debit_account_id': self.debit_account_id.id if self.debit_account_id else False,
            'credit_account_id': self.credit_account_id.id if self.credit_account_id else False,
            'points_value': self.points_value if self.points_value else 0.0,
            'company_id': self.company_id.id,
        }
        
        adjustment = self.env['loyalty.points.adjustment'].create(adjustment_vals)
        
        # Confirm the adjustment automatically
        adjustment.action_confirm()
        
        # Return action to open the created adjustment record
        return {
            'type': 'ir.actions.act_window',
            'name': _('Loyalty Points Adjustment'),
            'res_model': 'loyalty.points.adjustment',
            'res_id': adjustment.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_cancel(self):
        """Cancel the wizard"""
        return {'type': 'ir.actions.act_window_close'}
