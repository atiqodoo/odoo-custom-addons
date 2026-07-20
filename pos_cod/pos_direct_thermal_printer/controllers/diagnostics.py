# -*- coding: utf-8 -*-
import base64
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger("pos_direct_thermal_printer.diagnostics")


class PosDirectThermalPrinterDiagnostics(http.Controller):
    @http.route(
        "/pos_direct_thermal_printer/log",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def log(self, **payload):
        level = str(payload.get("level") or "info").lower()
        message = payload.get("message") or ""
        data = payload.get("data") or {}
        config_id = payload.get("config_id")
        order_uid = payload.get("order_uid")
        user = request.env.user
        log_payload = {
            "db": request.env.cr.dbname,
            "user": user.login,
            "user_id": user.id,
            "config_id": config_id,
            "order_uid": order_uid,
            "data": data,
        }
        logger = getattr(_logger, level, _logger.info)
        logger("[DTRP][pos] %s | %s", message, log_payload)
        return {"ok": True}

    @http.route(
        "/pos_direct_thermal_printer/windows_raw_print",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def windows_raw_print(self, **payload):
        printer = payload.get("printer")
        job_id = payload.get("job_id") or "odoo-pos-receipt"
        payload_base64 = payload.get("payload_base64") or ""
        config_id = payload.get("config_id")
        summary = payload.get("receipt_summary") or {}
        _logger.info(
            "[DTRP][windows_raw] Incoming print job config_id=%s printer=%s job_id=%s summary=%s",
            config_id,
            printer,
            job_id,
            summary,
        )
        if not printer:
            return {"ok": False, "message": "Printer name is empty."}
        try:
            raw_bytes = base64.b64decode(payload_base64)
        except Exception as error:
            _logger.exception("[DTRP][windows_raw] Invalid base64 payload: %s", error)
            return {"ok": False, "message": "Invalid print payload."}
        try:
            import win32print
        except Exception as error:
            _logger.exception("[DTRP][windows_raw] pywin32 win32print import failed: %s", error)
            return {
                "ok": False,
                "message": "win32print is not available in the Odoo Python environment.",
            }
        handle = None
        try:
            handle = win32print.OpenPrinter(printer)
            win32print.StartDocPrinter(handle, 1, (str(job_id), None, "RAW"))
            win32print.StartPagePrinter(handle)
            written = win32print.WritePrinter(handle, raw_bytes)
            win32print.EndPagePrinter(handle)
            win32print.EndDocPrinter(handle)
            _logger.info(
                "[DTRP][windows_raw] Print job completed printer=%s job_id=%s bytes=%s written=%s",
                printer,
                job_id,
                len(raw_bytes),
                written,
            )
            return {"ok": True, "printer": printer, "job_id": job_id, "bytes": len(raw_bytes)}
        except Exception as error:
            _logger.exception(
                "[DTRP][windows_raw] Print job failed printer=%s job_id=%s: %s",
                printer,
                job_id,
                error,
            )
            return {"ok": False, "message": str(error), "printer": printer, "job_id": job_id}
        finally:
            if handle:
                win32print.ClosePrinter(handle)
