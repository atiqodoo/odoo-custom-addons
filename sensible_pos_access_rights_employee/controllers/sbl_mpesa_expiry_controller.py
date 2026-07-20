import logging
import uuid

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SblMpesaExpiryController(http.Controller):

    @http.route('/pos/mpesa/expiry/check', type='json', auth='user', methods=['POST'])
    def check_expiry(self, transaction_id, pos_session_id, **_kw):
        txn = request.env['mpesa.transaction'].sudo().browse(int(transaction_id or 0)).exists()
        if not txn:
            return {
                'expired': True,
                'reason': 'missing_transaction',
                'message': 'M-Pesa transaction was not found.',
            }
        status = txn.sbl_mpesa_pos_expiry_status(int(pos_session_id or 0))
        _logger.debug(
            "POS M-Pesa expiry check: txn=%s session=%s status=%s",
            txn.mpesa_ref, pos_session_id, status,
        )
        return status

    @http.route('/pos/mpesa/expiry/authorize', type='json', auth='user', methods=['POST'])
    def authorize_expiry(
        self,
        pin,
        transaction_id,
        pos_session_id,
        cashier_id=False,
        config_id=False,
        order_reference=False,
        **_kw
    ):
        result = request.env['hr.employee'].sudo().sbl_validate_expired_mpesa_sms_pin(
            pin,
            int(transaction_id or 0),
            int(pos_session_id or 0),
            cashier_id=int(cashier_id or 0) or False,
            config_id=int(config_id or 0) or False,
            order_reference=order_reference or False,
        )
        if result.get('approved') and result.get('requires_override'):
            token = str(uuid.uuid4())
            key = '%s:%s' % (int(transaction_id or 0), int(pos_session_id or 0))
            authorizations = dict(request.session.get('sbl_mpesa_expiry_authorizations') or {})
            authorizations[key] = {
                'token': token,
                'employee_id': result.get('employee_id') or False,
            }
            request.session['sbl_mpesa_expiry_authorizations'] = authorizations
            result['token'] = token
            _logger.info(
                "Stored expired M-Pesa SMS override token: txn=%s session=%s employee=%s",
                transaction_id, pos_session_id, result.get('employee_id'),
            )
        return result
