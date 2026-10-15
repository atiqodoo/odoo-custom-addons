from odoo import fields, models


class VendorPaymentAuditVarianceType(models.Model):
    _name = 'vendor.payment.audit.variance.type'
    _description = 'Vendor Payment Audit Variance Type'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    default_severity = fields.Selection(
        [
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('critical', 'Critical'),
        ],
        default='medium',
        required=True,
    )

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Variance type code must be unique.'),
    ]
