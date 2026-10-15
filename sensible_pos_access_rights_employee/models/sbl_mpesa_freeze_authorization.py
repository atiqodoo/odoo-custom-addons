# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
import logging

from odoo import _, models

_logger = logging.getLogger(__name__)


class MpesaTransaction(models.Model):
    _inherit = 'mpesa.transaction'

    def _mpesa_authorize_freeze_pin(self, pin, operation):
        self.ensure_one()
        action_key = 'mpesa_sms_%s' % operation
        action_label = 'M-Pesa SMS %s' % ('Freeze' if operation == 'freeze' else 'Unfreeze')

        if operation not in ('freeze', 'unfreeze'):
            message = _('Unsupported M-Pesa freeze operation.')
            _logger.warning(
                "M-Pesa freeze authorization denied: unsupported operation=%s txn=%s user=%s",
                operation,
                self.mpesa_ref,
                self.env.uid,
            )
            self._mpesa_log_freeze_authorization(operation, False, message=message)
            return {'approved': False, 'message': message, 'employee_id': False}

        if not pin:
            message = _('Employee PIN is required.')
            self._mpesa_log_freeze_authorization(operation, False, message=message)
            return {'approved': False, 'message': message, 'employee_id': False}

        permission_field = (
            'sbl_allow_mpesa_sms_freeze'
            if operation == 'freeze'
            else 'sbl_allow_mpesa_sms_unfreeze'
        )
        employees = self.env['hr.employee'].sudo().search([
            ('pin', '=', str(pin)),
            ('active', '=', True),
        ])
        employee = employees.filtered(permission_field)[:1]

        if not employee:
            message = _('Invalid PIN or employee is not allowed to %(operation)s M-Pesa SMS balances.') % {
                'operation': operation,
            }
            _logger.warning(
                "M-Pesa %s authorization denied: txn_id=%s ref=%s user=%s matching_pin_count=%d",
                operation,
                self.id,
                self.mpesa_ref,
                self.env.uid,
                len(employees),
            )
            self._mpesa_log_freeze_authorization(operation, False, message=message)
            return {'approved': False, 'message': message, 'employee_id': False}

        message = _('M-Pesa SMS %(operation)s authorized by %(employee)s.') % {
            'operation': operation,
            'employee': employee.name,
        }
        _logger.info(
            "M-Pesa %s authorization approved: txn_id=%s ref=%s employee=%s user=%s",
            operation,
            self.id,
            self.mpesa_ref,
            employee.id,
            self.env.uid,
        )
        return {'approved': True, 'message': message, 'employee_id': employee.id}
