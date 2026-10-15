# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger("pos_uncleared_payment_guard.settings")


class PosUnclearedPaymentGuardSettings(models.AbstractModel):
    _name = "pos.uncleared.payment.guard.settings"
    _description = "POS Uncleared Payment Guard Runtime Settings"

    DEFAULT_CRON_INTERVAL_SECONDS = 300
    DEFAULT_MOVE_CANDIDATE_LIMIT = 400
    DEFAULT_STATEMENT_CANDIDATE_LIMIT = 300
    DEFAULT_LOG_TAIL_LINES = 200

    PARAM_LAST_CRON_RUN = "pos_uncleared_payment_guard.last_cron_run"

    @api.model
    def cron_interval_seconds(self, config=False):
        if config:
            return self._positive_int(
                config.upg_reconciliation_scan_interval_seconds,
                self.DEFAULT_CRON_INTERVAL_SECONDS,
            )

        configs = self.env["pos.config"].sudo().search([
            ("upg_reconciliation_scan_interval_seconds", ">", 0),
        ])
        values = [
            self._positive_int(
                config.upg_reconciliation_scan_interval_seconds,
                self.DEFAULT_CRON_INTERVAL_SECONDS,
            )
            for config in configs
        ]
        return min(values) if values else self.DEFAULT_CRON_INTERVAL_SECONDS

    @api.model
    def detector_options(self, hold=False):
        config = hold.pos_config_id if hold and hold.pos_config_id else self.env["pos.config"]
        move_limit = config.upg_detector_move_candidate_limit if config else 0
        statement_limit = config.upg_detector_statement_candidate_limit if config else 0
        backend_debug_logging = config.upg_backend_debug_logging if config else True
        return {
            "move_candidate_limit": self._positive_int(
                move_limit,
                self.DEFAULT_MOVE_CANDIDATE_LIMIT,
            ),
            "statement_candidate_limit": self._positive_int(
                statement_limit,
                self.DEFAULT_STATEMENT_CANDIDATE_LIMIT,
            ),
            "backend_debug_logging": bool(backend_debug_logging),
        }

    @api.model
    def log_tail_lines(self, config=False):
        configured_lines = config.upg_backend_log_tail_lines if config else 0
        return self._positive_int(
            configured_lines,
            self.DEFAULT_LOG_TAIL_LINES,
        )

    @api.model
    def should_run_cron_scan(self):
        interval_seconds = self.cron_interval_seconds()
        ICP = self.env["ir.config_parameter"].sudo()
        last_run = fields.Datetime.to_datetime(
            ICP.get_param(self.PARAM_LAST_CRON_RUN) or False
        )
        now = fields.Datetime.now()
        if last_run:
            elapsed = (now - last_run).total_seconds()
            if elapsed < interval_seconds:
                _logger.info(
                    "[UPG][Settings] cron scan skipped elapsed=%.2fs configured_interval=%ss",
                    elapsed,
                    interval_seconds,
                )
                return False
        ICP.set_param(self.PARAM_LAST_CRON_RUN, fields.Datetime.to_string(now))
        _logger.warning(
            "[UPG][Settings] cron scan allowed configured_interval=%ss previous_run=%s",
            interval_seconds,
            last_run,
        )
        return True

    @api.model
    def _positive_int(self, value, fallback):
        try:
            value = int(value or 0)
        except (TypeError, ValueError):
            return fallback
        return value if value > 0 else fallback
