# -*- coding: utf-8 -*-
"""Manufacturing settings for tinting formula registration policy."""

import logging

from odoo import fields, models


_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    auto_approve_first_tint_formula = fields.Boolean(
        string='Automatically Approve First Tinting Formula',
        config_parameter='paint_tinting.auto_approve_first_tint_formula',
        help=(
            'Automatically approve and make default only the first recipe captured '
            'for a previously unregistered tinting formula family. Later versions '
            'continue to require Tinting Formula Manager approval.'
        ),
    )
    block_cost_comparison_use_this = fields.Boolean(
        string='Block Cost Comparison Use This',
        default=True,
        config_parameter='paint_tinting.block_cost_comparison_use_this',
        help=(
            'Prevent users from switching the base product by clicking "Use This" '
            'inside the cost comparison wizard.'
        ),
    )
    tinted_product_category_policy = fields.Selection(
        [
            ('child_base', 'Child Category of Base Product Category'),
            ('same_base', 'Same as Base Product Category'),
            ('global_tinted', 'Global Tinted Paint Category'),
        ],
        string='Tinted Product Category',
        default='child_base',
        config_parameter='paint_tinting.tinted_product_category_policy',
        help=(
            'Choose where dynamically created tinted products are categorized. '
            'The default creates or reuses a Tinted Paint child category below '
            'the selected base product category.'
        ),
    )
    tinted_product_child_category_name = fields.Char(
        string='Tinted Product Child Category Name',
        default='Tinted Paint',
        config_parameter='paint_tinting.tinted_product_child_category_name',
        help=(
            'Name of the child category created under each base product category '
            'when the child-category policy is enabled.'
        ),
    )
    tinting_vat_percent = fields.Float(
        string='Tinting VAT %',
        default=16.0,
        config_parameter='paint_tinting.default_vat_percent',
        help='VAT percentage used by tinting operational cost registers.',
    )

    def get_values(self):
        result = super().get_values()
        block_enabled = self.env[
            'cost.comparison.use.this.policy'
        ].is_block_enabled()
        result.update(block_cost_comparison_use_this=block_enabled)
        _logger.debug(
            'COST_COMPARISON_USE_THIS_BLOCK_SETTING_LOADED value=%s user_id=%s',
            block_enabled, self.env.user.id,
        )
        return result

    def set_values(self):
        parameter = self.env['ir.config_parameter'].sudo()
        tracked_settings = [
            (
                'paint_tinting.auto_approve_first_tint_formula',
                'FORMULA_AUTO_APPROVAL',
                'False',
            ),
            (
                'paint_tinting.block_cost_comparison_use_this',
                'COST_COMPARISON_USE_THIS_BLOCK',
                'True',
            ),
            (
                'paint_tinting.tinted_product_category_policy',
                'TINTED_PRODUCT_CATEGORY_POLICY',
                'child_base',
            ),
            (
                'paint_tinting.tinted_product_child_category_name',
                'TINTED_PRODUCT_CHILD_CATEGORY_NAME',
                'Tinted Paint',
            ),
            (
                'paint_tinting.default_vat_percent',
                'TINTING_DEFAULT_VAT_PERCENT',
                '16.0',
            ),
        ]
        previous_values = {
            key: parameter.get_param(key, default=default)
            for key, _log_name, default in tracked_settings
        }
        result = super().set_values()
        for key, log_name, default in tracked_settings:
            previous = previous_values[key]
            current = parameter.get_param(key, default=default)
            if previous != current:
                _logger.warning(
                    '%s_SETTING_CHANGED key=%s previous=%s current=%s user_id=%s',
                    log_name, key, previous, current, self.env.user.id,
                )
            else:
                _logger.info(
                    '%s_SETTING_SAVED key=%s value=%s user_id=%s',
                    log_name, key, current, self.env.user.id,
                )
        return result
