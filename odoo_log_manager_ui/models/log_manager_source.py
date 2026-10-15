from pathlib import Path
from datetime import datetime
import logging
import time

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LogManagerSource(models.Model):
    _name = "log.manager.source"
    _description = "Log Manager Source"
    _order = "name"

    name = fields.Char(required=True)
    path = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    size_bytes = fields.Integer(readonly=True)
    size_mb = fields.Float(readonly=True, digits=(16, 2))
    last_modified = fields.Datetime(readonly=True)
    exists = fields.Boolean(readonly=True)
    tail_lines = fields.Integer(default=100)
    last_refresh = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("path_unique", "unique(path)", "Each log source path must be unique."),
    ]

    @api.model
    def action_discover_sources(self):
        adapter = self.env["log.manager.adapter"]
        for path in adapter.discover_sources():
            path_obj = Path(path)
            values = {
                "name": path_obj.name,
                "path": str(path_obj),
                "active": True,
            }
            existing = self.search([("path", "=", str(path_obj))], limit=1)
            if existing:
                existing.write(values)
            else:
                self.create(values)
        self.search([]).action_refresh_metadata()
        return self._action_open_sources()

    def action_refresh_metadata(self):
        for record in self:
            path = Path(record.path)
            values = {
                "exists": path.exists(),
                "last_refresh": fields.Datetime.now(),
            }
            if path.exists():
                stat = path.stat()
                values.update(
                    {
                        "size_bytes": stat.st_size,
                        "size_mb": stat.st_size / 1024 / 1024,
                        "last_modified": fields.Datetime.to_string(
                            datetime.fromtimestamp(stat.st_mtime)
                        ),
                    }
                )
            record.write(values)
        return True

    def action_tail(self):
        self.ensure_one()
        if not self.path:
            raise UserError("Log source path is missing.")

        entries = self.env["log.manager.adapter"].tail(self.path, self.tail_lines)
        entry_model = self.env["log.manager.entry"].sudo()
        entry_model.search(
            [("source_type", "=", "live"), ("source_path", "=", self.path)]
        ).unlink()

        values = [self._entry_values(entry) for entry in entries]
        if values:
            entry_model.create(values)

        return {
            "type": "ir.actions.act_window",
            "name": "Live Logs - %s" % self.name,
            "res_model": "log.manager.entry",
            "view_mode": "list,form",
            "domain": [("source_type", "=", "live"), ("source_path", "=", self.path)],
            "context": {"search_default_group_by_level": 1},
        }

    def action_rotate_and_index(self):
        start = time.monotonic()
        _logger.debug("[LOG_MANAGER][SOURCE_ROTATE_INDEX][START] uid=%s", self.env.uid)
        try:
            result = self.env["log.manager.adapter"].rotate_and_index()
            self.env["log.manager.archive"].sudo().action_sync_archives()
        except Exception as exc:
            _logger.exception(
                "[LOG_MANAGER][SOURCE_ROTATE_INDEX][ERROR] duration=%.3fs error=%s",
                time.monotonic() - start,
                exc,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Log manager",
                    "message": "Rotation/indexing failed: %s" % exc,
                    "type": "danger",
                    "sticky": True,
                },
            }
        _logger.debug(
            "[LOG_MANAGER][SOURCE_ROTATE_INDEX][END] duration=%.3fs",
            time.monotonic() - start,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Log manager",
                "message": "Rotation/indexing finished: %s" % result,
                "type": "success",
                "sticky": False,
            },
        }

    @api.model
    def action_auto_rotate_and_index(self):
        params = self.env["ir.config_parameter"].sudo()
        enabled = self._param_as_bool(
            params.get_param("odoo_log_manager_ui.auto_rotate_enabled")
        )
        if not enabled:
            _logger.debug("[LOG_MANAGER][AUTO_ROTATE_INDEX][END] enabled=False")
            return False

        start = time.monotonic()
        _logger.debug("[LOG_MANAGER][AUTO_ROTATE_INDEX][START] uid=%s", self.env.uid)
        try:
            result = self.env["log.manager.adapter"].rotate_and_index()
            self.env["log.manager.archive"].sudo().action_sync_archives()
        except Exception:
            _logger.exception(
                "[LOG_MANAGER][AUTO_ROTATE_INDEX][ERROR] duration=%.3fs",
                time.monotonic() - start,
            )
            raise
        _logger.debug(
            "[LOG_MANAGER][AUTO_ROTATE_INDEX][END] duration=%.3fs result=%s",
            time.monotonic() - start,
            self.env["log.manager.adapter"].dumps_result(result),
        )
        return result

    def _param_as_bool(self, value):
        return str(value).lower() in ("1", "true", "yes", "on")

    def _entry_values(self, entry):
        timestamp = entry.timestamp
        return {
            "timestamp": fields.Datetime.to_string(timestamp) if timestamp else False,
            "level": entry.level if entry.level in dict(self.env["log.manager.entry"]._fields["level"].selection) else False,
            "database": entry.database,
            "module": entry.module,
            "message": entry.message,
            "raw": entry.raw,
            "line_no": entry.line_no,
            "source_path": self.path,
            "source_type": "live",
        }

    def _action_open_sources(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Log Sources",
            "res_model": "log.manager.source",
            "view_mode": "list,form",
        }
