# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


SBL_ACTION_RESTRICTION_FIELDS = {
    'new_order': 'sbl_hide_pos_new_order_button',
    'delete_order': 'sbl_hide_pos_delete_order_button',
    'select_customer': 'sbl_hide_pos_customer_selection_button',
    'create_customer': 'sbl_hide_pos_create_customer_button',
    'edit_customer': 'sbl_hide_pos_edit_customer_button',
    'actions_menu': 'sbl_hide_pos_actions_button',
    'payment': 'sbl_hide_pos_payment',
    'numpad': 'sbl_hide_pos_numpad',
    'numpad_plus_minus': 'sbl_disable_pos_numpad_plus_minus',
    'qty': 'sbl_disable_pos_qty',
    'discount': 'sbl_disable_pos_discount_button',
    'global_discount': 'sbl_require_auth_global_discount',
    'cod_dispatch': 'sbl_require_auth_cod_dispatch',
    'cod_pay_all': 'sbl_require_auth_cod_pay_all',
    'cod_pay_partial': 'sbl_require_auth_cod_pay_partial',
    'cod_return_all': 'sbl_require_auth_cod_return_all',
    'cod_return_partial': 'sbl_require_auth_cod_return_partial',
    'cod_discount': 'sbl_require_auth_cod_discount',
    'change_price': 'sbl_disable_pos_change_price',
    'product_info': 'sbl_hide_pos_action_product_info',
    'product_info_financials': 'sbl_hide_pos_finance_from_product_info',
    'payment_customer': 'sbl_hide_pos_payment_customer_button',
    'payment_invoice': 'sbl_hide_pos_payment_invoice_button',
    'payment_validate': 'sbl_hide_pos_payment_validate_button',
    'payment_ship_later': 'sbl_hide_pos_payment_ship_later_button',
    'payment_tip': 'sbl_hide_pos_tip_button',
    'open_cashbox': 'sbl_hide_pos_open_cashbox_button',
    'payment_method': 'sbl_disabled_payment_method_ids',
    'deposit_settle_payment_method': 'sbl_deposit_settle_payment_method_ids',
    'install_app': 'sbl_hide_pos_install_app',
    'orders_menu': 'sbl_hide_pos_orders_menu',
    'backend_menu': 'sbl_hide_pos_backend_menu',
    'close_register': 'sbl_hide_pos_close_register',
    'daily_sale': 'sbl_hide_pos_daily_sale',
    'clear_cache': 'sbl_hide_pos_clear_cache',
    'debug_window': 'sbl_hide_pos_debug_window',
    'cash_in_out': 'sbl_hide_pos_cash_in_out',
    'general_note': 'sbl_hide_pos_action_general_note',
    'customer_note': 'sbl_hide_pos_action_customer_note',
    'pricelist': 'sbl_hide_pos_action_pricelist',
    'refund': 'sbl_hide_pos_action_refund',
    'reward': 'sbl_hide_pos_action_reward',
    'fiscal_position': 'sbl_hide_pos_action_fiscal_position',
    'cancel_order': 'sbl_hide_pos_action_cancel_order',
    'team_kubwa_open': 'sbl_require_auth_team_kubwa_open',
    'team_kubwa_create_customer': 'sbl_require_auth_team_kubwa_create_customer',
    'team_kubwa_check_eligibility': 'sbl_require_auth_team_kubwa_check_eligibility',
    'team_kubwa_save_draft': 'sbl_require_auth_team_kubwa_save_draft',
    'team_kubwa_open_draft': 'sbl_require_auth_team_kubwa_open_draft',
    'team_kubwa_continue_otp': 'sbl_require_auth_team_kubwa_continue_otp',
    'team_kubwa_mark_otp': 'sbl_require_auth_team_kubwa_mark_otp',
    'team_kubwa_continue_pay': 'sbl_require_auth_team_kubwa_continue_pay',
    'team_kubwa_manager_override': 'sbl_require_auth_team_kubwa_manager_override',
    'team_kubwa_pay_post': 'sbl_require_auth_team_kubwa_pay_post',
}


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
        authorization_context=False,
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

        supervisor = employees.filtered(
            lambda emp: (
                emp.id != cashier_id
                and self._sbl_is_pos_supervisor(emp, config)
                and not self._sbl_is_restricted_for_authorized_action(
                    emp,
                    action_key,
                    authorization_context,
                )
            )
        )[:1]
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
                _('Invalid supervisor PIN, self-authorization is not allowed, the employee is not a POS supervisor, or the supervisor is restricted for this action.'),
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
    def _sbl_is_restricted_for_authorized_action(
        self,
        employee,
        action_key,
        authorization_context=False,
    ):
        field_name = SBL_ACTION_RESTRICTION_FIELDS.get(action_key)
        if not employee or not field_name:
            return False
        if action_key in ('payment_method', 'deposit_settle_payment_method'):
            payment_method_id = (
                authorization_context
                and authorization_context.get('payment_method_id')
            )
            restricted_methods = employee[field_name]
            return bool(
                payment_method_id
                and restricted_methods.filtered(lambda method: method.id == payment_method_id)
            )
        return bool(employee[field_name])

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
        log = self.env['sbl.pos.authorization.log'].sbl_log_authorization({
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
            'authorization_log_id': log.id,
        }
