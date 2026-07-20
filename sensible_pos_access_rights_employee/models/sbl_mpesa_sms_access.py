# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
from odoo import _, api, models
from odoo.exceptions import AccessError
from odoo.http import request


def _sbl_mpesa_sms_session():
    try:
        return request.session
    except RuntimeError:
        return {}


def _sbl_check_mpesa_sms_app_access(env):
    session = _sbl_mpesa_sms_session()
    employee_id = session.get('sbl_mpesa_sms_employee_id')
    if not employee_id:
        return

    employee = env['hr.employee'].sudo().browse(employee_id).exists()
    if employee and employee.sbl_block_mpesa_sms_app and not session.get('sbl_mpesa_sms_supervisor_ok'):
        raise AccessError(_(
            'Supervisor authorization is required to open the M-Pesa SMS app.'
        ))


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def sbl_mpesa_sms_has_session_access(self):
        session = _sbl_mpesa_sms_session()
        employee_id = session.get('sbl_mpesa_sms_employee_id')
        if not employee_id:
            return {'authorized': False}

        employee = self.sudo().browse(employee_id).exists()
        if not employee:
            return {'authorized': False}

        return {
            'authorized': bool(
                not employee.sbl_block_mpesa_sms_app
                or session.get('sbl_mpesa_sms_supervisor_ok')
            ),
            'employee_id': employee.id,
            'employee_name': employee.name,
        }

    @api.model
    def sbl_mpesa_sms_employee_login(self, pin):
        employee = self.sudo().search([('pin', '=', pin)], limit=1)
        if not employee:
            return {
                'success': False,
                'message': _('Invalid employee PIN.'),
            }

        session = _sbl_mpesa_sms_session()
        session['sbl_mpesa_sms_employee_id'] = employee.id
        session['sbl_mpesa_sms_supervisor_ok'] = False
        return {
            'success': True,
            'employee_id': employee.id,
            'employee_name': employee.name,
            'blocked': bool(employee.sbl_block_mpesa_sms_app),
        }

    @api.model
    def sbl_mpesa_sms_supervisor_authorize(self, pin, employee_id=False):
        employee = self.sudo().browse(employee_id).exists() if employee_id else False
        supervisor = self.sudo().search([('pin', '=', pin)], limit=1)
        if not supervisor or supervisor == employee or not self._sbl_is_pos_supervisor(supervisor):
            self.env['sbl.pos.authorization.log'].sbl_log_authorization({
                'action_key': 'mpesa_sms_app',
                'action_label': 'M-Pesa SMS App',
                'status': 'denied',
                'cashier_id': employee.id if employee else False,
                'supervisor_id': supervisor.id if supervisor else False,
                'message': _('Invalid supervisor PIN or self-authorization is not allowed.'),
            })
            return {
                'approved': False,
                'message': _('Invalid supervisor PIN or self-authorization is not allowed.'),
            }

        session = _sbl_mpesa_sms_session()
        session['sbl_mpesa_sms_employee_id'] = employee.id if employee else False
        session['sbl_mpesa_sms_supervisor_ok'] = True
        self.env['sbl.pos.authorization.log'].sbl_log_authorization({
            'action_key': 'mpesa_sms_app',
            'action_label': 'M-Pesa SMS App',
            'status': 'approved',
            'cashier_id': employee.id if employee else False,
            'supervisor_id': supervisor.id,
            'message': _('Authorization approved.'),
        })
        return {
            'approved': True,
            'message': _('Authorization approved.'),
        }


class MpesaTransaction(models.Model):
    _inherit = 'mpesa.transaction'

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        _sbl_check_mpesa_sms_app_access(self.env)
        return super().web_search_read(domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)

    def web_read(self, specification):
        _sbl_check_mpesa_sms_app_access(self.env)
        return super().web_read(specification)


class MpesaSmsRawLog(models.Model):
    _inherit = 'mpesa.sms.raw.log'

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        _sbl_check_mpesa_sms_app_access(self.env)
        return super().web_search_read(domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)

    def web_read(self, specification):
        _sbl_check_mpesa_sms_app_access(self.env)
        return super().web_read(specification)


class MpesaModemHealth(models.Model):
    _inherit = 'mpesa.modem.health'

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        _sbl_check_mpesa_sms_app_access(self.env)
        return super().web_search_read(domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)

    def web_read(self, specification):
        _sbl_check_mpesa_sms_app_access(self.env)
        return super().web_read(specification)
