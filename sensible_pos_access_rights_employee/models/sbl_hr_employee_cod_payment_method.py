# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployeeBase(models.AbstractModel):
    _inherit = 'hr.employee.base'

    sbl_cod_payment_method_ids = fields.Many2many(
        'pos.payment.method',
        'sbl_hr_employee_cod_payment_method_rel',
        'employee_id',
        'payment_method_id',
        string='COD Payment Methods Requiring Authorization',
        help='COD collection payment methods that require supervisor authorization for this employee.',
    )


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if 'sbl_cod_payment_method_ids' not in fields_list:
            fields_list.append('sbl_cod_payment_method_ids')
        return fields_list

    def _sbl_is_restricted_for_authorized_action(
        self,
        employee,
        action_key,
        authorization_context=False,
    ):
        if action_key == 'cod_payment_method':
            payment_method_id = (
                authorization_context
                and authorization_context.get('payment_method_id')
            )
            return bool(
                payment_method_id
                and employee.sbl_cod_payment_method_ids.filtered(
                    lambda method: method.id == payment_method_id
                )
            )
        return super()._sbl_is_restricted_for_authorized_action(
            employee,
            action_key,
            authorization_context,
        )
