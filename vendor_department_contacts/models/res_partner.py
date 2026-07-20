from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    vendor_department_ids = fields.One2many(
        'vendor.department',
        'vendor_id',
        string='Vendor Departments',
        copy=False,
    )
    vendor_department_count = fields.Integer(
        string='Vendor Department Count',
        compute='_compute_vendor_department_count',
    )

    @api.depends('vendor_department_ids')
    def _compute_vendor_department_count(self):
        counts = {
            data['vendor_id'][0]: data['vendor_id_count']
            for data in self.env['vendor.department'].read_group(
                [('vendor_id', 'in', self.ids)],
                ['vendor_id'],
                ['vendor_id'],
            )
        }
        for partner in self:
            partner.vendor_department_count = counts.get(partner.id, 0)

    def action_open_vendor_departments(self):
        self.ensure_one()
        action = self.env.ref(
            'vendor_department_contacts.action_vendor_department'
        ).read()[0]
        action['domain'] = [('vendor_id', '=', self.id)]
        action['context'] = {
            'default_vendor_id': self.id,
            'search_default_vendor_id': self.id,
        }
        return action
