# -*- coding: utf-8 -*-
from odoo import api, fields, models

from odoo.addons.purchase_net_price_compute.models.vendor_invoice_profile import (
    VENDOR_INVOICE_PROFILE_SELECTION,
    VENDOR_INVOICE_PROFILE_STANDARD,
)


class AccountMoveCrownInvoiceAudit(models.Model):
    _inherit = 'account.move'

    vendor_invoice_profile = fields.Selection(
        selection=VENDOR_INVOICE_PROFILE_SELECTION,
        string='Vendor Invoice Calculation Profile',
        default=VENDOR_INVOICE_PROFILE_STANDARD,
        readonly=True,
        copy=False,
        index=True,
    )
    vendor_calculated_total_vat_incl = fields.Monetary(
        string='Calculated Total (VAT Incl.)', currency_field='currency_id', readonly=True, copy=False,
    )
    vendor_invoice_final_total = fields.Monetary(
        string='Vendor Invoice Final Total', currency_field='currency_id', readonly=True, copy=False,
    )
    vendor_invoice_variance_amount = fields.Monetary(
        string='Invoice Variance', currency_field='currency_id', readonly=True, copy=False,
    )
    vendor_invoice_variance_percentage = fields.Float(
        string='Invoice Variance %', readonly=True, copy=False,
    )


class AccountMoveLineCrownInvoiceAudit(models.Model):
    _inherit = 'account.move.line'

    vendor_invoice_unit_price = fields.Monetary(
        string='Invoice Unit Price', currency_field='currency_id', readonly=True, copy=False,
    )
    vendor_invoice_line_total = fields.Monetary(
        string='Vendor Line Total', currency_field='currency_id', readonly=True, copy=False,
    )
    vendor_structured_discount_amount = fields.Monetary(
        string='Structured Discount', currency_field='currency_id', readonly=True, copy=False,
    )
    vendor_structured_discount_percentage = fields.Float(
        string='Structured Discount %', readonly=True, copy=False,
    )
    vendor_discount_per_quantity = fields.Monetary(
        string='Discount / Qty', currency_field='currency_id', readonly=True, copy=False,
    )
    vendor_invoice_variance_allocated = fields.Monetary(
        string='Allocated Invoice Variance', currency_field='currency_id', readonly=True, copy=False,
    )
    vendor_final_unit_price_vat_incl = fields.Monetary(
        string='Final Unit Price (VAT Incl.)',
        compute='_compute_vendor_final_unit_price_vat_incl',
        store=True,
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )

    @api.depends(
        'price_unit',
        'tax_ids',
        'currency_id',
        'product_id',
        'partner_id',
        'move_id.partner_id',
        'move_id.vendor_invoice_profile',
        'move_id.vendor_invoice_variance_amount',
    )
    def _compute_vendor_final_unit_price_vat_incl(self):
        for line in self:
            partner = line.partner_id or line.move_id.partner_id
            if line.tax_ids:
                tax_result = line.tax_ids.compute_all(
                    line.price_unit or 0.0,
                    currency=line.currency_id,
                    quantity=1.0,
                    product=line.product_id,
                    partner=partner,
                )
                line.vendor_final_unit_price_vat_incl = tax_result['total_included']
            else:
                line.vendor_final_unit_price_vat_incl = line.price_unit or 0.0
