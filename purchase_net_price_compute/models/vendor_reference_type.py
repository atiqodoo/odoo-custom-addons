# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class VendorReferenceType(models.Model):
    _name = 'purchase.vendor.reference.type'
    _description = 'Vendor Reference Type'
    _order = 'sequence, name'

    name = fields.Char(required=True, index=True)
    name_normalized = fields.Char(
        compute='_compute_name_normalized',
        store=True,
        index=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'name_normalized_uniq',
            'unique(name_normalized)',
            'Vendor reference type already exists.',
        ),
    ]

    @api.depends('name')
    def _compute_name_normalized(self):
        for record in self:
            record.name_normalized = (record.name or '').strip().casefold()

    @api.constrains('name')
    def _check_name_not_blank(self):
        for record in self:
            if not (record.name or '').strip():
                raise ValidationError(_('Vendor reference type name cannot be blank.'))
