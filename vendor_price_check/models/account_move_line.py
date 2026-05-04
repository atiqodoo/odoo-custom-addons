# vendor_price_check/models/account_move_line.py
from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    use_custom_pricing = fields.Boolean(string='Use Custom Pricing')
    net_price = fields.Float(string='Net Price', store=True)
    applied_discount = fields.Float(string='Discount %')
    applied_freight = fields.Float(string='Freight %')

    @api.model
    def _prepare_invoice_line(self, purchase_line):
        res = super(AccountMoveLine, self)._prepare_invoice_line(purchase_line)
        _logger.info(f"=== Creating Bill Line with Custom Pricing ===")
        _logger.info(f"Product: {purchase_line.product_id.display_name}")
        _logger.info(f"PO Unit Price: {purchase_line.price_unit}")

        wizard_line = self.env['vendor.price.wizard.line'].search([
            ('purchase_line_id', '=', purchase_line.id),
            ('wizard_id.purchase_id', '=', purchase_line.order_id.id)
        ], limit=1)
        if wizard_line:
            price_unit = wizard_line.calculated_subtotal
            _logger.info(f"Using wizard calculated_subtotal: {price_unit}")
        else:
            price_unit = purchase_line.net_price or purchase_line.price_unit
            _logger.info(f"Using PO net_price: {price_unit}")

        _logger.info(f"Net Price (tax-exclusive): {price_unit}")
        _logger.info(f"Bill Line Price Unit set to: {price_unit}")

        res.update({
            'price_unit': price_unit,
            'tax_ids': [(6, 0, purchase_line.taxes_id.ids)],
            'use_custom_pricing': wizard_line.use_custom_pricing if wizard_line else purchase_line.use_custom_pricing,
            'net_price': price_unit,
            'applied_discount': wizard_line.applied_discount if wizard_line else purchase_line.applied_discount,
            'applied_freight': wizard_line.applied_freight if wizard_line else purchase_line.applied_freight,
        })

        _logger.info(
            f"Stored custom pricing values - net_price: {res['net_price']}, "
            f"discount: {res['applied_discount']}, freight: {res['applied_freight']}"
        )
        return res

    @api.model_create_multi
    def create(self, vals_list):
        lines = super(AccountMoveLine, self).create(vals_list)
        for line in lines:
            _logger.info(f"=== Verification After Create ===")
            _logger.info(f"Line ID: {line.id}")
            _logger.info(f"use_custom_pricing: {line.use_custom_pricing}")
            _logger.info(f"net_price: {line.net_price}")
            _logger.info(f"applied_discount: {line.applied_discount}")
            _logger.info(f"applied_freight: {line.applied_freight}")
        return lines
    # vendor_price_check/models/account_move_line.py
# (append to the bottom — after your existing fields)

    # ──────────────────────────────────────────────────────────────
    # NEW: Line-level subtotal including VAT
    # ──────────────────────────────────────────────────────────────
    line_subtotal_incl_vat = fields.Monetary(
        string="Net price(incl. VAT)",
        compute='_compute_line_subtotal_incl_vat',
        store=True,
        readonly=True,
        currency_field='currency_id',
    )

    @api.depends('price_subtotal', 'price_total')
    def _compute_line_subtotal_incl_vat(self):
        for line in self:
            # price_total = price_subtotal + tax
            line.line_subtotal_incl_vat = line.price_total