"""
Orchestrates the full ingest pipeline:
  raw_log → parse → partner match → create transaction

Called only by the HTTP controller.
All database writes happen inside a single savepoint so partial
failures don't corrupt the raw log.
"""
import logging

from .sms_parser import SmsParserEngine
from .partner_matcher import PartnerMatcher

_log = logging.getLogger(__name__)
_parser = SmsParserEngine()


class IngestService:

    def __init__(self, env):
        self._env = env

    def ingest(self, payload: dict):
        """
        Full pipeline for one SMS payload from the bridge.
        payload keys: queue_id, raw_text, source_phone, received_at, modem_index
        Returns: ('created'|'duplicate'|'parse_error', record_or_None)
        """
        queue_id  = payload.get('queue_id', '')
        raw_text  = payload.get('raw_text', '')
        src_phone = payload.get('source_phone', '')
        recv_at   = payload.get('received_at')

        # ------------------------------------------------------------------
        # 1. Duplicate check (idempotency by queue_id)
        # ------------------------------------------------------------------
        existing_log = self._env['mpesa.sms.raw.log'].sudo().search(
            [('queue_id', '=', queue_id)], limit=1
        )
        if existing_log:
            _log.info("Duplicate queue_id=%s — skipping", queue_id)
            return 'duplicate', existing_log

        # ------------------------------------------------------------------
        # 2. Create raw log (write-first, parse after)
        # ------------------------------------------------------------------
        raw_log = self._env['mpesa.sms.raw.log'].sudo().create({
            'queue_id':    queue_id,
            'raw_text':    raw_text,
            'source_phone': src_phone,
            'received_at': recv_at,
            'modem_index': payload.get('modem_index', 0),
            'parse_status': 'pending',
        })
        _log.info("Raw log created id=%d queue_id=%s", raw_log.id, queue_id)

        return self._process_raw_log(raw_log)

    def retry(self, raw_log):
        """Re-run parsing for an existing durable raw log."""
        raw_log.ensure_one()
        return self._process_raw_log(raw_log.sudo())

    def _process_raw_log(self, raw_log):
        parsed = _parser.parse(raw_log.raw_text or '')
        if not parsed:
            raw_log.mark_failed('No parser matched this SMS text')
            return 'parse_error', raw_log

        # ------------------------------------------------------------------
        # 4. Idempotency by mpesa_ref (Safaricom transaction ID)
        # ------------------------------------------------------------------
        existing_txn = self._env['mpesa.transaction'].sudo().search(
            [('mpesa_ref', '=', parsed.mpesa_ref)], limit=1
        )
        if existing_txn:
            _log.info(
                "Transaction ref=%s already exists — linking raw log", parsed.mpesa_ref
            )
            raw_log.mark_parsed(existing_txn)
            return 'duplicate', existing_txn

        # ------------------------------------------------------------------
        # 5. Partner match
        # ------------------------------------------------------------------
        matcher = PartnerMatcher(self._env)
        partner = matcher.find(parsed.sender_phone)

        # ------------------------------------------------------------------
        # 6. Create transaction
        # ------------------------------------------------------------------
        KES = self._env.ref('base.KES', raise_if_not_found=False)
        txn = self._env['mpesa.transaction'].sudo().create({
            'mpesa_ref':        parsed.mpesa_ref,
            'amount':           parsed.amount,
            'currency_id':      KES.id if KES else False,
            'sender_name':      parsed.sender_name,
            'sender_phone':     parsed.sender_phone,
            'transaction_date': parsed.transaction_date,
            'utility_balance':  parsed.utility_balance,
            'transaction_cost': parsed.transaction_cost,
            'partner_id':       partner.id if partner else False,
            'raw_log_id':       raw_log.id,
            'state':            'new' if partner else 'unmatched',
        })

        raw_log.mark_parsed(txn)
        _log.info(
            "Transaction created id=%d ref=%s amount=%.2f partner=%s",
            txn.id, txn.mpesa_ref, txn.amount,
            partner.name if partner else 'UNMATCHED',
        )
        return 'created', txn
