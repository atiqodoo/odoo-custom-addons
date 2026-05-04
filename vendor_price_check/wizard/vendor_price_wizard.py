from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class VendorPriceWizard(models.TransientModel):
    _name = 'vendor.price.wizard'
    _description = 'Vendor Price Wizard'

    purchase_id = fields.Many2one('purchase.order', string='Purchase Order', required=True)
    bill_id = fields.Many2one('account.move', string='Vendor Bill')
    line_ids = fields.One2many('vendor.price.wizard.line', 'wizard_id', string='Lines')

    def action_create_bill(self):
        self.ensure_one()
        _logger.info(f"Creating/Updating bill for PO {self.purchase_id.name}")

        # Validate all lines before proceeding
        for line in self.line_ids:
            _logger.debug(f"Validating line {line.id}: vendor_price={line.vendor_price}, calculated_subtotal={line.calculated_subtotal}")
            if line.vendor_price is None or line.vendor_price == 0.0:
                raise ValidationError(_("Vendor Price is required and must be a non-zero value for all lines."))

        bill_vals = {
            'move_type': 'in_invoice',
            'partner_id': self.purchase_id.partner_id.id,
            'purchase_id': self.purchase_id.id,
            'invoice_origin': self.purchase_id.name,
            'currency_id': self.purchase_id.currency_id.id,
            'invoice_line_ids': [],
        }

        wizard_vendor_prices = {
            line.product_id.id: line.calculated_subtotal
            for line in self.line_ids.filtered(lambda l: l.product_id and l.purchase_line_id)
        }

        for line in self.line_ids.filtered(lambda l: l.product_id and l.purchase_line_id):
            _logger.info(
                f"📊 {line.product_id.display_name}: "
                f"Vendor={line.vendor_price:.2f} → Calculated={line.calculated_subtotal:.2f} "
                f"(Custom Pricing: {line.use_custom_pricing})"
            )
            price_unit = line.calculated_subtotal  # Use calculated_subtotal directly as tax-exclusive
            bill_line_vals = {
                'product_id': line.product_id.id,
                'quantity': line.product_qty,
                'price_unit': price_unit,
                'tax_ids': [(6, 0, line.purchase_line_id.taxes_id.ids)],
                'purchase_line_id': line.purchase_line_id.id,
                'use_custom_pricing': line.use_custom_pricing,
                'net_price': line.calculated_subtotal,
                'applied_discount': line.applied_discount,
                'applied_freight': line.applied_freight,
            }
            bill_vals['invoice_line_ids'].append((0, 0, bill_line_vals))

        if self.bill_id:
            _logger.info(f"Updating existing bill {self.bill_id.name}")
            self.bill_id.with_context(wizard_vendor_prices=wizard_vendor_prices).write({
                'invoice_line_ids': [(5, 0, 0)] + bill_vals['invoice_line_ids']
            })
            bill = self.bill_id
        else:
            _logger.info("Creating new bill")
            bill = self.env['account.move'].with_context(wizard_vendor_prices=wizard_vendor_prices).create(bill_vals)

        discrepancies = bill._check_vendor_bill_prices()
        if discrepancies:
            _logger.warning(f"⚠️ {len(discrepancies)} discrepancies found")
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': bill.id,
                'target': 'current',
            }

        _logger.info(f"✅ Bill created/updated: ID={bill.id}")
        for line in bill.invoice_line_ids:
            _logger.info(
                f"✅ Line created: {line.product_id.display_name} @ {line.price_unit:.2f} "
                f"(Custom Pricing: {line.use_custom_pricing})"
            )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': bill.id,
            'target': 'current',
        }