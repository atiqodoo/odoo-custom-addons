# -*- coding: utf-8 -*-
"""
POS Extra Amount Distribution Model
Records commission payouts from extra amounts charged above pricelist.
Only creates one journal entry: Debit COGS (commission), Credit Cash/Bank.
"""
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PosExtraDistribution(models.Model):
    """
    Records of extra amount distributions with commission journal entry.
    
    Creates 1 journal entry:
    - Debit: COGS Commission Account
    - Credit: Cash/M-Pesa (payment journal)
    
    Note: Extra revenue and base product COGS are already in normal POS entries.
    """
    _name = 'pos.extra.distribution'
    _description = 'POS Extra Amount Distribution'
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
        help="Source POS order for this distribution"
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
        help="Amount distributed (from % or fixed input)"
    )
    
    distribution_cogs = fields.Monetary(
        string='Proportional COGS',
        compute='_compute_proportional_cogs',
        store=True,
        currency_field='currency_id',
        help="Proportional COGS based on distribution ratio"
    )
    
    percent = fields.Float(
        string='Percent (%)',
        digits=(5, 2),
        help="Percentage of total extra used for this distribution"
    )
    
    # === PAYMENT & ACCOUNTING ===
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        required=True,
        domain="[('type', 'in', ['cash', 'bank'])]",
        help="Journal used for payout (Cash, M-Pesa, etc.)"
    )
    
    # Updated: COGS type account (not expense)
    cogs_commission_account_id = fields.Many2one(
        'account.account',
        string='Commission COGS Account',
        required=True,
        domain="[('account_type', '=', 'cogs')]",  # CHANGED: 'cogs' not 'expense'
        help="COGS account to debit for commission payout"
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Recipient',
        required=True,
        help="Partner receiving the commission"
    )
    
    # === JOURNAL ENTRY ===
    commission_move_id = fields.Many2one(
        'account.move',
        string='Commission Journal Entry',
        readonly=True
    )
    
    # Legacy compatibility
    cogs_commission_move_id = fields.Many2one(
        'account.move',
        string='Journal Entry (Legacy)',
        compute='_compute_legacy_move_id',
        store=False
    )
    
    @api.depends('commission_move_id')
    def _compute_legacy_move_id(self):
        for record in self:
            record.cogs_commission_move_id = record.commission_move_id
    
    # === STATE ===
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='draft', tracking=True)
    
    # === CURRENCY & COMPANY ===
    currency_id = fields.Many2one(related='pos_order_id.currency_id', store=True)
    company_id = fields.Many2one(related='pos_order_id.company_id', store=True)
    
    # === METADATA ===
    create_date = fields.Datetime(string='Created On', readonly=True)
    create_uid = fields.Many2one('res.users', string='Created By', readonly=True)
    
    # === COMPUTED NAME ===
    @api.depends('pos_order_id', 'distribution_amount', 'create_date')
    def _compute_display_name(self):
        for record in self:
            if record.pos_order_id:
                symbol = record.currency_id.symbol or ''
                record.display_name = f"{record.pos_order_id.name} - {symbol}{record.distribution_amount:.2f}"
            else:
                record.display_name = "New Distribution"
    
    # === PROPORTIONAL COGS ===
    @api.depends('distribution_amount', 'pos_order_id.total_extra_amount', 'pos_order_id.total_extra_cogs')
    def _compute_proportional_cogs(self):
        for record in self:
            total = record.pos_order_id.total_extra_amount
            if total and total > 0:
                proportion = record.distribution_amount / total
                record.distribution_cogs = record.pos_order_id.total_extra_cogs * proportion
            else:
                record.distribution_cogs = 0.0
    
    # === VALIDATION ===
    @api.constrains('distribution_amount')
    def _check_distribution_amount(self):
        for record in self:
            if record.distribution_amount <= 0:
                raise ValidationError('Distribution amount must be greater than zero.')
            
            posted = record.pos_order_id.extra_distribution_ids.filtered(
                lambda d: d.id != record.id and d.state == 'posted'
            )
            total_posted = sum(posted.mapped('distribution_amount'))
            available = record.pos_order_id.total_extra_amount - total_posted
            
            if record.distribution_amount > available:
                raise ValidationError(
                    f'Distribution ({record.distribution_amount:.2f}) exceeds available ({available:.2f}).'
                )
    
    # === CREATE JOURNAL ENTRY ===
    def action_create_journal_entries(self):
        self.ensure_one()
        if self.state == 'posted':
            raise UserError('Journal entry already posted.')
        
        cash_account = self.payment_journal_id.default_account_id
        if not cash_account:
            raise UserError(f'No default account in journal: {self.payment_journal_id.name}')
        
        move_date = fields.Date.context_today(self)
        
        move_vals = {
            'journal_id': self.payment_journal_id.id,
            'date': move_date,
            'ref': f'Commission Payout - {self.pos_order_id.name}',
            'line_ids': [
                # Debit: COGS Commission
                (0, 0, {
                    'account_id': self.cogs_commission_account_id.id,
                    'name': f'Commission - {self.pos_order_id.name} - {self.partner_id.name}',
                    'debit': self.distribution_amount,
                    'credit': 0.0,
                    'partner_id': self.partner_id.id,
                }),
                # Credit: Cash/Bank
                (0, 0, {
                    'account_id': cash_account.id,
                    'name': f'Payout - {self.pos_order_id.name}',
                    'debit': 0.0,
                    'credit': self.distribution_amount,
                    'partner_id': self.partner_id.id,
                }),
            ],
        }
        move = self.env['account.move'].create(move_vals)
        self.commission_move_id = move.id
        self.state = 'posted'
        
        if self.pos_order_id.extra_state != 'distributed':
            self.pos_order_id.extra_state = 'distributed'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Commission posted: {self.distribution_amount:.2f} to {self.partner_id.name}',
                'type': 'success',
                'sticky': False,
            }
        }
    
    # === VIEW ENTRY ===
    def action_view_journal_entries(self):
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
    
    # === PREVENT DELETE ===
    def unlink(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError('Cannot delete posted distributions.')
        return super().unlink()