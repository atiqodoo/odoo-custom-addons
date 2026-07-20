# -*- coding: utf-8 -*-
from odoo import fields, models

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
        string='Final Unit Price (VAT Incl.)', currency_field='currency_id', readonly=True, copy=False,
    )
