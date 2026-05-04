from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def action_create_invoice_wizard(self):
        """Open wizard to enter vendor bill prices"""
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info(f"Opening vendor price wizard for PO: {self.name}")
        _logger.info("=" * 80)
        
        # Create wizard
        wizard = self.env['vendor.price.wizard'].create({
            'purchase_id': self.id,
        })
        
        _logger.info(f"Wizard created: ID {wizard.id}")
        
        # Create wizard lines from PO lines
        line_count = 0
        for po_line in self.order_line.filtered(lambda l: not l.display_type):
            wizard_line = self.env['vendor.price.wizard.line'].create({
                'wizard_id': wizard.id,
                'purchase_line_id': po_line.id,
                'product_id': po_line.product_id.id,
                'product_qty': po_line.product_qty,
                'price_unit': po_line.price_unit,
                'vendor_price': None,  # Explicitly set to None to avoid coercion
                'use_custom_pricing': True,  # Automatically set to True
                'applied_discount': po_line.applied_discount or 0.0,  # Populate from PO line
                'applied_freight': po_line.applied_freight or 0.0,  # Populate from PO line
                'currency_id': self.currency_id.id,
            })
            line_count += 1
            _logger.info(f"  Line {line_count}: {po_line.product_id.display_name} - Qty: {po_line.product_qty} - Price: {po_line.price_unit} - Discount: {po_line.applied_discount}% - Freight: {po_line.applied_freight}% - Vendor Price: {wizard_line.vendor_price}")
        
        _logger.info(f"Created {line_count} wizard lines")
        _logger.info("=" * 80)
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Enter Vendor Bill Prices',
            'res_model': 'vendor.price.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }