# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
from odoo import fields, models


class SblAppGateConfig(models.Model):
    _name = 'sbl.app.gate.config'
    _description = 'App Gate Configuration'
    _order = 'sequence, name'
    _rec_name = 'name'

    name = fields.Char(string='App Name', required=True)
    xmlid = fields.Char(
        string='Menu XML ID',
        required=True,
        index=True,
        help='The XML ID of the top-level menu item for this app (e.g. point_of_sale.menu_point_root).',
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ('unique_xmlid', 'UNIQUE(xmlid)', 'Each app XML ID must be unique in the App Gate configuration.'),
    ]
