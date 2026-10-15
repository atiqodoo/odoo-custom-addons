# -*- coding: utf-8 -*-
import logging
import os
from collections import deque

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools import config

_logger = logging.getLogger("pos_uncleared_payment_guard.log_tail")


class PosUnclearedPaymentLogTailWizard(models.TransientModel):
    _name = "pos.uncleared.payment.log.tail"
    _description = "POS Uncleared Payment Backend Log Tail"

    pos_config_id = fields.Many2one("pos.config", readonly=True)
    line_count = fields.Integer(
        default=lambda self: self.env[
            "pos.uncleared.payment.guard.settings"
        ].DEFAULT_LOG_TAIL_LINES,
        required=True,
    )
    upg_only = fields.Boolean(string="Only [UPG] Lines", default=True)
    log_file_path = fields.Char(readonly=True)
    log_tail = fields.Text(string="Backend Log Tail", readonly=True)

    def action_refresh(self):
        self.ensure_one()
        settings = self.env["pos.uncleared.payment.guard.settings"]
        self.line_count = settings.log_tail_lines(self.pos_config_id)
        log_path = self._resolve_log_file_path()
        if not log_path:
            raise UserError(_("No backend log file path is configured or discoverable."))
        if not os.path.exists(log_path):
            raise UserError(_("Backend log file was not found: %s") % log_path)

        lines = self._tail_file(log_path, self.line_count, upg_only=self.upg_only)
        self.write({
            "log_file_path": log_path,
            "log_tail": "".join(lines) or _("No matching log lines found."),
        })
        _logger.warning(
            "[UPG][LogTail] refreshed config=%s path=%s lines=%s upg_only=%s user=%s",
            self.pos_config_id.display_name,
            log_path,
            self.line_count,
            self.upg_only,
            self.env.user.login,
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("UPG Backend Log Tail"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _resolve_log_file_path(self):
        configured = (
            self.pos_config_id.upg_backend_log_file_path
            or config.get("logfile")
        )
        candidates = [
            configured,
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        return configured

    def _tail_file(self, log_path, line_count, upg_only=True):
        max_lines = max(1, int(line_count or 1))
        lines = deque(maxlen=max_lines)
        with open(log_path, "r", encoding="utf-8", errors="replace") as log_file:
            for line in log_file:
                if upg_only and "[UPG]" not in line:
                    continue
                lines.append(line)
        return list(lines)
