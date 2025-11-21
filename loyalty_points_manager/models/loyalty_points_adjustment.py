# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class LoyaltyPointsAdjustment(models.Model):
    _name = 'loyalty.points.adjustment'
    _description = 'Loyalty Points Adjustment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        default=lambda self: _('New'),
        copy=False,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        tracking=True,
        domain=[('customer_rank', '>', 0)],
    )
    operation_type = fields.Selection([
        ('add', 'Add Points'),
        ('reduce', 'Reduce Points'),
    ], string='Operation Type', required=True, tracking=True)
    
    points_amount = fields.Float(
        string='Points Amount',
        required=True,
        tracking=True,
    )
    balance_before = fields.Float(
        string='Balance Before',
        readonly=True,
    )
    balance_after = fields.Float(
        string='Balance After',
        readonly=True,
    )
    reason = fields.Text(
        string='Reason',
        required=True,
        tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    
    # Accounting fields
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        domain=[('type', '=', 'general')],
    )
    account_move_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        copy=False,
    )
    debit_account_id = fields.Many2one(
        'account.account',
        string='Debit Account',
        help='Account to debit when adding points',
    )
    credit_account_id = fields.Many2one(
        'account.account',
        string='Credit Account',
        help='Account to credit when adding points',
    )
    points_value = fields.Monetary(
        string='Monetary Value',
        currency_field='currency_id',
        help='Monetary value of the points adjustment',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    
    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('loyalty.points.adjustment') or _('New')
        return super(LoyaltyPointsAdjustment, self).create(vals)

    @api.constrains('points_amount')
    def _check_points_amount(self):
        for record in self:
            if record.points_amount <= 0:
                raise ValidationError(_('Points amount must be greater than zero.'))

    def action_confirm(self):
        """Confirm the loyalty points adjustment and create accounting entry"""
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft adjustments can be confirmed.'))
            
            # Get current loyalty points
            loyalty_card = self.env['loyalty.card'].search([
                ('partner_id', '=', record.partner_id.id),
                ('program_id.program_type', '=', 'loyalty'),
            ], limit=1)
            
            if not loyalty_card:
                # Create a new loyalty card if none exists
                loyalty_program = self.env['loyalty.program'].search([
                    ('program_type', '=', 'loyalty'),
                ], limit=1)
                
                if not loyalty_program:
                    raise UserError(_('No loyalty program found. Please create a loyalty program first.'))
                
                loyalty_card = self.env['loyalty.card'].create({
                    'partner_id': record.partner_id.id,
                    'program_id': loyalty_program.id,
                })
            
            record.balance_before = loyalty_card.points
            
            # Calculate new balance
            if record.operation_type == 'add':
                new_balance = loyalty_card.points + record.points_amount
            else:  # reduce
                new_balance = loyalty_card.points - record.points_amount
                if new_balance < 0:
                    raise UserError(_('Insufficient points. Current balance: %s') % loyalty_card.points)
            
            record.balance_after = new_balance
            
            # Update loyalty card points
            loyalty_card.points = new_balance
            
            # Create accounting entry if configured
            if record.journal_id and record.debit_account_id and record.credit_account_id and record.points_value:
                record._create_account_move()
            
            record.state = 'confirmed'
            
            # Post message to chatter
            record.message_post(
                body=_('Loyalty points adjustment confirmed. Points %s from %s to %s.') % (
                    'added' if record.operation_type == 'add' else 'reduced',
                    record.balance_before,
                    record.balance_after
                )
            )

    def action_cancel(self):
        """Cancel the loyalty points adjustment"""
        for record in self:
            if record.state == 'cancelled':
                raise UserError(_('Adjustment is already cancelled.'))
            
            if record.state == 'confirmed':
                # Reverse the points adjustment
                loyalty_card = self.env['loyalty.card'].search([
                    ('partner_id', '=', record.partner_id.id),
                    ('program_id.program_type', '=', 'loyalty'),
                ], limit=1)
                
                if loyalty_card:
                    if record.operation_type == 'add':
                        loyalty_card.points -= record.points_amount
                    else:
                        loyalty_card.points += record.points_amount
                
                # Cancel accounting entry
                if record.account_move_id and record.account_move_id.state == 'posted':
                    record.account_move_id.button_cancel()
            
            record.state = 'cancelled'
            record.message_post(body=_('Loyalty points adjustment cancelled.'))

    def action_draft(self):
        """Reset to draft"""
        for record in self:
            if record.state == 'confirmed':
                raise UserError(_('Cannot reset confirmed adjustment to draft. Please cancel it first.'))
            record.state = 'draft'

    def _create_account_move(self):
        """Create accounting journal entry for the points adjustment"""
        self.ensure_one()
        
        if self.account_move_id:
            return
        
        move_lines = []
        
        if self.operation_type == 'add':
            # Debit: Loyalty Points Expense/Asset
            # Credit: Liability (Customer Points Obligation)
            move_lines.append((0, 0, {
                'name': _('Loyalty Points - %s') % self.partner_id.name,
                'account_id': self.debit_account_id.id,
                'partner_id': self.partner_id.id,
                'debit': self.points_value,
                'credit': 0.0,
            }))
            move_lines.append((0, 0, {
                'name': _('Loyalty Points - %s') % self.partner_id.name,
                'account_id': self.credit_account_id.id,
                'partner_id': self.partner_id.id,
                'debit': 0.0,
                'credit': self.points_value,
            }))
        else:  # reduce
            # Reverse the entry
            move_lines.append((0, 0, {
                'name': _('Loyalty Points Reduction - %s') % self.partner_id.name,
                'account_id': self.credit_account_id.id,
                'partner_id': self.partner_id.id,
                'debit': self.points_value,
                'credit': 0.0,
            }))
            move_lines.append((0, 0, {
                'name': _('Loyalty Points Reduction - %s') % self.partner_id.name,
                'account_id': self.debit_account_id.id,
                'partner_id': self.partner_id.id,
                'debit': 0.0,
                'credit': self.points_value,
            }))
        
        move_vals = {
            'journal_id': self.journal_id.id,
            'date': fields.Date.today(),
            'ref': self.name,
            'line_ids': move_lines,
        }
        
        move = self.env['account.move'].create(move_vals)
        move.action_post()
        self.account_move_id = move.id

    def unlink(self):
        for record in self:
            if record.state == 'confirmed':
                raise UserError(_('Cannot delete confirmed adjustments. Please cancel them first.'))
        return super(LoyaltyPointsAdjustment, self).unlink()
