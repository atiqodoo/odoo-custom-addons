# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class HrEmployeeAppGate(models.Model):
    _inherit = 'hr.employee'

    sbl_blocked_app_ids = fields.Many2many(
        'sbl.app.gate.config',
        'sbl_hr_employee_blocked_app_rel',
        'employee_id',
        'app_id',
        string='Blocked Apps',
        help=(
            'Apps this employee is BLOCKED from. '
            'All gated apps always require a PIN — but if the app appears here, '
            'the employee will be denied even with a valid PIN.'
        ),
    )

    # ------------------------------------------------------------------ #
    # RPC: fetch all globally-gated app XML IDs (called on page load)
    # ------------------------------------------------------------------ #

    @api.model
    def sbl_get_app_gate_config(self):
        """Return ALL active gated-app XML IDs.

        Every app in sbl.app.gate.config is gated for EVERYONE — any click
        will trigger the PIN dialog regardless of which Odoo user is logged in.
        The per-employee sbl_blocked_app_ids decides whether access is granted
        or denied after the employee identifies themselves with their PIN.
        """
        gated = self.env['sbl.app.gate.config'].sudo().search([('active', '=', True)])
        return {'blocked_apps': gated.mapped('xmlid')}

    # ------------------------------------------------------------------ #
    # RPC: identify employee by PIN and check app authorisation
    # ------------------------------------------------------------------ #

    @api.model
    def sbl_app_gate_login(self, pin, app_xmlid, app_name=False):
        """Authenticate any employee by PIN and check if they can open the app.

        The employee is identified purely by their PIN — not by the Odoo
        session user. After identification the server checks whether the
        requested app appears in the employee's blocked list.

        Returns a dict:
            success (bool)
            message (str)   — human-readable, shown in the PIN dialog
            employee_name   — present on both success and blocked outcomes
            blocked (bool)  — True only when the employee is identified but blocked
        """
        if not pin:
            return {'success': False, 'message': _('Please enter your PIN.')}

        employee = self.sudo().search(
            [('pin', '=', str(pin)), ('active', '=', True)],
            limit=1,
        )

        log_vals = {
            'app_xmlid': app_xmlid or '',
            'app_name': app_name or app_xmlid or '',
            'user_id': self.env.uid,
            'employee_id': employee.id if employee else False,
        }

        if not employee:
            reason = _('Invalid PIN.')
            log_vals.update(status='failed', failure_reason=reason)
            self.env['sbl.app.gate.log'].sudo().create(log_vals)
            _logger.warning("App gate denied (invalid PIN): app=%s", app_xmlid)
            return {'success': False, 'message': _('Invalid PIN. Access denied.')}

        # Check whether this specific app is blocked for the identified employee
        app_config = self.env['sbl.app.gate.config'].sudo().search(
            [('xmlid', '=', app_xmlid), ('active', '=', True)],
            limit=1,
        )
        if app_config and app_config.id in employee.sbl_blocked_app_ids.ids:
            reason = _(
                'Employee %s is not authorized to access %s.'
            ) % (employee.name, app_name or app_xmlid)
            log_vals.update(status='failed', failure_reason=reason)
            self.env['sbl.app.gate.log'].sudo().create(log_vals)
            _logger.warning(
                "App gate BLOCKED: employee=%s (%s) app=%s",
                employee.name, employee.id, app_xmlid,
            )
            return {
                'success': False,
                'message': reason,
                'employee_name': employee.name,
                'blocked': True,
            }

        log_vals.update(status='success', failure_reason=False)
        self.env['sbl.app.gate.log'].sudo().create(log_vals)
        _logger.info(
            "App gate granted: employee=%s (%s) app=%s",
            employee.name, employee.id, app_xmlid,
        )
        return {
            'success': True,
            'message': _('Welcome, %s! Access granted.') % employee.name,
            'employee_name': employee.name,
        }
