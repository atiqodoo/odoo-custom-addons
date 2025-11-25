# -*- coding: utf-8 -*-
"""
Wizard: Distribute extra amount (percent or fixed) - TIER 1
"""
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PosExtraDistributionWizard(models.TransientModel):
    _name = 'pos.extra.distribution.wizard'
    _description = 'POS Extra Distribution Wizard'
    
    pos_order_id = fields.Many2one('pos.order', required=True, readonly=True)
    total_extra_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    remaining_extra_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    total_extra_cogs = fields.Monetary(readonly=True, currency_field='currency_id')
    
    input_method = fields.Selection([('percent', 'Percentage'), ('amount', 'Fixed Amount')], required=True, default='percent')
    percent = fields.Float(digits=(5, 2))
    amount = fields.Monetary(currency_field='currency_id')
    
    distribution_amount = fields.Monetary(compute='_compute_distribution_amount', store=True, readonly=True, currency_field='currency_id')
    distribution_cogs = fields.Monetary(compute='_compute_distribution_cogs', store=True, readonly=True, currency_field='currency_id')
    
    payment_journal_id = fields.Many2one('account.journal', required=True, domain="[('type', 'in', ['cash', 'bank'])]")
    cogs_commission_account_id = fields.Many2one('account.account', required=True, domain="[('account_type', '=', 'cogs')]")
    output_vat_account_id = fields.Many2one(
        'account.account', 
        string='Output VAT Account',
        required=True, 
        domain="[('account_type', '=', 'liability_current')]",
        help="Account for VAT payable on commissions"
    )
    partner_id = fields.Many2one('res.partner', required=True)
    
    currency_id = fields.Many2one(related='pos_order_id.currency_id')
    company_id = fields.Many2one(related='pos_order_id.company_id')
    
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        
        # Load COGS Commission Account from settings
        cogs_account_id = self.env['ir.config_parameter'].sudo().get_param('pos_extra_amount_manager.cogs_commission_account_id')
        if 'cogs_commission_account_id' in fields_list and cogs_account_id:
            res['cogs_commission_account_id'] = int(cogs_account_id)
        
        # Load Output VAT Account from settings
        vat_account_id = self.env['ir.config_parameter'].sudo().get_param('pos_extra_amount_manager.output_vat_account_id')
        if 'output_vat_account_id' in fields_list and vat_account_id:
            res['output_vat_account_id'] = int(vat_account_id)
        
        return res
    
    @api.depends('input_method', 'percent', 'amount', 'remaining_extra_amount')
    def _compute_distribution_amount(self):
        for wiz in self:
            if wiz.input_method == 'percent' and wiz.percent:
                wiz.distribution_amount = wiz.remaining_extra_amount * (wiz.percent / 100)
            elif wiz.input_method == 'amount':
                wiz.distribution_amount = wiz.amount
            else:
                wiz.distribution_amount = 0.0
    
    @api.depends('distribution_amount', 'total_extra_amount', 'total_extra_cogs')
    def _compute_distribution_cogs(self):
        for wiz in self:
            if wiz.total_extra_amount:
                wiz.distribution_cogs = wiz.total_extra_cogs * (wiz.distribution_amount / wiz.total_extra_amount)
            else:
                wiz.distribution_cogs = 0.0
    
    @api.constrains('percent', 'amount', 'distribution_amount')
    def _check_amounts(self):
        for wiz in self:
            if wiz.input_method == 'percent' and (wiz.percent <= 0 or wiz.percent > 100):
                raise ValidationError('Percent must be 0–100.')
            if wiz.input_method == 'amount' and wiz.amount <= 0:
                raise ValidationError('Amount must be positive.')
            if wiz.distribution_amount > wiz.remaining_extra_amount:
                raise ValidationError('Amount exceeds remaining.')
    
    def action_distribute(self):
        self.ensure_one()
        if not self.distribution_amount:
            raise UserError('Enter valid amount.')
        
        dist = self.env['pos.extra.distribution'].create({
            'pos_order_id': self.pos_order_id.id,
            'distribution_amount': self.distribution_amount,
            'percent': self.percent if self.input_method == 'percent' else 0.0,
            'payment_journal_id': self.payment_journal_id.id,
            'cogs_commission_account_id': self.cogs_commission_account_id.id,
            'output_vat_account_id': self.output_vat_account_id.id,
            'partner_id': self.partner_id.id,
        })
        dist.action_create_journal_entries()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pos.extra.distribution',
            'res_id': dist.id,
            'view_mode': 'form',
            'target': 'current',
        }
