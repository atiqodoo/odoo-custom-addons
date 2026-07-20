# -*- coding: utf-8 -*-
from odoo import _, models

from .attachment_requirement import ensure_linked_attachment


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        vendor_bills = self.filtered(
            lambda move: move.state == 'draft'
            and move.is_purchase_document(include_receipts=True)
        )
        ensure_linked_attachment(
            vendor_bills,
            'purchase_net_price_compute.require_vendor_bill_attachment_on_confirm',
            _('Attach at least one document to the vendor bill before clicking Confirm.'),
        )
        return super().action_post()
