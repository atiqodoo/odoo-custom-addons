# -*- coding: utf-8 -*-
"""
Settings: Default COGS accounts for both commission types
TIER 1: Extra Commission Account
TIER 2: Base Profit Commission Account (separate for better reporting)
"""
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    # === TIER 1: EXTRA AMOUNT COMMISSION ===
    pos_extra_cogs_commission_account_id = fields.Many2one(
        'account.account',
        string='Default Extra Commission COGS Account',
        config_parameter='pos_extra_amount_manager.cogs_commission_account_id',
        domain="[('account_type', '=', 'cogs')]",
        help="Default COGS account for extra amount commission distributions (TIER 1) - excl VAT portion"
    )
    
    pos_output_vat_account_id = fields.Many2one(
        'account.account',
        string='Default Output VAT Account',
        config_parameter='pos_extra_amount_manager.output_vat_account_id',
        domain="[('account_type', '=', 'liability_current')]",
        help="Default account for VAT payable on extra commissions (Output VAT)"
    )
    
    # === TIER 2: BASE PROFIT COMMISSION ===
    pos_base_profit_cogs_commission_account_id = fields.Many2one(
        'account.account',
        string='Default Base Profit Commission COGS Account',
        config_parameter='pos_extra_amount_manager.base_profit_cogs_commission_account_id',
        domain="[('account_type', '=', 'cogs')]",
        help="Default COGS account for base profit commission distributions (TIER 2) - separate from extra for better P&L reporting"
    )
