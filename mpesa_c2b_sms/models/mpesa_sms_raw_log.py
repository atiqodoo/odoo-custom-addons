"""
Immutable audit trail for every SMS received from the bridge.
Written once — never updated or deleted (compliance requirement).
Parsing happens in IngestService; results go to mpesa.transaction.
"""
import logging

from odoo import fields, models

_log = logging.getLogger(__name__)


class MpesaSmsRawLog(models.Model):
    _name        = 'mpesa.sms.raw.log'
    _description = 'M-Pesa SMS Raw Log'
    _order       = 'received_at desc'

    # Bridge-supplied fields
    queue_id     = fields.Char('Bridge Queue ID', index=True, readonly=True)
    raw_text     = fields.Text('Raw SMS Text', readonly=True)
    source_phone = fields.Char('Sender Number', readonly=True)
    received_at  = fields.Datetime('Received At', readonly=True, index=True)
    modem_index  = fields.Integer('Modem Index', readonly=True)

    # Parse outcome — set by IngestService
    parse_status = fields.Selection(
        [('pending', 'Pending'), ('success', 'Parsed'), ('failed', 'Failed')],
        default='pending', readonly=True, index=True,
    )
    parse_error  = fields.Text('Parse Error Detail', readonly=True)
    transaction_id = fields.Many2one(
        'mpesa.transaction', 'Transaction', readonly=True, ondelete='set null',
    )

    _sql_constraints = [
        ('queue_id_uniq', 'UNIQUE(queue_id)',
         'Duplicate bridge queue_id — SMS already ingested.'),
    ]

    def mark_parsed(self, transaction):
        self.sudo().write({
            'parse_status':   'success',
            'transaction_id': transaction.id,
        })
        _log.info("Raw log %d → transaction %d", self.id, transaction.id)

    def mark_failed(self, error: str):
        self.sudo().write({
            'parse_status': 'failed',
            'parse_error':  error[:2000],
        })
        _log.warning("Raw log %d parse failed: %s", self.id, error[:120])
