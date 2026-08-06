"""
Time-series modem health records posted by the bridge every 60s.
Drives the dashboard health widget and alerts cashiers to modem issues.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

_log = logging.getLogger(__name__)


class MpesaModemHealth(models.Model):
    _name        = 'mpesa.modem.health'
    _description = 'M-Pesa Modem Health Record'
    _order       = 'timestamp desc'

    timestamp         = fields.Datetime('Recorded At', required=True, index=True)
    storage_used      = fields.Integer('Slots Used')
    storage_total     = fields.Integer('Slots Total')
    usage_pct         = fields.Float('Usage %', digits=(5, 2))
    status            = fields.Selection(
        [('ok', 'OK'), ('warning', 'Warning'), ('critical', 'Critical')],
        default='ok',
    )
    modem_connected   = fields.Boolean('Modem Connected', default=True)
    last_sms_received = fields.Datetime('Last SMS Received At')
    queue_pending     = fields.Integer('Queue Pending')
    queue_forwarded   = fields.Integer('Queue Forwarded')
    queue_failed      = fields.Integer('Queue Failed')

    @classmethod
    def record_health(cls, env, payload: dict):
        """Called by the ingest controller to persist a health report."""
        qs = payload.get('queue_stats', {})
        rec = env['mpesa.modem.health'].sudo().create({
            'timestamp':         payload.get('timestamp'),
            'storage_used':      payload.get('storage_used', 0),
            'storage_total':     payload.get('storage_total', 0),
            'usage_pct':         payload.get('usage_pct', 0.0),
            'status':            payload.get('status', 'ok'),
            'modem_connected':   payload.get('modem_connected', True),
            'last_sms_received': payload.get('last_sms_received_at') or False,
            'queue_pending':     qs.get('pending', 0),
            'queue_forwarded':   qs.get('forwarded', 0),
            'queue_failed':      qs.get('failed', 0),
        })
        _log.debug("Health recorded id=%d status=%s", rec.id, rec.status)
        return rec

    @classmethod
    def latest(cls, env):
        """Return the most recent health record for dashboard display."""
        return env['mpesa.modem.health'].sudo().search([], limit=1)

    @api.model
    def _cron_purge_old_records(self):
        cutoff = fields.Datetime.now() - timedelta(days=7)
        old_records = self.search([('timestamp', '<', cutoff)])
        old_records.unlink()
        _log.info("Purged %d old M-Pesa modem health record(s)", len(old_records))
