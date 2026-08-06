# -*- coding: utf-8 -*-
import logging

from odoo import api, models


_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def pos_idle_lock_audit(self, session_id, event, payload=None):
        payload = payload or {}
        session = self.browse(session_id).exists()
        _logger.info(
            "POS idle session lock audit | session_id=%s session_name=%s config_id=%s event=%s payload=%s",
            session.id if session else session_id,
            session.name if session else False,
            session.config_id.id if session else payload.get("config_id"),
            event,
            payload,
        )
        return True
