from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VendorDepartmentContact(models.Model):
    _name = 'vendor.department.contact'
    _description = 'Vendor Department Contact'
    _order = 'sequence, title, id'
    _rec_name = 'contact_id'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    department_id = fields.Many2one(
        'vendor.department',
        required=True,
        ondelete='cascade',
        index=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        related='department_id.vendor_id',
        store=True,
        readonly=True,
        index=True,
    )
    contact_id = fields.Many2one(
        'res.partner',
        string='Contact',
        required=True,
        ondelete='restrict',
        index=True,
        help='Contact from the Contacts app assigned to this vendor department.',
    )
    title = fields.Char(
        string='Department Title',
        required=True,
        help='Role/title in this vendor department, for example Head of Sales.',
    )
    email = fields.Char(related='contact_id.email', readonly=True)
    phone = fields.Char(related='contact_id.phone', readonly=True)
    mobile = fields.Char(related='contact_id.mobile', readonly=True)
    is_primary = fields.Boolean(
        string='Primary',
        help='Mark the main contact for this department.',
    )
    note = fields.Text()

    _sql_constraints = [
        (
            'department_contact_unique',
            'unique(department_id, contact_id)',
            'A contact can only be assigned once per department.',
        ),
    ]

    @api.onchange('contact_id')
    def _onchange_contact_id(self):
        for line in self:
            if line.contact_id and not line.title:
                line.title = line.contact_id.function or ''

    @api.constrains('department_id', 'is_primary')
    def _check_single_primary_contact(self):
        for line in self.filtered('is_primary'):
            domain = [
                ('department_id', '=', line.department_id.id),
                ('is_primary', '=', True),
                ('id', '!=', line.id),
            ]
            if self.search_count(domain):
                raise ValidationError('Only one primary contact is allowed per department.')
