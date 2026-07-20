# -*- coding: utf-8 -*-
"""Manufacturing settings for the POS tinted-product oversell policy."""

import logging

from odoo import fields, models


_logger = logging.getLogger(__name__)

BLOCK_TINTED_OVERSELL_PARAM = (
    "pos_neg_stock_anglosaxon.block_tinted_oversell_without_normal_lot"
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    block_tinted_oversell_without_normal_lot = fields.Boolean(
        string="Block Tinted POS Oversell Without a Normal Lot",
        config_parameter=BLOCK_TINTED_OVERSELL_PARAM,
        default=False,
        help=(
            "When enabled, POS cashiers cannot sell a tinted product when only "
            "temporary POS oversell lots exist and no normal manufactured lot is "
            "available. When disabled, POS hides existing temporary lots but allows "
            "the sale to continue without a lot so the backend creates a new temporary "
            "lot after POS completion."
        ),
    )

    def set_values(self):
        parameter = self.env["ir.config_parameter"].sudo()
        previous = parameter.get_param(BLOCK_TINTED_OVERSELL_PARAM, default="False")
        result = super().set_values()
        current = parameter.get_param(BLOCK_TINTED_OVERSELL_PARAM, default="False")
        log_values = {
            "previous": previous,
            "current": current,
            "user_id": self.env.user.id,
            "user": self.env.user.display_name,
        }
        if previous != current:
            _logger.warning(
                "[NegStock][TINTED_OVERSELL_SETTING] changed | %s",
                log_values,
            )
        else:
            _logger.info(
                "[NegStock][TINTED_OVERSELL_SETTING] saved unchanged | %s",
                log_values,
            )
        return result

