# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class ModernQuotationCategoryGroup(models.Model):
    _name = 'modern.quotation.category.group'
    _description = 'Modern Quotation Category Group'
    _order = 'sequence, name, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    child_category_ids = fields.Many2many(
        'product.category',
        'modern_quotation_category_group_rel',
        'group_id',
        'category_id',
        string='Mapped Child Categories',
        help='Existing product categories grouped under this quotation filter parent.',
    )
    child_category_count = fields.Integer(compute='_compute_child_category_count')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'The category group name must be unique.'),
    ]

    @api.depends('child_category_ids')
    def _compute_child_category_count(self):
        for group in self:
            group.child_category_count = len(group.child_category_ids)

    @api.constrains('child_category_ids')
    def _check_child_category_ids(self):
        for group in self:
            if not group.child_category_ids:
                raise ValidationError(_('Add at least one mapped child category.'))
            if group.active:
                duplicate = self.search([
                    ('id', '!=', group.id),
                    ('active', '=', True),
                    ('child_category_ids', 'in', group.child_category_ids.ids),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        'One or more child categories are already mapped in "%s".'
                    ) % duplicate.display_name)

    def write(self, vals):
        result = super().write(vals)
        self._log_change('UPDATED', vals)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._log_change('CREATED', vals_list)
        return records

    def unlink(self):
        self._log_change('DELETED', {'ids': self.ids})
        return super().unlink()

    def _log_change(self, operation, values):
        _logger.info(
            '%s | CATEGORY GROUP %s | ids=%s | values=%s',
            'MODERN QUOTATION CATALOGUE',
            operation,
            self.ids,
            values,
        )
