# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class SblPosAuthorizationLog(models.Model):
    _name = 'sbl.pos.authorization.log'
    _description = 'POS Supervisor Authorization Log'
    _order = 'create_date desc, id desc'

    action_key = fields.Char(required=True, index=True)
    action_label = fields.Char()
    status = fields.Selection(
        [('approved', 'Approved'), ('denied', 'Denied'), ('error', 'Error')],
        required=True,
        default='denied',
        index=True,
    )
    cashier_id = fields.Many2one('hr.employee', index=True, ondelete='set null')
    supervisor_id = fields.Many2one('hr.employee', index=True, ondelete='set null')
    pos_config_id = fields.Many2one('pos.config', index=True, ondelete='set null')
    pos_session_id = fields.Many2one('pos.session', index=True, ondelete='set null')
    order_reference = fields.Char(index=True)
    message = fields.Char()

    @api.model
    def sbl_log_authorization(self, vals):
        safe_vals = {
            'action_key': vals.get('action_key') or 'unknown',
            'action_label': vals.get('action_label'),
            'status': vals.get('status') or 'denied',
            'cashier_id': vals.get('cashier_id') or False,
            'supervisor_id': vals.get('supervisor_id') or False,
            'pos_config_id': vals.get('pos_config_id') or False,
            'pos_session_id': vals.get('pos_session_id') or False,
            'order_reference': vals.get('order_reference'),
            'message': vals.get('message'),
        }
        record = self.sudo().create(safe_vals)
        _logger.info(
            "POS authorization %s: action=%s cashier=%s supervisor=%s config=%s session=%s order=%s message=%s",
            safe_vals['status'],
            safe_vals['action_key'],
            safe_vals['cashier_id'],
            safe_vals['supervisor_id'],
            safe_vals['pos_config_id'],
            safe_vals['pos_session_id'],
            safe_vals['order_reference'],
            safe_vals['message'],
        )
        return record


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def sbl_validate_pos_supervisor_authorization(
        self,
        pin,
        action_key,
        cashier_id=False,
        config_id=False,
        session_id=False,
        order_reference=False,
        action_label=False,
    ):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            _logger.warning(
                "POS authorization denied: user %s is not a POS user for action=%s",
                self.env.user.id,
                action_key,
            )
            return self._sbl_authorization_result(
                False,
                _('Only POS users can request supervisor authorization.'),
                action_key,
                action_label,
                cashier_id,
                False,
                config_id,
                session_id,
                order_reference,
                'denied',
            )

        if not pin:
            return self._sbl_authorization_result(
                False,
                _('Supervisor PIN is required.'),
                action_key,
                action_label,
                cashier_id,
                False,
                config_id,
                session_id,
                order_reference,
                'denied',
            )

        config = self.env['pos.config'].sudo().browse(config_id).exists() if config_id else False
        employees = self.sudo().search([('pin', '=', pin)])
        if config:
            visible_domain = config._employee_domain(config.current_user_id.id)
            visible_employees = self.sudo().search(visible_domain)
            employees &= visible_employees

        supervisor = employees.filtered(lambda emp: self._sbl_is_pos_supervisor(emp, config))[:1]
        if not supervisor:
            _logger.warning(
                "POS authorization denied: invalid supervisor PIN/action=%s cashier=%s config=%s session=%s",
                action_key,
                cashier_id,
                config_id,
                session_id,
            )
            return self._sbl_authorization_result(
                False,
                _('Invalid supervisor PIN or the employee is not a POS supervisor.'),
                action_key,
                action_label,
                cashier_id,
                False,
                config_id,
                session_id,
                order_reference,
                'denied',
            )

        _logger.info(
            "POS authorization approved: action=%s cashier=%s supervisor=%s config=%s session=%s",
            action_key,
            cashier_id,
            supervisor.id,
            config_id,
            session_id,
        )
        return self._sbl_authorization_result(
            True,
            _('Authorization approved.'),
            action_key,
            action_label,
            cashier_id,
            supervisor.id,
            config_id,
            session_id,
            order_reference,
            'approved',
        )

    @api.model
    def _sbl_is_pos_supervisor(self, employee, config=False):
        if not employee:
            return False
        if employee.user_id and employee.user_id.has_group('point_of_sale.group_pos_manager'):
            return True
        if config and employee in config.advanced_employee_ids:
            return True
        return False

    @api.model
    def _sbl_authorization_result(
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
        status,
    ):
        self.env['sbl.pos.authorization.log'].sbl_log_authorization({
            'action_key': action_key,
            'action_label': action_label,
            'status': status,
            'cashier_id': cashier_id,
            'supervisor_id': supervisor_id,
            'pos_config_id': config_id,
            'pos_session_id': session_id,
            'order_reference': order_reference,
            'message': message,
        })
        return {
            'approved': approved,
            'message': message,
            'supervisor_id': supervisor_id,
        }
