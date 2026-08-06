# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    sbl_create_sale_order = fields.Boolean(
        related="pos_config_id.sbl_create_sale_order", readonly=False
    )
    sbl_create_sale_order_action = fields.Selection(
        related="pos_config_id.sbl_create_sale_order_action", readonly=False
    )