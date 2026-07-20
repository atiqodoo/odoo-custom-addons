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

    def set_values(self):
        parameter = self.env['ir.config_parameter'].sudo()
        key = 'paint_tinting.auto_approve_first_tint_formula'
        previous = parameter.get_param(key, default='False')
        result = super().set_values()
        current = parameter.get_param(key, default='False')
        if previous != current:
            _logger.warning(
                'FORMULA_AUTO_APPROVAL_SETTING_CHANGED previous=%s current=%s user_id=%s',
                previous, current, self.env.user.id,
            )
        else:
            _logger.info(
                'FORMULA_AUTO_APPROVAL_SETTING_SAVED value=%s user_id=%s',
                current, self.env.user.id,
            )
        return result
