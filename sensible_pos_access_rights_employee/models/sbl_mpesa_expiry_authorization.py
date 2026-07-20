# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _load_pos_data_fields(self, config_id):
        pos_fields = super()._load_pos_data_fields(config_id)
        return pos_fields + ['sbl_allow_expired_mpesa_sms_override']

    def sbl_validate_expired_mpesa_sms_pin(
        self,
        pin,
        transaction_id,
        pos_session_id,
        cashier_id=False,
        config_id=False,
        order_reference=False,
    ):
        Txn = self.env['mpesa.transaction'].sudo()
        txn = Txn.browse(transaction_id).exists()
        status = txn.sbl_mpesa_pos_expiry_status(pos_session_id) if txn else {
            'expired': True,
            'message': _('M-Pesa transaction was not found.'),
        }
        action_key = 'mpesa_expired_sms_override'
        action_label = 'Expired M-Pesa SMS Override'

        if not txn:
            return self._sbl_log_mpesa_expiry_result(
                False, status['message'], action_key, action_label,
                cashier_id, False, config_id, pos_session_id, order_reference,
            )
        if not status.get('expired'):
            _logger.info(
                "M-Pesa expiry override not required: txn=%s session=%s",
                txn.mpesa_ref, pos_session_id,
            )
            return {
                'approved': True,
                'requires_override': False,
                'message': status.get('message') or _('M-Pesa SMS is valid for this POS session.'),
                'employee_id': False,
                'status': status,
            }
        if not pin:
            return self._sbl_log_mpesa_expiry_result(
                False, _('Employee PIN is required for expired M-Pesa SMS payments.'),
                action_key, action_label, cashier_id, False, config_id,
                pos_session_id, order_reference, status=status,
            )

        employees = self.sudo().search([('pin', '=', str(pin)), ('active', '=', True)])
        config = self.env['pos.config'].sudo().browse(config_id).exists() if config_id else False
        if config:
            visible_domain = config._employee_domain(config.current_user_id.id)
            employees &= self.sudo().search(visible_domain)

        authorizer = employees.filtered('sbl_allow_expired_mpesa_sms_override')[:1]
        if not authorizer:
            _logger.warning(
                "Expired M-Pesa SMS override denied: txn=%s session=%s cashier=%s",
                txn.mpesa_ref, pos_session_id, cashier_id,
            )
            return self._sbl_log_mpesa_expiry_result(
                False,
                _('Invalid PIN or employee is not allowed to authorize expired M-Pesa SMS payments.'),
                action_key, action_label, cashier_id, False, config_id,
                pos_session_id, order_reference, status=status,
            )

        _logger.info(
            "Expired M-Pesa SMS override approved: txn=%s session=%s cashier=%s authorizer=%s",
            txn.mpesa_ref, pos_session_id, cashier_id, authorizer.id,
        )
        return self._sbl_log_mpesa_expiry_result(
            True,
            _('Expired M-Pesa SMS override approved.'),
            action_key,
            action_label,
            cashier_id,
            authorizer.id,
            config_id,
            pos_session_id,
            order_reference,
            status=status,
        )

    def sbl_validate_expired_mpesa_sms_confirmation(
        self,
        transaction_id,
        pos_session_id,
        authorization=False,
        session_authorizations=False,
    ):
        txn = self.env['mpesa.transaction'].sudo().browse(transaction_id).exists()
        if not txn:
            return {'approved': False, 'message': _('M-Pesa transaction was not found.')}
        status = txn.sbl_mpesa_pos_expiry_status(pos_session_id)
        if not status.get('expired'):
            return {'approved': True, 'status': status}

        authorization = authorization or {}
        session_authorizations = session_authorizations or {}
        key = '%s:%s' % (transaction_id, pos_session_id)
        stored = session_authorizations.get(key) or {}
        token = authorization.get('token')
        if token and stored.get('token') == token:
            _logger.info(
                "Expired M-Pesa SMS confirmation accepted with override: txn=%s session=%s employee=%s",
                txn.mpesa_ref, pos_session_id, stored.get('employee_id'),
            )
            return {'approved': True, 'status': status, 'employee_id': stored.get('employee_id')}

        _logger.warning(
            "Expired M-Pesa SMS confirmation blocked: txn=%s session=%s reason=%s",
            txn.mpesa_ref, pos_session_id, status.get('message'),
        )
        return {
            'approved': False,
            'expired': True,
            'status': status,
            'message': status.get('message') or _('This M-Pesa SMS is expired for the current POS session.'),
        }

    def _sbl_log_mpesa_expiry_result(
        self,
        approved,
        message,
        action_key,
        action_label,
        cashier_id,
        supervisor_id,
        config_id,
        session_id,
        order_reference,
        status=False,
    ):
        log_message = message
        if status:
            log_message = '%s %s' % (message, status.get('debug_summary') or '')
        self.env['sbl.pos.authorization.log'].sbl_log_authorization({
            'action_key': action_key,
            'action_label': action_label,
            'status': 'approved' if approved else 'denied',
            'cashier_id': cashier_id or False,
            'supervisor_id': supervisor_id or False,
            'pos_config_id': config_id or False,
            'pos_session_id': session_id or False,
            'order_reference': order_reference or False,
            'message': log_message,
        })
        return {
            'approved': approved,
            'requires_override': True,
            'message': message,
            'employee_id': supervisor_id or False,
            'status': status or {},
        }


class MpesaTransaction(models.Model):
    _inherit = 'mpesa.transaction'

    def sbl_mpesa_pos_expiry_status(self, pos_session_id):
        self.ensure_one()
        session = self.env['pos.session'].sudo().browse(pos_session_id).exists()
        if not session:
            return {
                'expired': True,
                'reason': 'missing_session',
                'message': _('The POS session was not found.'),
            }
        if not self.transaction_date:
            return {
                'expired': True,
                'reason': 'missing_transaction_time',
                'message': _('The M-Pesa SMS has no transaction timestamp.'),
            }

        txn_dt = fields.Datetime.to_datetime(self.transaction_date)
        start_dt = fields.Datetime.to_datetime(session.start_at or session.create_date)
        stop_dt = fields.Datetime.to_datetime(session.stop_at) if session.stop_at else fields.Datetime.now()
        expired = bool(txn_dt < start_dt or txn_dt > stop_dt)

        if txn_dt < start_dt:
            reason = 'before_session_open'
            message = _('This M-Pesa SMS was received before the current POS session opened.')
        elif txn_dt > stop_dt:
            reason = 'after_session_window'
            message = _('This M-Pesa SMS is outside the current POS session window.')
        else:
            reason = 'valid'
            message = _('This M-Pesa SMS is valid for the current POS session.')

        debug_summary = (
            'txn_ref=%s txn_time=%s session=%s start=%s stop=%s state=%s'
            % (self.mpesa_ref, txn_dt, session.name, start_dt, stop_dt, session.state)
        )
        _logger.debug("M-Pesa POS expiry status: %s expired=%s", debug_summary, expired)
        return {
            'expired': expired,
            'reason': reason,
            'message': message,
            'transaction_time': fields.Datetime.to_string(txn_dt),
            'session_start': fields.Datetime.to_string(start_dt),
            'session_stop': fields.Datetime.to_string(stop_dt),
            'session_state': session.state,
            'debug_summary': debug_summary,
        }
