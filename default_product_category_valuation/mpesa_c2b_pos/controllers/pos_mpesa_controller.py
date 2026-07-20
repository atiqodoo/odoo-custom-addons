"""
POS-facing JSON endpoints.
All validation logic lives here — the OWL frontend is display-only.

POST /pos/mpesa/validate  → find matching transaction(s) for a phone
POST /pos/mpesa/lock      → reserve a transaction for a POS session
POST /pos/mpesa/confirm   → finalise payment, link to pos.order
POST /pos/mpesa/release   → release lock (cashier cancelled)
"""
import json
import logging
import uuid
from datetime import datetime, timedelta

from odoo import http
from odoo.http import request

_log = logging.getLogger(__name__)
AVAILABLE_TRANSACTION_STATES = ('new', 'unmatched', 'partial_pos', 'partially_refunded')


def _release_state(txn):
    if hasattr(txn, '_available_state'):
        return txn._available_state()
    if txn.amount_remaining and txn.amount_remaining < txn.amount:
        return 'partial_pos'
    return 'new' if txn.partner_id else 'unmatched'


def _json(data: dict, status: int = 200):
    body = json.dumps(data, default=str)
    return request.make_response(
        body,
        headers=[('Content-Type', 'application/json'), ('Content-Length', str(len(body)))],
        status=status,
    )


def _get_param(key: str, default=None):
    return (
        request.env['ir.config_parameter']
        .sudo()
        .get_param(f'mpesa_c2b_sms.{key}', default)
    )


class PosMpesaController(http.Controller):

    # ------------------------------------------------------------------
    # VALIDATE — find transaction(s) by phone
    # ------------------------------------------------------------------

    @http.route('/pos/mpesa/validate', type='json', auth='user', methods=['POST'])
    def validate(self, phone: str, order_amount: float, pos_session_id: int, **_kw):
        """
        Cashier entered customer phone → search for matching M-Pesa transactions.
        Returns list so cashier can select if customer paid multiple times.
        """
        _log.info(
            "POS validate: phone=%s amount=%.2f session=%s",
            phone, order_amount, pos_session_id,
        )

        norm_phone = self._normalize_phone(phone)
        if not norm_phone:
            return {'status': 'invalid_phone', 'transactions': []}

        mpesa_method = self._get_session_mpesa_method(pos_session_id)
        tolerance = (
            mpesa_method.mpesa_amount_tolerance
            if mpesa_method
            else float(_get_param('amount_tolerance', 1.0))
        )
        now = datetime.utcnow()

        Txn = request.env['mpesa.transaction'].sudo()
        expired_locks = Txn.search([
            ('state', '=', 'pending_pos'),
            ('pos_lock_expires', '!=', False),
            ('pos_lock_expires', '<', now),
        ])
        for expired in expired_locks:
            expired.write({
                'state': _release_state(expired),
                'pos_session_id': False,
                'lock_token': False,
            })
        if expired_locks:
            _log.info("Released %d expired M-Pesa POS lock(s) before validate", len(expired_locks))

        phone_variants = self._phone_variants(norm_phone)

        txns = Txn.search([
            ('sender_phone', 'in', phone_variants),
            ('state', 'in', AVAILABLE_TRANSACTION_STATES),
            ('amount_remaining', '>', 0),
        ], order='transaction_date desc')
        own_locked_txns = Txn.search([
            ('sender_phone', 'in', phone_variants),
            ('state', '=', 'pending_pos'),
            ('pos_session_id', '=', pos_session_id),
            ('amount_remaining', '>', 0),
            '|',
            ('pos_lock_expires', '=', False),
            ('pos_lock_expires', '>=', now),
        ], order='transaction_date desc')
        txns |= own_locked_txns
        txns = txns.sorted('transaction_date', reverse=True)

        if not txns:
            _log.info(
                "POS validate no match: phone=%s normalized=%s amount=%.2f "
                "variants=%s states=%s",
                phone, norm_phone, order_amount, phone_variants, AVAILABLE_TRANSACTION_STATES,
            )
            return {'status': 'not_found', 'transactions': []}

        result = []
        for txn in txns:
            available_amount = txn.amount_remaining
            diff = available_amount - order_amount
            if abs(diff) <= tolerance:
                match_type = 'exact'
            elif diff > tolerance:
                match_type = 'overpayment'
            else:
                match_type = 'underpayment'

            result.append({
                'id':               txn.id,
                'mpesa_ref':        txn.mpesa_ref,
                'amount':           available_amount,
                'original_amount':  txn.amount,
                'amount_used':      txn.amount_used,
                'amount_remaining': available_amount,
                'sender_name':      txn.sender_name,
                'sender_phone':     txn.display_phone,
                'transaction_date': txn.transaction_date.isoformat() if txn.transaction_date else '',
                'match_type':       match_type,
                'difference':       round(diff, 2),
            })

        _log.info(
            "POS validate found %d match(es): phone=%s refs=%s",
            len(result), norm_phone, ','.join(txns.mapped('mpesa_ref')),
        )
        return {'status': 'found', 'transactions': result}

    # ------------------------------------------------------------------
    # LOCK — reserve transaction for this POS session
    # ------------------------------------------------------------------

    @http.route('/pos/mpesa/lock', type='json', auth='user', methods=['POST'])
    def lock(self, transaction_id: int, pos_session_id: int, **_kw):
        """
        SELECT FOR UPDATE ensures two cashiers cannot lock the same transaction.
        Returns a single-use lock_token that must be provided at confirm time.
        """
        Txn = request.env['mpesa.transaction'].sudo()

        # Use FOR UPDATE to prevent race condition between two tills
        request.env.cr.execute(
            """
            SELECT state, pos_session_id, pos_lock_expires
              FROM mpesa_transaction
             WHERE id = %s
               FOR UPDATE NOWAIT
            """,
            (transaction_id,)
        )
        row = request.env.cr.fetchone()
        if not row:
            return {'success': False, 'error': 'Transaction no longer available'}

        txn = Txn.browse(transaction_id)
        state, locked_session_id, lock_expires = row
        if state == 'pending_pos':
            if locked_session_id != pos_session_id:
                return {'success': False, 'error': 'Transaction locked by another till'}
            if lock_expires and datetime.utcnow() > lock_expires:
                txn.write({
                    'state': _release_state(txn),
                    'pos_session_id': False,
                    'lock_token': False,
                })
                state = txn.state
            else:
                _log.info(
                    "Reusing own POS lock txn id=%d session=%d cashier=%d",
                    transaction_id, pos_session_id, request.env.uid,
                )
        if state not in AVAILABLE_TRANSACTION_STATES and state != 'pending_pos':
            return {'success': False, 'error': 'Transaction no longer available'}

        lock_token = str(uuid.uuid4())
        lock_mins = 5
        method = self._get_session_mpesa_method(pos_session_id)
        if method:
            lock_mins = method.mpesa_lock_minutes

        txn.write({
            'state':             'pending_pos',
            'pos_session_id':    pos_session_id,
            'pos_lock_expires':  datetime.utcnow() + timedelta(minutes=lock_mins),
            'locked_by_cashier': request.env.uid,
            'lock_token':        lock_token,
        })

        _log.info(
            "Locked txn id=%d session=%d cashier=%d token=%s",
            transaction_id, pos_session_id, request.env.uid, lock_token[:8],
        )
        return {
            'success':    True,
            'lock_token': lock_token,
            'expires_in': lock_mins * 60,
        }

    # ------------------------------------------------------------------
    # CONFIRM — finalise payment
    # ------------------------------------------------------------------

    @http.route('/pos/mpesa/confirm', type='json', auth='user', methods=['POST'])
    def confirm(
        self,
        transaction_id: int,
        lock_token: str,
        pos_order_id: int = 0,
        applied_amount: float = 0.0,
        **_kw
    ):
        """
        Validates lock_token, consumes the available M-Pesa balance, and keeps
        the amount reserved until the POS order sync links the payment line.
        """
        Txn = request.env['mpesa.transaction'].sudo()
        request.env.cr.execute(
            """
            SELECT id
              FROM mpesa_transaction
             WHERE id = %s
               FOR UPDATE NOWAIT
            """,
            (transaction_id,)
        )
        if not request.env.cr.fetchone():
            return {'success': False, 'error': 'Transaction not found'}

        txn = Txn.browse(transaction_id)

        if not txn.exists():
            return {'success': False, 'error': 'Transaction not found'}
        if txn.state != 'pending_pos':
            return {'success': False, 'error': f'Transaction state is {txn.state}'}
        if txn.lock_token != lock_token:
            return {'success': False, 'error': 'Invalid lock token'}
        if txn.pos_lock_expires and datetime.utcnow() > txn.pos_lock_expires:
            txn.write({'state': _release_state(txn), 'pos_session_id': False, 'lock_token': False})
            return {'success': False, 'error': 'Lock expired — please re-validate'}

        expiry_validator = getattr(
            request.env['hr.employee'].sudo(),
            'sbl_validate_expired_mpesa_sms_confirmation',
            None,
        )
        if expiry_validator:
            expiry_result = expiry_validator(
                txn.id,
                txn.pos_session_id.id,
                _kw.get('expiry_authorization') or {},
                request.session.get('sbl_mpesa_expiry_authorizations') or {},
            )
            if not expiry_result.get('approved'):
                _log.warning(
                    "Blocked expired M-Pesa confirm txn id=%d ref=%s session=%s reason=%s",
                    txn.id,
                    txn.mpesa_ref,
                    txn.pos_session_id.id,
                    expiry_result.get('message'),
                )
                return {
                    'success': False,
                    'expired': True,
                    'error': expiry_result.get('message') or 'Expired M-Pesa SMS requires authorization.',
                    'expiry_status': expiry_result.get('status') or {},
                }

        remaining_before = txn.amount_remaining or 0.0
        applied = min(float(applied_amount or remaining_before), remaining_before)
        if applied <= 0:
            return {'success': False, 'error': 'No M-Pesa balance remaining'}

        amount_used = (txn.amount_used or 0.0) + applied
        remaining_after = max(remaining_before - applied, 0.0)
        txn.write({
            'amount_used': amount_used,
            'pos_reserved_amount': (txn.pos_reserved_amount or 0.0) + applied,
            'state': 'partial_pos' if remaining_after > 0.01 else 'reconciled_pos',
            'pos_lock_expires': False,
            'lock_token': False,
        })

        _log.info(
            "Confirmed POS-held txn id=%d ref=%s applied=%.2f remaining=%.2f",
            txn.id, txn.mpesa_ref, applied, remaining_after,
        )
        return {
            'success': True,
            'transaction_id': txn.id,
            'mpesa_ref': txn.mpesa_ref,
            'applied_amount': applied,
            'remaining_amount': remaining_before - applied,
        }

    # ------------------------------------------------------------------
    # RELEASE — cashier cancelled
    # ------------------------------------------------------------------

    @http.route('/pos/mpesa/release', type='json', auth='user', methods=['POST'])
    def release(
        self,
        transaction_id: int = 0,
        pos_session_id: int = 0,
        mpesa_ref: str = '',
        release_amount: float = 0.0,
        **_kw
    ):
        Txn = request.env['mpesa.transaction'].sudo()
        txn = Txn.browse(transaction_id) if transaction_id else Txn.search(
            [('mpesa_ref', '=', mpesa_ref)], limit=1
        )
        if txn.exists() and txn.state == 'pending_pos' and txn.pos_session_id.id == pos_session_id:
            txn.write({
                'state': _release_state(txn),
                'pos_session_id': False,
                'pos_lock_expires': False,
                'lock_token': False,
            })
            _log.info("Released txn id=%d by session=%d", txn.id, pos_session_id)
        elif (
            txn.exists()
            and txn.pos_session_id.id == pos_session_id
            and txn.pos_reserved_amount
        ):
            request.env.cr.execute(
                """
                SELECT id
                  FROM mpesa_transaction
                 WHERE id = %s
                   FOR UPDATE NOWAIT
                """,
                (txn.id,)
            )
            reserved = txn.pos_reserved_amount or 0.0
            rollback = min(float(release_amount or reserved), reserved)
            reserved_after = max(reserved - rollback, 0.0)
            amount_used = max((txn.amount_used or 0.0) - rollback, 0.0)
            remaining_after = max(
                (txn.amount or 0.0)
                - amount_used
                - (txn.amount_refunded or 0.0)
                - (txn.amount_reversed or 0.0)
                - (txn.amount_frozen or 0.0),
                0.0,
            )
            if amount_used > 0.01:
                release_state = 'partial_pos' if remaining_after > 0.01 else 'reconciled_pos'
            elif txn.amount_refunded and remaining_after > 0.01:
                release_state = 'partially_refunded'
            else:
                release_state = 'new' if txn.partner_id else 'unmatched'
            txn.write({
                'amount_used': amount_used,
                'pos_reserved_amount': reserved_after,
                'state': release_state,
                'pos_session_id': txn.pos_session_id.id if reserved_after > 0.01 else False,
                'pos_lock_expires': False,
                'lock_token': False,
            })
            _log.info(
                "Rolled back confirmed POS hold txn id=%d ref=%s amount=%.2f by session=%d",
                txn.id, txn.mpesa_ref, rollback, pos_session_id,
            )
        return {'success': True}

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        import re
        digits = re.sub(r'\D', '', phone or '')
        if len(digits) == 12 and digits.startswith('254'):
            return digits
        if len(digits) == 10 and digits.startswith('0'):
            return '254' + digits[1:]
        if len(digits) == 9 and digits[0] in ('7', '1'):
            return '254' + digits
        return ''

    @staticmethod
    def _phone_variants(phone_254: str):
        if not phone_254:
            return []
        variants = [phone_254]
        if len(phone_254) == 12 and phone_254.startswith('254'):
            variants.append('0' + phone_254[3:])
            variants.append(phone_254[3:])
        return list(dict.fromkeys(variants))

    @staticmethod
    def _get_session_mpesa_method(pos_session_id: int):
        session = request.env['pos.session'].sudo().browse(pos_session_id)
        if not session or not session.config_id:
            return request.env['pos.payment.method'].sudo().browse()
        return session.config_id.payment_method_ids.filtered('is_mpesa')[:1]
