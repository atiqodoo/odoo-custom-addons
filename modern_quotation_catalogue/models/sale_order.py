# -*- coding: utf-8 -*-
from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_open_modern_quotation_workspace(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'modern_quotation_catalogue.workspace',
            'name': 'Modern Quotation',
            'target': 'current',
            'context': {
                'default_order_id': self.id,
                'active_id': self.id,
                'active_model': 'sale.order',
            },
        }
