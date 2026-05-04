# -*- coding: utf-8 -*-
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = 'pos.session'

    # -------------------------------------------------------------------------
    # Product loader — expose standard_price (AVCO cost) to the POS frontend
    # -------------------------------------------------------------------------

    def _loader_params_product_product(self):
        result = super()._loader_params_product_product()
        fields = result['search_params']['fields']
        if 'standard_price' not in fields:
            fields.append('standard_price')
            _logger.info(
                "pos_block_price_cost: 'standard_price' appended to product loader "
                "fields for session %s", self.id
            )
        return result

    # -------------------------------------------------------------------------
    # Manager PIN validation — called via ORM RPC from the POS frontend
    # -------------------------------------------------------------------------

    def validate_manager_pin(self, pin):
        """
        Validates whether the supplied PIN belongs to an employee with
        the 'Point of Sale / Administrator' (group_pos_manager) role.

        Called from the frontend ManagerPinDialog component via:
            this.orm.call('pos.session', 'validate_manager_pin', [[sessionId], pin])

        Returns:
            dict — {'valid': True,  'employee_name': str}
                 — {'valid': False, 'reason': str}

        Reason codes:
            'no_pin'       — empty PIN received
            'invalid_pin'  — no employee found with that PIN
            'not_manager'  — employee found but lacks POS Manager group
            'config_error' — XML ref for group not found (misconfigured DB)
        """
        self.ensure_one()
        _logger.info(
            "pos_block_price_cost: validate_manager_pin called for session %s", self.id
        )

        # ── Guard: empty PIN ──────────────────────────────────────────────────
        if not pin:
            _logger.warning("pos_block_price_cost: Empty PIN received — rejecting")
            return {'valid': False, 'reason': 'no_pin'}

        # ── Look up employee by PIN ───────────────────────────────────────────
        employee = self.env['hr.employee'].sudo().search(
            [('pos_security_pin', '=', str(pin).strip())],
            limit=1
        )
        if not employee:
            _logger.warning(
                "pos_block_price_cost: No hr.employee found for supplied PIN"
            )
            return {'valid': False, 'reason': 'invalid_pin'}

        # ── Resolve POS Manager group ─────────────────────────────────────────
        manager_group = self.env.ref(
            'point_of_sale.group_pos_manager', raise_if_not_found=False
        )
        if not manager_group:
            _logger.error(
                "pos_block_price_cost: 'point_of_sale.group_pos_manager' XML ref "
                "not found — cannot validate manager role"
            )
            return {'valid': False, 'reason': 'config_error'}

        # ── Check manager role ────────────────────────────────────────────────
        if employee.user_id and employee.user_id in manager_group.users:
            _logger.info(
                "pos_block_price_cost: Manager override GRANTED by employee '%s' (id=%s)",
                employee.name, employee.id
            )
            return {'valid': True, 'employee_name': employee.name}

        _logger.warning(
            "pos_block_price_cost: Employee '%s' (id=%s) found but is NOT in "
            "group_pos_manager — override DENIED",
            employee.name, employee.id
        )
        return {'valid': False, 'reason': 'not_manager'}