# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    courier_cogs_account_id = fields.Many2one(
        'account.account',
        string='Courier COGS Account',
        config_parameter='pos_courier_dispatch.courier_cogs_account_id',
        domain=[('account_type', '=', 'expense_direct_cost')],
        help='Account to use for courier fees paid by company (Cost of Goods Sold)',
    )
    
    default_courier_journal_id = fields.Many2one(
        'account.journal',
        string='Default Courier Payment Journal',
        config_parameter='pos_courier_dispatch.default_courier_journal_id',
        domain=[('type', 'in', ['bank', 'cash'])],
        help='Default journal for courier fee payments',
    )
