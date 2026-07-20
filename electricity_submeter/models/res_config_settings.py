# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    electricity_journal_id = fields.Many2one(
        'account.journal', 
        string='Electricity Billing Journal', 
        config_parameter='electricity_submeter.electricity_journal_id',
        help="Journal used for invoicing electricity sub-meter consumption."
    )
    electricity_account_id = fields.Many2one(
        'account.account', 
        string='Electricity Revenue/Offset Account', 
        config_parameter='electricity_submeter.electricity_account_id',
        help="Account where electricity redistribution revenues (or expense offsets) are posted."
    )
    electricity_product_id = fields.Many2one(
        'product.product', 
        string='Default Electricity Service Product', 
        config_parameter='electricity_submeter.electricity_product_id',
        help="Default service product used on generated invoices."
    )
