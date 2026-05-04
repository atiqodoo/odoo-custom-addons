# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ========================================
    # COURIER DISPATCH CONFIGURATION
    # ========================================
    
    courier_cogs_account_id = fields.Many2one(
        'account.account',
        string='Courier COGS Account',
        config_parameter='pos_courier_dispatch.courier_cogs_account_id',
        domain=[('account_type', '=', 'expense_direct_cost')],
        help='Account to use for courier fees paid by company (Cost of Goods Sold) - Net amount excluding VAT',
    )
    
    courier_vat_account_id = fields.Many2one(
        'account.account',
        string='Courier VAT Input Account',
        config_parameter='pos_courier_dispatch.courier_vat_account_id',
        domain=[('account_type', '=', 'asset_current')],
        help='Account to use for VAT on courier fees (Input VAT claimable)',
    )
    
    courier_vat_rate = fields.Float(
        string='Courier VAT Rate (%)',
        config_parameter='pos_courier_dispatch.courier_vat_rate',
        default=16.0,
        help='VAT rate for courier services in Kenya (default: 16%)',
    )
    
    courier_fee_vat_inclusive = fields.Boolean(
        string='Courier Fees are VAT Inclusive',
        config_parameter='pos_courier_dispatch.courier_fee_vat_inclusive',
        default=True,
        help='If enabled, courier fee amounts entered include VAT and will be split. '
             'If disabled, VAT will be calculated on top of the entered amount.',
    )
    
    courier_payment_journal_id = fields.Many2one(
        'account.journal',
        string='Courier Payment Journal',
        config_parameter='pos_courier_dispatch.courier_payment_journal_id',
        domain=[('type', 'in', ['bank', 'cash'])],
        help='Default journal for recording courier payments when company pays',
    )