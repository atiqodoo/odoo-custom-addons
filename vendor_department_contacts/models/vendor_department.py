from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VendorDepartment(models.Model):
    _name = 'vendor.department'
    _description = 'Vendor Department'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name, id'

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, tracking=True)
    code = fields.Char(
        help='Optional short code used by integrations or reports.',
        tracking=True,
    )
    active = fields.Boolean(default=True)
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        required=True,
        domain=[('supplier_rank', '>', 0)],
        ondelete='cascade',
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='vendor_id.company_id',
        store=True,
        readonly=True,
    )
    contact_line_ids = fields.One2many(
        'vendor.department.contact',
        'department_id',
        string='Contacts',
        copy=True,
    )
    contact_count = fields.Integer(
        compute='_compute_contact_count',
        string='Contact Count',
    )
    note = fields.Text()

    _sql_constraints = [
        (
            'vendor_department_name_unique',
            'unique(vendor_id, name)',
            'Department names must be unique per vendor.',
        ),
        (
            'vendor_department_code_unique',
            'unique(vendor_id, code)',
            'Department codes must be unique per vendor.',
        ),
    ]

    @api.depends('contact_line_ids')
    def _compute_contact_count(self):
        counts = {
            data['department_id'][0]: data['department_id_count']
            for data in self.env['vendor.department.contact'].read_group(
                [('department_id', 'in', self.ids)],
                ['department_id'],
                ['department_id'],
            )
        }
        for department in self:
            department.contact_count = counts.get(department.id, 0)

    @api.constrains('vendor_id')
    def _check_vendor_partner(self):
        for department in self:
            if department.vendor_id and department.vendor_id.supplier_rank <= 0:
                raise ValidationError('Vendor departments can only be created on vendor contacts.')
