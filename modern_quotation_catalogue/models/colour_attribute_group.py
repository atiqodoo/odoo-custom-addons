# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class ModernQuotationColourAttributeGroup(models.Model):
    _name = 'modern.quotation.colour.attribute.group'
    _description = 'Modern Quotation Colour and Attribute Group'
    _order = 'sequence, name, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    colour_code_ids = fields.Many2many(
        'colour.code',
        'modern_quotation_colour_group_code_rel',
        'group_id',
        'colour_code_id',
        string='Colour Codes / Names',
        help='Colour code records whose code or name should search together with the mapped attribute values.',
    )
    attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        'modern_quotation_colour_group_attribute_rel',
        'group_id',
        'attribute_value_id',
        string='Attribute Values',
        help='Product attribute values that should search together with the mapped colour codes.',
    )
    colour_code_count = fields.Integer(compute='_compute_counts')
    attribute_value_count = fields.Integer(compute='_compute_counts')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'The colour and attribute group name must be unique.'),
    ]

    @api.depends('colour_code_ids', 'attribute_value_ids')
    def _compute_counts(self):
        for group in self:
            group.colour_code_count = len(group.colour_code_ids)
            group.attribute_value_count = len(group.attribute_value_ids)

    @api.constrains('colour_code_ids', 'attribute_value_ids', 'active')
    def _check_mapping(self):
        for group in self:
            if not group.colour_code_ids or not group.attribute_value_ids:
                raise ValidationError(_('Add at least one colour code/name and one attribute value.'))
            if not group.active:
                continue
            duplicate = self.search([
                ('id', '!=', group.id),
                ('active', '=', True),
                '|',
                ('colour_code_ids', 'in', group.colour_code_ids.ids),
                ('attribute_value_ids', 'in', group.attribute_value_ids.ids),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'One or more colour codes or attribute values are already mapped in "%s".'
                ) % duplicate.display_name)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._log_change('CREATED', vals_list)
        return records

    def write(self, vals):
        result = super().write(vals)
        self._log_change('UPDATED', vals)
        return result

    def unlink(self):
        self._log_change('DELETED', {'ids': self.ids})
        return super().unlink()

    def _log_change(self, operation, values):
        _logger.info(
            '%s | COLOUR ATTRIBUTE GROUP %s | ids=%s | values=%s',
            'MODERN QUOTATION CATALOGUE',
            operation,
            self.ids,
            values,
        )
