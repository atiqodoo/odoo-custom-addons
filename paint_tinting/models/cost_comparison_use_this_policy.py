# -*- coding: utf-8 -*-
"""Policy service for controlling cost-comparison product switching."""

import logging

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import str2bool


_logger = logging.getLogger(__name__)


class CostComparisonUseThisPolicy(models.AbstractModel):
    _name = 'cost.comparison.use.this.policy'
    _description = 'Cost Comparison Use This Button Policy'

    _SETTING_KEY = 'paint_tinting.block_cost_comparison_use_this'

    @api.model
    def is_block_enabled(self):
        raw_value = self.env['ir.config_parameter'].sudo().get_param(
            self._SETTING_KEY, default='True',
        )
        enabled = str2bool(raw_value, default=True)
        _logger.debug(
            'COST_COMPARISON_USE_THIS_SETTING_READ key=%s raw_value=%s enabled=%s user_id=%s',
            self._SETTING_KEY, raw_value, enabled, self.env.user.id,
        )
        return enabled

    @api.model
    def assert_can_use_this(self, line):
        line.ensure_one()
        blocked = self.is_block_enabled()
        _logger.info(
            'COST_COMPARISON_USE_THIS_POLICY_CHECK line_id=%s wizard_id=%s '
            'product_id=%s blocked=%s user_id=%s',
            line.id, line.wizard_id.id, line.product_id.id, blocked, self.env.user.id,
        )
        if not blocked:
            return True

        _logger.warning(
            'COST_COMPARISON_USE_THIS_BLOCKED line_id=%s wizard_id=%s '
            'parent_wizard_id=%s product_id=%s user_id=%s',
            line.id, line.wizard_id.id, line.wizard_id.parent_wizard_id.id,
            line.product_id.id, self.env.user.id,
        )
        raise UserError(_(
            'The "Use This" action is currently blocked by the Manufacturing '
            'setting "Block Cost Comparison Use This". Disable that setting to '
            'allow product switching from the cost comparison wizard.'
        ))
