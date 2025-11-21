# -*- coding: utf-8 -*-
"""
Settings: Default COGS account for commission payouts
"""
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    pos_extra_cogs_commission_account_id = fields.Many2one(
        'account.account',
        string='Default Commission COGS Account',
        config_parameter='pos_extra_amount_manager.cogs_commission_account_id',
        domain="[('account_type', '=', 'cogs')]",  # CHANGED
        help="Default COGS account for commission distributions"
    )