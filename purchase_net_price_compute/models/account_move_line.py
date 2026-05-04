# purchase_net_price_compute/models/account_move_line.py
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

        # Defer to vendor_price_check for price_unit, only set custom pricing fields
        res.update({
            'use_custom_pricing': purchase_line.use_custom_pricing,
            'net_price': purchase_line.net_price or purchase_line.price_unit,
            'applied_discount': purchase_line.applied_discount,
            'applied_freight': purchase_line.applied_freight,
            'tax_ids': [(6, 0, purchase_line.taxes_id.ids)],
        })

        _logger.info(f"Stored values - net_price: {res['net_price']}, "
                     f"discount: {res['applied_discount']}, freight: {res['applied_freight']}")
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

    @api.model
    def write(self, vals):
        res = super(AccountMoveLine, self).write(vals)
        for line in self:
            _logger.info(f"=== Verification After Write ===")
            _logger.info(f"Line ID: {line.id}")
            _logger.info(f"use_custom_pricing: {line.use_custom_pricing}")
            _logger.info(f"net_price: {line.net_price}")
            _logger.info(f"applied_discount: {line.applied_discount}")
            _logger.info(f"applied_freight: {line.applied_freight}")
        return res