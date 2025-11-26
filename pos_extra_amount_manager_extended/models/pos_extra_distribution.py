# -*- coding: utf-8 -*-
"""
POS Extra Amount Distribution Model (TIER 1)
Records commission payouts from extra amounts charged above pricelist.
Creates 3 journal entries per distribution.
"""
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PosExtraDistribution(models.Model):
    """
    Records of extra amount distributions with full journal entries.
    
    Creates 3 journal entries:
    1. Extra Revenue: Dr Cash / Cr Extra Revenue
    2. Product COGS: Dr COGS Product / Cr Stock Valuation
    3. Commission: Dr COGS Commission / Cr Cash
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
        index=True
    )
    
    # === DISPLAY ===
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True
    )
    
    # === AMOUNTS ===
    distribution_amount = fields.Monetary(
        string='Distribution Amount (Incl VAT)',
        required=True,
        currency_field='currency_id',
        help="Total amount including VAT"
    )
    
    distribution_amount_excl_vat = fields.Monetary(
        string='Amount Excl VAT',
        compute='_compute_vat_amounts',
        store=True,
        currency_field='currency_id',
        help="Commission amount excluding VAT"
    )
    
    vat_amount = fields.Monetary(
        string='VAT Amount',
        compute='_compute_vat_amounts',
        store=True,
        currency_field='currency_id',
        help="VAT portion of distribution"
    )
    
    vat_rate = fields.Float(
        string='VAT Rate (%)',
        compute='_compute_vat_amounts',
        store=True,
        help="VAT rate from product"
    )
    
    distribution_cogs = fields.Monetary(
        string='Proportional COGS',
        compute='_compute_proportional_cogs',
        store=True,
        currency_field='currency_id'
    )
    
    percent = fields.Float(
        string='Percent (%)',
        digits=(5, 2)
    )
    
    # === PAYMENT & ACCOUNTING ===
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        required=True,
        domain="[('type', 'in', ['cash', 'bank'])]"
    )
    
    cogs_commission_account_id = fields.Many2one(
        'account.account',
        string='Commission COGS Account',
        required=True,
        domain="[('account_type', '=', 'cogs')]"
    )
    
    output_vat_account_id = fields.Many2one(
        'account.account',
        string='Output VAT Account',
        required=True,
        domain="[('account_type', '=', 'liability_current')]",
        help="Account for VAT payable to tax authority"
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Recipient',
        required=True
    )
    
    # === JOURNAL ENTRY ===
    commission_move_id = fields.Many2one(
        'account.move',
        string='Commission Journal Entry',
        readonly=True
    )
    
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
    
    # === VAT SPLIT COMPUTATION ===
    @api.depends('distribution_amount', 'pos_order_id', 'pos_order_id.lines', 'pos_order_id.lines.product_id')
    def _compute_vat_amounts(self):
        """
        Split distribution amount into VAT-exclusive base and VAT portion.
        
        Formula:
        - Amount incl VAT = distribution_amount (what we distribute)
        - VAT rate from product taxes (e.g., 16%)
        - Amount excl VAT = Amount incl VAT / (1 + VAT rate)
        - VAT amount = Amount incl VAT - Amount excl VAT
        
        Example:
        - Distribution: 260 (incl VAT)
        - VAT rate: 16%
        - Amount excl VAT: 260 / 1.16 = 224.14
        - VAT amount: 260 - 224.14 = 35.86
        """
        for record in self:
            # Get VAT rate from first order line's product
            vat_rate = 0.0
            if record.pos_order_id and record.pos_order_id.lines:
                first_line = record.pos_order_id.lines[0]
                if first_line.product_id and first_line.product_id.taxes_id:
                    taxes = first_line.product_id.taxes_id.filtered(lambda t: t.amount_type == 'percent')
                    vat_rate = sum(taxes.mapped('amount')) / 100.0 if taxes else 0.0
            
            # Store VAT rate as percentage for display
            record.vat_rate = vat_rate * 100
            
            if vat_rate > 0:
                # Split: Amount excl VAT = Amount incl VAT / (1 + VAT rate)
                record.distribution_amount_excl_vat = record.distribution_amount / (1.0 + vat_rate)
                record.vat_amount = record.distribution_amount - record.distribution_amount_excl_vat
            else:
                # No VAT applicable
                record.distribution_amount_excl_vat = record.distribution_amount
                record.vat_amount = 0.0
    
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
    
    # === CREATE JOURNAL ENTRY WITH VAT SPLIT ===
    def action_create_journal_entries(self):
        """
        Create journal entry with VAT split (Option 3: Most Accounting-Correct).
        
        Journal Entry Structure:
        Dr COGS Commission [Amount Excl VAT]
        Dr Output VAT Payable [VAT Amount]        (only if VAT > 0)
            Cr Cash/Bank [Total Amount Incl VAT]
        
        Example (260 with 16% VAT):
        Dr COGS Commission: 224.14
        Dr Output VAT: 35.86
            Cr Cash: 260.00
        """
        self.ensure_one()
        if self.state == 'posted':
            raise UserError('Journal entry already posted.')
        
        cash_account = self.payment_journal_id.default_account_id
        if not cash_account:
            raise UserError(f'No default account in journal: {self.payment_journal_id.name}')
        
        # Validate Output VAT account if VAT amount exists
        if self.vat_amount > 0 and not self.output_vat_account_id:
            raise UserError('Output VAT Account is required when VAT amount exists.')
        
        move_date = fields.Date.context_today(self)
        
        # Build journal entry lines
        line_ids = []
        
        # LINE 1: Debit COGS Commission (Excl VAT)
        line_ids.append((0, 0, {
            'account_id': self.cogs_commission_account_id.id,
            'name': f'Extra Commission (Excl VAT) - {self.pos_order_id.name} - {self.partner_id.name}',
            'debit': self.distribution_amount_excl_vat,
            'credit': 0.0,
            'partner_id': self.partner_id.id,
        }))
        
        # LINE 2: Debit Output VAT (only if VAT exists)
        if self.vat_amount > 0:
            line_ids.append((0, 0, {
                'account_id': self.output_vat_account_id.id,
                'name': f'Output VAT on Extra Commission - {self.pos_order_id.name} ({self.vat_rate:.1f}%)',
                'debit': self.vat_amount,
                'credit': 0.0,
                'partner_id': self.partner_id.id,
            }))
        
        # LINE 3: Credit Cash/Bank (Total Incl VAT)
        line_ids.append((0, 0, {
            'account_id': cash_account.id,
            'name': f'Commission Payout (Incl VAT) - {self.pos_order_id.name}',
            'debit': 0.0,
            'credit': self.distribution_amount,
            'partner_id': self.partner_id.id,
        }))
        
        # Create journal entry
        move_vals = {
            'journal_id': self.payment_journal_id.id,
            'date': move_date,
            'ref': f'Extra Commission (VAT Split) - {self.pos_order_id.name}',
            'line_ids': line_ids,
        }
        move = self.env['account.move'].create(move_vals)
        self.commission_move_id = move.id
        self.state = 'posted'
        
        if self.pos_order_id.extra_state != 'distributed':
            self.pos_order_id.extra_state = 'distributed'
        
        # Notification with VAT breakdown
        vat_msg = f" (Excl VAT: {self.distribution_amount_excl_vat:.2f}, VAT: {self.vat_amount:.2f})" if self.vat_amount > 0 else ""
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Extra commission posted: {self.distribution_amount:.2f}{vat_msg} to {self.partner_id.name}',
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
