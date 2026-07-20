from odoo import models, fields, api, _
from odoo.tools.float_utils import float_is_zero
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _get_invoice_wizard_received_qty(self, po_line):
        received_to_bill = max((po_line.qty_received or 0.0) - (po_line.qty_invoiced or 0.0), 0.0)
        rounding = po_line.product_uom.rounding if po_line.product_uom else 0.01
        return 0.0 if float_is_zero(received_to_bill, precision_rounding=rounding) else received_to_bill

    def action_create_invoice_wizard(self):
        """Open wizard to enter vendor bill prices"""
        self.ensure_one()
        profile = self.partner_id.get_vendor_invoice_profile()
        _logger.info(
            '[VPC_OPEN] wizard_open_start po_id=%s po=%s vendor_id=%s profile=%s',
            self.id,
            self.name,
            self.partner_id.id,
            profile,
        )
        
        # Create wizard
        wizard = self.env['vendor.price.wizard'].create({
            'purchase_id': self.id,
        })
        
        _logger.info('[VPC_OPEN] wizard_created wizard_id=%s po_id=%s', wizard.id, self.id)
        
        # Create wizard lines from PO lines
        line_count = 0
        for po_line in self.order_line.filtered(lambda l: not l.display_type):
            received_qty = self._get_invoice_wizard_received_qty(po_line)
            if not received_qty:
                _logger.info(
                    "Skipping %s on PO %s: received=%s, already invoiced=%s",
                    po_line.product_id.display_name,
                    self.name,
                    po_line.qty_received,
                    po_line.qty_invoiced,
                )
                continue
            wizard_line = self.env['vendor.price.wizard.line'].create({
                'wizard_id': wizard.id,
                'purchase_line_id': po_line.id,
                'product_id': po_line.product_id.id,
                'product_qty': received_qty,
                'price_unit': po_line.price_unit,
                'vendor_price': None,  # Explicitly set to None to avoid coercion
                'use_custom_pricing': True,  # Automatically set to True
                'applied_discount': po_line.applied_discount or 0.0,  # Populate from PO line
                'applied_freight': po_line.applied_freight or 0.0,  # Populate from PO line
                'currency_id': self.currency_id.id,
            })
            line_count += 1
            _logger.info(
                '[VPC_OPEN] line_created wizard_id=%s wizard_line_id=%s purchase_line_id=%s '
                'product_id=%s received_to_bill=%s po_price=%s discount=%s freight=%s tax_ids=%s',
                wizard.id,
                wizard_line.id,
                po_line.id,
                po_line.product_id.id,
                received_qty,
                po_line.price_unit,
                po_line.applied_discount,
                po_line.applied_freight,
                po_line.taxes_id.ids,
            )
        
        _logger.info(
            '[VPC_OPEN] wizard_ready wizard_id=%s po_id=%s profile=%s line_count=%s',
            wizard.id,
            self.id,
            profile,
            line_count,
        )

        if not line_count:
            _logger.warning("No validated received quantities to invoice for PO %s", self.name)
            return {'type': 'ir.actions.do_nothing'}
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Enter Vendor Bill Prices',
            'res_model': 'vendor.price.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
