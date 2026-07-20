# -*- coding: utf-8 -*-
from odoo import _, models

from .attachment_requirement import ensure_linked_attachment


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def action_view_picking(self):
        if self.env.context.get('pnpc_require_attachment_before_receive_products'):
            ensure_linked_attachment(
                self,
                'purchase_net_price_compute.require_po_attachment_on_receive_products',
                _('Attach at least one document to the Purchase Order before clicking Receive Products.'),
            )
        return super().action_view_picking()
