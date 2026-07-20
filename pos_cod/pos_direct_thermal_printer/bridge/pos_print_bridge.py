#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Local ESC/POS print bridge for Odoo POS.

Run this on the till PC where Chrome opens the POS. It listens on
127.0.0.1:9109 and writes RAW ESC/POS bytes to a Windows printer.
"""

import argparse
import base64
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import win32print
except Exception as import_error:  # pragma: no cover - printed at runtime
    win32print = None
    WIN32PRINT_IMPORT_ERROR = import_error
else:
    WIN32PRINT_IMPORT_ERROR = None


LOG = logging.getLogger("pos_print_bridge")


class BridgeConfig:
    host = "127.0.0.1"
    port = 9109
    default_printer = ""
    token = ""


def json_response(handler, status, payload):
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Odoo-Print-Token")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


def list_printers():
    if not win32print:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [printer[2] for printer in win32print.EnumPrinters(flags)]


def get_default_printer():
    if not win32print:
        return ""
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        LOG.exception("Could not read Windows default printer")
        return ""


def write_raw(printer_name, payload, job_id):
    if not win32print:
        raise RuntimeError(f"win32print unavailable: {WIN32PRINT_IMPORT_ERROR}")
    handle = None
    try:
        handle = win32print.OpenPrinter(printer_name)
        win32print.StartDocPrinter(handle, 1, (str(job_id), None, "RAW"))
        win32print.StartPagePrinter(handle)
        written = win32print.WritePrinter(handle, payload)
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
        return written
    finally:
        if handle:
            win32print.ClosePrinter(handle)


class PrintBridgeHandler(BaseHTTPRequestHandler):
    server_version = "OdooPosPrintBridge/1.0"

    def log_message(self, fmt, *args):
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def do_OPTIONS(self):
        json_response(self, 200, {"ok": True})

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            windows_default = get_default_printer()
            json_response(
                self,
                200,
                {
                    "ok": True,
                    "service": "odoo-pos-print-bridge",
                    "win32print": bool(win32print),
                    "configured_printer": BridgeConfig.default_printer,
                    "windows_default_printer": windows_default,
                    "effective_default_printer": BridgeConfig.default_printer or windows_default,
                },
            )
            return
        if self.path.rstrip("/") == "/printers":
            json_response(self, 200, {"ok": True, "printers": list_printers()})
            return
        json_response(self, 404, {"ok": False, "message": "Unknown endpoint."})

    def do_POST(self):
        if self.path.rstrip("/") != "/print":
            json_response(self, 404, {"ok": False, "message": "Unknown endpoint."})
            return
        if BridgeConfig.token:
            received = self.headers.get("X-Odoo-Print-Token", "")
            if received != BridgeConfig.token:
                LOG.warning("Rejected print job: invalid token")
                json_response(self, 403, {"ok": False, "message": "Invalid bridge token."})
                return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body or "{}")
            available_printers = list_printers()
            windows_default = get_default_printer()
            printer = data.get("printer") or BridgeConfig.default_printer or windows_default
            job_id = data.get("job_id") or "odoo-pos-receipt"
            payload_base64 = data.get("payload_base64") or ""
            payload = base64.b64decode(payload_base64)
            if not printer:
                raise ValueError("Printer is empty and no default printer was configured.")
            if available_printers and printer not in available_printers:
                raise ValueError(
                    "Printer is not in Windows printer list. "
                    f"requested={printer!r}; windows_default={windows_default!r}; "
                    f"available={available_printers!r}"
                )
            LOG.info(
                "Printing job_id=%s printer=%s bytes=%s summary=%s",
                job_id,
                printer,
                len(payload),
                data.get("receipt_summary") or {},
            )
            written = write_raw(printer, payload, job_id)
            json_response(
                self,
                200,
                {
                    "ok": True,
                    "printer": printer,
                    "job_id": job_id,
                    "bytes": len(payload),
                    "written": written,
                },
            )
        except Exception as error:
            LOG.exception("Print job failed")
            json_response(self, 500, {"ok": False, "message": str(error)})


def parse_args():
    parser = argparse.ArgumentParser(description="Odoo POS local ESC/POS print bridge")
    parser.add_argument("--host", default=BridgeConfig.host)
    parser.add_argument("--port", type=int, default=BridgeConfig.port)
    parser.add_argument("--printer", default="")
    parser.add_argument("--token", default="")
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args()
    BridgeConfig.host = args.host
    BridgeConfig.port = args.port
    BridgeConfig.default_printer = args.printer
    BridgeConfig.token = args.token
    if not win32print:
        LOG.error("win32print unavailable: %s", WIN32PRINT_IMPORT_ERROR)
    else:
        LOG.info("Available printers: %s", list_printers())
    server = ThreadingHTTPServer((BridgeConfig.host, BridgeConfig.port), PrintBridgeHandler)
    LOG.info(
        "Odoo POS print bridge listening at http://%s:%s default_printer=%s",
        BridgeConfig.host,
        BridgeConfig.port,
        BridgeConfig.default_printer or "<request printer/default empty>",
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
