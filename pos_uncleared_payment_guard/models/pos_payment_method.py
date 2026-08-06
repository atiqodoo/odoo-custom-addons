# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger("pos_uncleared_payment_guard.pos_payment_method")


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    upg_is_uncleared_guard_method = fields.Boolean(
        string="Default Uncleared Guard Method",
        default=False,
        help=(
            "Optional global marker for methods such as Bank Cheque. "
            "POS config mapping remains the main control."
        ),
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if "upg_is_uncleared_guard_method" not in fields_list:
            fields_list.append("upg_is_uncleared_guard_method")
        _logger.debug(
            "[UPG][PaymentMethod] POS data fields extended for config_id=%s",
            config_id,
        )
        return fields_list
