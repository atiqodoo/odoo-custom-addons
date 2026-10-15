# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorBillInvoiceVarianceAudit(models.Model):
    _name = 'vendor.bill.invoice.variance.audit'
    _description = 'Vendor Bill Invoice Variance Audit'
    _order = 'create_date desc, id desc'

    name = fields.Char(default='Invoice Variance Audit', readonly=True)
    bill_id = fields.Many2one('account.move', string='Vendor Bill', index=True, readonly=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor', index=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    purchase_id = fields.Many2one('purchase.order', string='Purchase Order', readonly=True)
    purchase_ids = fields.Many2many('purchase.order', string='Source LPOs', readonly=True)
    wizard_model = fields.Char(string='Wizard Model', readonly=True)
    wizard_id = fields.Integer(string='Wizard ID', readonly=True)
    vendor_invoice_profile = fields.Char(string='Vendor Invoice Profile', readonly=True)
    calculated_total_vat_incl = fields.Monetary(
        string='Calculated Total (VAT Incl.)',
        currency_field='currency_id',
        readonly=True,
    )
    vendor_invoice_final_total = fields.Monetary(
        string='Vendor Invoice Final Total',
        currency_field='currency_id',
        readonly=True,
    )
    variance_amount = fields.Monetary(
        string='Invoice Variance',
        currency_field='currency_id',
        readonly=True,
    )
    absolute_variance_amount = fields.Monetary(
        string='Absolute Variance',
        currency_field='currency_id',
        readonly=True,
    )
    allowed_variance_amount = fields.Monetary(
        string='Allowed Variance',
        currency_field='currency_id',
        readonly=True,
    )
    block_above_allowed = fields.Boolean(string='Blocked Above Allowed', readonly=True)
    exceeded_allowed_amount = fields.Boolean(string='Exceeded Allowed Amount', readonly=True)
    dismiss_clicks_required = fields.Integer(string='Dismiss Clicks Required', readonly=True)
    dismiss_clicks_done = fields.Integer(string='Dismiss Clicks Done', readonly=True)
    created_by_id = fields.Many2one('res.users', string='Created By', readonly=True)
    wizard_snapshot_json = fields.Json(string='Wizard Snapshot', readonly=True)
    line_snapshot_json = fields.Json(string='Line Snapshot', readonly=True)
