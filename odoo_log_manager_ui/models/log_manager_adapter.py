import json
import logging
import os
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LogManagerAdapter(models.AbstractModel):
    _name = "log.manager.adapter"
    _description = "Log Manager Engine Adapter"

    @api.model
    def get_pipeline(self):
        start = time.monotonic()
        _logger.debug("[LOG_MANAGER][PIPELINE_LOAD][START] uid=%s", self.env.uid)
        engine_path = self._get_engine_path()
        config_path = None
        if str(engine_path) not in sys.path:
            sys.path.insert(0, str(engine_path))
        self._reload_engine_modules()

        try:
            from config.settings import Settings
            from core.pipeline import LogPipeline
        except Exception as exc:
            raise UserError("Could not load log manager engine: %s" % exc) from exc

        try:
            config_path = self._get_config_path()
            settings = Settings.load(config_path if config_path else None)
            settings = self._settings_with_ui_overrides(Settings, settings)
            pipeline = LogPipeline(settings)
        except Exception:
            _logger.exception(
                "[LOG_MANAGER][PIPELINE_LOAD][ERROR] engine_path=%s config_path=%s",
                engine_path,
                config_path,
            )
            raise

        _logger.debug(
            "[LOG_MANAGER][PIPELINE_LOAD][END] engine_path=%s config_path=%s duration=%.3fs",
            engine_path,
            config_path,
            time.monotonic() - start,
        )
        return pipeline

    @api.model
    def tail(self, source_path, lines=100):
        pipeline = self.get_pipeline()
        try:
            raw_entries = pipeline.tail(Path(source_path), int(lines or 100))
            parsed = []
            for entry in raw_entries:
                parsed_entry = pipeline.parser.parse(entry.raw, entry.line_no) or entry
                for processor in pipeline.processors:
                    parsed_entry = processor.process(parsed_entry)
                parsed.append(parsed_entry)
            return parsed
        finally:
            pipeline.close()

    @api.model
    def search(self, criteria):
        engine_path = self._get_engine_path()
        if str(engine_path) not in sys.path:
            sys.path.insert(0, str(engine_path))
        self._reload_engine_modules()
        from core.contracts import SearchCriteria

        prepared = dict(criteria)
        for key in ("since", "until"):
            if isinstance(prepared.get(key), str):
                prepared[key] = datetime.fromisoformat(prepared[key])

        pipeline = self.get_pipeline()
        try:
            return pipeline.search(SearchCriteria(**prepared))
        finally:
            pipeline.close()

    @api.model
    def archives(self):
        pipeline = self.get_pipeline()
        try:
            return pipeline.archives()
        finally:
            pipeline.close()

    @api.model
    def rotate_and_index(self):
        start = time.monotonic()
        _logger.debug("[LOG_MANAGER][ROTATE_INDEX][START] uid=%s", self.env.uid)
        pipeline = self.get_pipeline()
        try:
            result = pipeline.run()
            _logger.debug(
                "[LOG_MANAGER][ROTATE_INDEX][END] duration=%.3fs result=%s",
                time.monotonic() - start,
                self.dumps_result(result),
            )
            return result
        except Exception:
            _logger.exception(
                "[LOG_MANAGER][ROTATE_INDEX][ERROR] duration=%.3fs",
                time.monotonic() - start,
            )
            raise
        finally:
            pipeline.close()

    @api.model
    def discover_sources(self):
        pipeline = self.get_pipeline()
        try:
            return pipeline._monitored_paths()
        finally:
            pipeline.close()

    @api.model
    def config_health(self):
        engine_path = self._safe_engine_path()
        config_path = self._get_config_path()
        return {
            "engine_path": str(engine_path) if engine_path else "",
            "engine_exists": bool(engine_path and engine_path.exists()),
            "config_path": str(config_path) if config_path else "",
            "config_exists": bool(config_path and config_path.exists()),
        }

    @api.model
    def _get_engine_path(self):
        engine_path = self._safe_engine_path()
        if not engine_path or not engine_path.exists():
            raise UserError(
                "Log manager engine path is not configured. "
                "Set it in Settings or LOG_MANAGER_ENGINE_PATH."
            )
        return engine_path

    @api.model
    def _safe_engine_path(self):
        params = self.env["ir.config_parameter"].sudo()
        configured = params.get_param("odoo_log_manager_ui.engine_path")
        raw = configured or os.environ.get("LOG_MANAGER_ENGINE_PATH")
        if raw:
            return Path(raw).expanduser()
        return self._find_engine_path()

    @api.model
    def _get_config_path(self):
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("odoo_log_manager_ui.config_path")
        )
        if raw:
            return Path(raw).expanduser()
        engine_path = self._safe_engine_path()
        if engine_path:
            candidate = engine_path / "config" / "example.odoo18.json"
            if candidate.exists():
                return candidate
        return None

    @api.model
    def _find_engine_path(self):
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "log_manager"
            if (candidate / "core" / "pipeline.py").exists():
                return candidate
        return None

    @api.model
    def dumps_result(self, value):
        return json.dumps(value, default=str, indent=2)

    @api.model
    def _settings_with_ui_overrides(self, settings_cls, settings):
        config = deepcopy(settings.raw())
        params = self.env["ir.config_parameter"].sudo()

        strategy = params.get_param("odoo_log_manager_ui.rotation_strategy")
        max_size_mb = self._int_param(params, "odoo_log_manager_ui.max_size_mb")
        locked_file_mode = params.get_param("odoo_log_manager_ui.locked_file_mode")
        interval_number = self._int_param(
            params, "odoo_log_manager_ui.auto_rotate_interval_number"
        )
        interval_type = params.get_param("odoo_log_manager_ui.auto_rotate_interval_type")

        rotation = config.setdefault("rotation", {})
        if strategy:
            rotation["strategy"] = strategy
        if max_size_mb:
            rotation["max_size_mb"] = max_size_mb
        if locked_file_mode:
            rotation["locked_file_mode"] = locked_file_mode
        if interval_number and interval_type:
            rotation["interval_hours"] = self._interval_to_hours(
                interval_number, interval_type
            )

        _logger.debug(
            "[LOG_MANAGER][CONFIG_OVERRIDE][END] strategy=%s max_size_mb=%s locked_file_mode=%s interval_number=%s interval_type=%s",
            rotation.get("strategy"),
            rotation.get("max_size_mb"),
            rotation.get("locked_file_mode"),
            interval_number,
            interval_type,
        )
        return settings_cls(config)

    def _int_param(self, params, key):
        raw = params.get_param(key)
        if raw in (None, False, ""):
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            _logger.warning("[LOG_MANAGER][CONFIG_OVERRIDE][ERROR] key=%s value=%s", key, raw)
            return 0

    def _interval_to_hours(self, number, interval_type):
        factors = {
            "minutes": 1 / 60,
            "hours": 1,
            "days": 24,
            "weeks": 24 * 7,
            "months": 24 * 30,
        }
        return max(1, int(number * factors.get(interval_type, 1)))

    def _reload_engine_modules(self):
        prefixes = ("config.", "core.", "parsers.", "plugins.")
        for name in list(sys.modules):
            if name in ("config", "core", "parsers", "plugins") or name.startswith(prefixes):
                sys.modules.pop(name, None)
