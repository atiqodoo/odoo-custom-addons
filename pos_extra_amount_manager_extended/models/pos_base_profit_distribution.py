# -*- coding: utf-8 -*-
"""
POS Base Profit Distribution Model (TIER 2)
Records base profit sharing payouts with simple commission journal entry.
Only creates 1 journal entry: Debit COGS (commission), Credit Cash/Bank.
Note: Sale revenue and product COGS already recorded in normal POS entries.
"""
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PosBaseProfitDistribution(models.Model):
    """
    Records of base profit distributions with simple commission entry.
    
    Creates 1 journal entry:
    - Debit: COGS Commission Account (Base Profit)
    - Credit: Cash/M-Pesa (payment journal)
    
    Note: Base sale revenue and product COGS are already in normal POS entries.
    This is TIER 2 - only accessible after TIER 1 (extra) fully distributed.
    """
    _name = 'pos.base.profit.distribution'
    _description = 'POS Base Profit Distribution'
    _inherit = ['mail.thread']
    _order = 'create_date desc'
    _rec_name = 'display_name'
    
    # === RELATIONS ===
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        ondelete='cascade',
        index=True,
        help="Source POS order for this base profit distribution"
    )
    
    # === DISPLAY ===
    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )
    
    # === AMOUNTS ===
    distribution_amount = fields.Monetary(
        string='Distribution Amount',
        required=True,
        currency_field='currency_id',
        help="Amount distributed from base profit (from % or fixed input)"
    )
    
    percent = fields.Float(
        string='Percent (%)',
        digits=(5, 2),
        help="Percentage of total base profit used for this distribution"
    )
    
    # === PAYMENT & ACCOUNTING ===
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        required=True,
        domain="[('type', 'in', ['cash', 'bank'])]",
        help="Journal used for payout (Cash, M-Pesa, etc.)"
    )
    
    cogs_commission_account_id = fields.Many2one(
        'account.account',
        string='Base Commission COGS Account',
        required=True,
        domain="[('account_type', '=', 'cogs')]",
        help="COGS account to debit for base profit commission payout (separate from extra commission)"
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Recipient',
        required=True,
        help="Partner receiving the base profit share"
    )
    
    # === JOURNAL ENTRY ===
    commission_move_id = fields.Many2one(
        'account.move',
        string='Commission Journal Entry',
        readonly=True,
        help="Generated journal entry for this base profit distribution"
    )
    
    # === STATE ===
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='draft', tracking=True)
    
    # === CURRENCY & COMPANY ===
    currency_id = fields.Many2one(
        related='pos_order_id.currency_id',
        store=True
    )
    company_id = fields.Many2one(
        related='pos_order_id.company_id',
        store=True
    )
    
    # === METADATA ===
    create_date = fields.Datetime(string='Created On', readonly=True)
    create_uid = fields.Many2one('res.users', string='Created By', readonly=True)
    
    # === COMPUTED NAME ===
    @api.depends('pos_order_id', 'distribution_amount', 'create_date')
    def _compute_display_name(self):
        for record in self:
            if record.pos_order_id:
                symbol = record.currency_id.symbol or ''
                record.display_name = f"{record.pos_order_id.name} - Base Profit {symbol}{record.distribution_amount:.2f}"
            else:
                record.display_name = "New Base Profit Distribution"
    
    # === VALIDATION ===
    @api.constrains('distribution_amount')
    def _check_distribution_amount(self):
        """Validate distribution amount doesn't exceed available base profit."""
        for record in self:
            if record.distribution_amount <= 0:
                raise ValidationError('Distribution amount must be greater than zero.')
            
            # Calculate total posted (excluding current record)
            posted = record.pos_order_id.base_profit_distribution_ids.filtered(
                lambda d: d.id != record.id and d.state == 'posted'
            )
            total_posted = sum(posted.mapped('distribution_amount'))
            available = record.pos_order_id.total_base_profit - total_posted
            
            if record.distribution_amount > available:
                raise ValidationError(
                    f'Distribution amount ({record.distribution_amount:.2f}) '
                    f'exceeds available base profit ({available:.2f}).'
                )
    
    # === CREATE JOURNAL ENTRY ===
    def action_create_journal_entries(self):
        """Create simple commission journal entry and post the distribution."""
        self.ensure_one()
        
        if self.state == 'posted':
            raise UserError('Journal entry already posted.')
        
        # Get payment journal's default account
        cash_account = self.payment_journal_id.default_account_id
        if not cash_account:
            raise UserError(
                f'No default account configured for journal: {self.payment_journal_id.name}'
            )
        
        move_date = fields.Date.context_today(self)
        
        # Create journal entry (SIMPLE: Only commission payout)
        move_vals = {
            'journal_id': self.payment_journal_id.id,
            'date': move_date,
            'ref': f'Base Profit Share - {self.pos_order_id.name}',
            'line_ids': [
                # Debit: COGS Commission (Base Profit)
                (0, 0, {
                    'account_id': self.cogs_commission_account_id.id,
                    'name': f'Base Profit Commission - {self.pos_order_id.name} - {self.partner_id.name}',
                    'debit': self.distribution_amount,
                    'credit': 0.0,
                    'partner_id': self.partner_id.id,
                }),
                # Credit: Cash/Bank
                (0, 0, {
                    'account_id': cash_account.id,
                    'name': f'Base Profit Payout - {self.pos_order_id.name}',
                    'debit': 0.0,
                    'credit': self.distribution_amount,
                    'partner_id': self.partner_id.id,
                }),
            ],
        }
        
        move = self.env['account.move'].create(move_vals)
        self.commission_move_id = move.id
        self.state = 'posted'
        
        # Update order state if first distribution
        if self.pos_order_id.profit_state != 'shared':
            self.pos_order_id.profit_state = 'shared'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Base profit shared: {self.currency_id.symbol}{self.distribution_amount:.2f} to {self.partner_id.name}',
                'type': 'success',
                'sticky': False,
            }
        }
    
    # === VIEW ENTRY ===
    def action_view_journal_entries(self):
        """Open the commission journal entry form."""
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
    
    # === PREVENT DELETE ===
    def unlink(self):
        """Prevent deletion of posted distributions."""
        for rec in self:
            if rec.state == 'posted':
                raise UserError('Cannot delete posted base profit distributions.')
        return super().unlink()
