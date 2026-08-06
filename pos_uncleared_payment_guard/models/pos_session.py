# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger("pos_uncleared_payment_guard.pos_session")


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config_id):
        models_to_load = super()._load_pos_data_models(config_id)
        if "account.journal" not in models_to_load:
            models_to_load.append("account.journal")
        _logger.debug("[UPG][PosSession] POS models extended with account.journal for config=%s", config_id)
        return models_to_load
