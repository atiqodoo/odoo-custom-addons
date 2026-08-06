# -*- coding: utf-8 -*-
"""Category placement policy for dynamically created tinted products."""

import logging

from odoo import api, models


_logger = logging.getLogger(__name__)


class ProductCategory(models.Model):
    _inherit = 'product.category'

    _PT_CATEGORY_COPY_FIELDS = (
        'property_cost_method',
        'property_valuation',
        'property_stock_valuation_account_id',
        'property_stock_account_input_categ_id',
        'property_stock_account_output_categ_id',
        'property_stock_journal',
        'property_account_income_categ_id',
        'property_account_expense_categ_id',
        'property_account_creditor_price_difference_categ',
    )

    @api.model
    def _paint_tinting_get_tinted_product_category(self, base_category):
        """Return the category to use for a tinted product.

        The default policy keeps tinted products grouped below the same product
        family as their base paint, e.g. ``Vinyl Silk / Tinted Paint``.
        """
        if not base_category:
            _logger.warning(
                'PT_CATEGORY_POLICY_NO_BASE_CATEGORY fallback=global_tinted_paint'
            )
            return self._paint_tinting_get_global_tinted_category()

        parameter = self.env['ir.config_parameter'].sudo()
        policy = parameter.get_param(
            'paint_tinting.tinted_product_category_policy',
            default='child_base',
        )
        child_name = (
            parameter.get_param(
                'paint_tinting.tinted_product_child_category_name',
                default='Tinted Paint',
            )
            or 'Tinted Paint'
        ).strip()

        _logger.info(
            'PT_CATEGORY_POLICY_RESOLVE policy=%s base_category_id=%s '
            'base_category=%s child_name=%s',
            policy, base_category.id, base_category.complete_name, child_name,
        )

        if policy == 'same_base':
            _logger.info(
                'PT_CATEGORY_POLICY_SELECTED policy=same_base category_id=%s '
                'category=%s',
                base_category.id, base_category.complete_name,
            )
            return base_category

        if policy == 'global_tinted':
            return self._paint_tinting_get_global_tinted_category()

        if (
            base_category.parent_id
            and base_category.name.casefold() == child_name.casefold()
        ):
            _logger.info(
                'PT_CATEGORY_POLICY_CHILD_SOURCE_ALREADY_TINTED '
                'source_category_id=%s source_category=%s effective_parent_id=%s '
                'effective_parent=%s',
                base_category.id,
                base_category.complete_name,
                base_category.parent_id.id,
                base_category.parent_id.complete_name,
            )
            base_category = base_category.parent_id

        return self._paint_tinting_get_or_create_child_tinted_category(
            base_category, child_name
        )

    @api.model
    def _paint_tinting_get_global_tinted_category(self):
        category = self.search([('name', '=', 'Tinted Paint')], limit=1)
        if category:
            _logger.info(
                'PT_CATEGORY_POLICY_SELECTED policy=global_tinted '
                'category_id=%s category=%s',
                category.id, category.complete_name,
            )
            return category

        category = self.sudo().create({'name': 'Tinted Paint'})
        _logger.warning(
            'PT_CATEGORY_POLICY_CREATED_GLOBAL category_id=%s category=%s',
            category.id, category.complete_name,
        )
        return category

    @api.model
    def _paint_tinting_get_or_create_child_tinted_category(
        self, base_category, child_name
    ):
        category = self.search([
            ('name', '=', child_name),
            ('parent_id', '=', base_category.id),
        ], limit=1)
        if category:
            _logger.info(
                'PT_CATEGORY_POLICY_SELECTED policy=child_base '
                'category_id=%s category=%s parent_id=%s',
                category.id, category.complete_name, base_category.id,
            )
            return category

        values = self._paint_tinting_prepare_child_category_values(
            base_category, child_name
        )
        category = self.sudo().create(values)
        copied_fields = sorted(set(values) - {'name', 'parent_id'})
        _logger.warning(
            'PT_CATEGORY_POLICY_CREATED_CHILD category_id=%s category=%s '
            'parent_id=%s copied_fields=%s',
            category.id, category.complete_name, base_category.id, copied_fields,
        )
        return category

    @api.model
    def _paint_tinting_prepare_child_category_values(
        self, base_category, child_name
    ):
        values = {
            'name': child_name,
            'parent_id': base_category.id,
        }
        for field_name in self._PT_CATEGORY_COPY_FIELDS:
            if field_name not in self._fields:
                _logger.debug(
                    'PT_CATEGORY_POLICY_COPY_SKIP missing_field=%s',
                    field_name,
                )
                continue

            value = base_category[field_name]
            if not value:
                _logger.debug(
                    'PT_CATEGORY_POLICY_COPY_SKIP empty_field=%s parent_id=%s',
                    field_name, base_category.id,
                )
                continue

            field = self._fields[field_name]
            values[field_name] = value.id if field.type == 'many2one' else value
            _logger.debug(
                'PT_CATEGORY_POLICY_COPY_FIELD field=%s value=%s parent_id=%s',
                field_name, values[field_name], base_category.id,
            )

        return values
