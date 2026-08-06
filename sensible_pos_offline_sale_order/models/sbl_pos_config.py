# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    sbl_create_sale_order = fields.Boolean('Create Sale Order')

    sbl_create_sale_order_action = fields.Selection([('draft', 'Draft'),
                                                    ('confirmed', 'Confirmed'),
                                                    ('delivered', 'Delivered'),
                                                    ('invoiced', 'Invoiced')],
        string="Sale Order Action",
        help="The action to perform when creating a Sale Order from a PoS Order.\n"
        "Draft: The Sale Order will be created in draft state.\n"
        "Confirmed: The Sale Order will be created in confirmed state.\n"
        "Delivered: The Sale Order will be created in confirmed state and the"
        " picking will be marked as delivered.\n"
        "Invoiced: The Sale Order will be created in confirmed state, the"
        " picking will be marked as delivered and the invoice will be generated"
        " and confirmed.\n"
        "Only invoice payment process will be possible.",
        default='draft',)