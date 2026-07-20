# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pnpc_require_po_attachment_on_receive_products = fields.Boolean(
        string='Require PO document before Receive Products',
        config_parameter='purchase_net_price_compute.require_po_attachment_on_receive_products',
        default=True,
    )
    pnpc_require_receipt_attachment_on_validate = fields.Boolean(
        string='Require receipt document before Validate',
        config_parameter='purchase_net_price_compute.require_receipt_attachment_on_validate',
        default=True,
    )
    pnpc_require_vendor_bill_attachment_on_confirm = fields.Boolean(
        string='Require bill document before Confirm',
        config_parameter='purchase_net_price_compute.require_vendor_bill_attachment_on_confirm',
        default=True,
    )
