# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging
import time

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

    def _pc_override_secret(self):
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        return (secret or self.env.cr.dbname).encode()

    def _pc_make_below_cost_override_token(self, order_uuid, employee, lines_data):
        self.ensure_one()
        signature = self._pc_below_cost_signature(lines_data, source="manager_pin_override")
        payload = {
            "employee_id": employee.id,
            "issued_at": int(time.time()),
            "order_uuid": order_uuid or "",
            "session_id": self.id,
            "signature": signature,
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hmac.new(
            self._pc_override_secret(),
            payload_json.encode(),
            hashlib.sha256,
        ).hexdigest()
        return "%s.%s" % (payload_json, digest)

    def validate_manager_pin(self, pin, override_context=None):
        """
        Validates whether the supplied PIN belongs to an employee with
        the 'Point of Sale / Administrator' (group_pos_manager) role.

        Called from the frontend ManagerPinDialog component via:
            this.orm.call('pos.session', 'validate_manager_pin', [[sessionId], pin, context])

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
            result = {
                'valid': True,
                'employee_id': employee.id,
                'employee_name': employee.name,
            }
            override_context = override_context or {}
            if override_context.get("type") == "below_cost_order":
                lines_data = override_context.get("lines") or []
                result["below_cost_override_token"] = self._pc_make_below_cost_override_token(
                    override_context.get("order_uuid"),
                    employee,
                    lines_data,
                )
                _logger.info(
                    "[POS_BLOCK_PRICE_COST][MANAGER_OVERRIDE_TOKEN][END] "
                    "session_id=%s employee_id=%s order_uuid=%s line_count=%s",
                    self.id,
                    employee.id,
                    override_context.get("order_uuid"),
                    len(lines_data),
                )
            return result

        _logger.warning(
            "pos_block_price_cost: Employee '%s' (id=%s) found but is NOT in "
            "group_pos_manager — override DENIED",
            employee.name, employee.id
        )
        return {'valid': False, 'reason': 'not_manager'}
