# -*- coding: utf-8 -*-
from odoo import _, models

from .attachment_requirement import ensure_linked_attachment


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        if self.env.context.get('pnpc_require_attachment_before_validate_receipt'):
            ensure_linked_attachment(
                self,
                'purchase_net_price_compute.require_receipt_attachment_on_validate',
                _('Attach at least one document to the receipt before clicking Validate.'),
            )
        return super().button_validate()
