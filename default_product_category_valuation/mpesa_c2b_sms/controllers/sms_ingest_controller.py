"""
HTTP endpoints consumed by the Windows bridge service.
All routes are public (no session cookie) but protected by Bearer token.

POST /mpesa/sms/ingest   → 202 | 409 | 400 | 401
POST /mpesa/modem/health → 202
POST /mpesa/modem/alert  → 202
"""
import json
import logging

from odoo import SUPERUSER_ID, api, http
from odoo.http import request
from odoo.modules.registry import Registry

from ..models.mpesa_modem_health import MpesaModemHealth
from ..services.ingest_service import IngestService

_log = logging.getLogger(__name__)


def _get_dbname() -> str:
    """Bridge calls do not have an Odoo browser session, so db is explicit."""
    return request.httprequest.args.get('db', '').strip()


def _verify_token(env) -> bool:
    """Validate the Bearer token from settings against the request header."""
    expected = (
        env['ir.config_parameter']
        .sudo()
        .get_param('mpesa_c2b_sms.api_token', '')
    )
    if not expected:
        _log.error("mpesa_c2b_sms.api_token not configured — all bridge requests rejected")
        return False

    auth_header = request.httprequest.headers.get('Authorization', '')
    token = auth_header.removeprefix('Bearer ').strip()
    return token == expected


def _json_response(data: dict, status: int = 200):
    body = json.dumps(data)
    return request.make_response(
        body,
        headers=[
            ('Content-Type', 'application/json'),
            ('Content-Length', str(len(body))),
        ],
        status=status,
    )


class SmsIngestController(http.Controller):

    @http.route('/mpesa/sms/ingest', type='http', auth='none', methods=['POST'], csrf=False)
    def ingest(self, **_kw):
        try:
            payload = json.loads(request.httprequest.data)
        except json.JSONDecodeError as exc:
            _log.warning("Invalid JSON from bridge: %s", exc)
            return _json_response({'error': 'Invalid JSON'}, 400)

        queue_id = payload.get('queue_id', '')
        if not queue_id or not payload.get('raw_text'):
            return _json_response({'error': 'Missing queue_id or raw_text'}, 400)

        dbname = _get_dbname()
        if not dbname:
            return _json_response({'error': 'Missing db query parameter'}, 400)

        _log.info("Ingest received queue_id=%s", queue_id)

        try:
            registry = Registry(dbname)
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                if not _verify_token(env):
                    return _json_response({'error': 'Unauthorized'}, 401)
                service = IngestService(env)
                outcome, record = service.ingest(payload)
                cr.commit()
        except Exception as exc:
            _log.exception("Ingest pipeline error queue_id=%s: %s", queue_id, exc)
            return _json_response({'error': 'Internal error'}, 500)

        if outcome == 'duplicate':
            return _json_response({'status': 'duplicate', 'queue_id': queue_id}, 409)

        if outcome == 'parse_error':
            # Return 202 so bridge marks it forwarded — parse issues are Odoo's problem
            return _json_response({'status': 'parse_error', 'queue_id': queue_id}, 202)

        return _json_response({'status': 'created', 'queue_id': queue_id}, 202)

    @http.route('/mpesa/modem/health', type='http', auth='none', methods=['POST'], csrf=False)
    def health(self, **_kw):
        dbname = _get_dbname()
        if not dbname:
            return _json_response({'error': 'Missing db query parameter'}, 400)

        try:
            payload = json.loads(request.httprequest.data)
            registry = Registry(dbname)
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                if not _verify_token(env):
                    return _json_response({'error': 'Unauthorized'}, 401)
                MpesaModemHealth.record_health(env, payload)
                cr.commit()
        except Exception as exc:
            _log.warning("Health record failed: %s", exc)

        return _json_response({'status': 'ok'}, 202)

    @http.route('/mpesa/modem/alert', type='http', auth='none', methods=['POST'], csrf=False)
    def alert(self, **_kw):
        dbname = _get_dbname()
        if not dbname:
            return _json_response({'error': 'Missing db query parameter'}, 400)

        try:
            registry = Registry(dbname)
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                if not _verify_token(env):
                    return _json_response({'error': 'Unauthorized'}, 401)
            payload = json.loads(request.httprequest.data)
            alert_type = payload.get('type', 'unknown')
            message    = payload.get('message', '')
            _log.warning("Bridge alert [%s]: %s", alert_type, message)
        except Exception as exc:
            _log.warning("Alert endpoint error: %s", exc)

        return _json_response({'status': 'received'}, 202)
