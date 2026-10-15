# -*- coding: utf-8 -*-
import logging

from odoo import models
from odoo.tools.float_utils import float_is_zero


_logger = logging.getLogger(__name__)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _get_combined_lpo_gross_billed_qty(self):
        self.ensure_one()
        billed_qty = 0.0
        for invoice_line in self.invoice_lines:
            move = invoice_line.move_id
            if move.state == 'cancel' or move.move_type != 'in_invoice':
                continue
            billed_qty += invoice_line.product_uom_id._compute_quantity(
                invoice_line.quantity,
                self.product_uom,
            )
        return billed_qty

    def _get_combined_lpo_billable_qty(self):
        self.ensure_one()
        if self.display_type or not self.product_id:
            return 0.0
        if 'is_promotion_foc' in self._fields and self.is_promotion_foc:
            _logger.debug(
                '[CLPO_ELIGIBILITY] skip_foc purchase_line_id=%s po=%s product_id=%s',
                self.id,
                self.order_id.name,
                self.product_id.id,
            )
            return 0.0
        gross_billed_qty = self._get_combined_lpo_gross_billed_qty()
        received_to_bill = max((self.qty_received or 0.0) - gross_billed_qty, 0.0)
        rounding = self.product_uom.rounding if self.product_uom else 0.01
        billable_qty = 0.0 if float_is_zero(received_to_bill, precision_rounding=rounding) else received_to_bill
        _logger.debug(
            '[CLPO_ELIGIBILITY] gross_billable purchase_line_id=%s po=%s product_id=%s '
            'received=%s net_invoiced=%s gross_billed=%s billable=%s',
            self.id,
            self.order_id.name,
            self.product_id.id,
            self.qty_received,
            self.qty_invoiced,
            gross_billed_qty,
            billable_qty,
        )
        return billable_qty
