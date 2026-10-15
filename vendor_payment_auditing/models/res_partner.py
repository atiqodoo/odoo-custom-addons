from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    vendor_payment_audit_enabled = fields.Boolean(
        string='Vendor Payment Audit Enabled',
        default=True,
        company_dependent=True,
    )
    vendor_payment_audit_policy_id = fields.Many2one(
        'vendor.payment.audit.policy',
        string='Vendor Payment Audit Policy',
        company_dependent=True,
        domain="[('active', '=', True)]",
    )
