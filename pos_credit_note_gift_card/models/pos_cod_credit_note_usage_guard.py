# -*- coding: utf-8 -*-
"""Server-side guard for Credit Note Gift Card misuse in COD collection."""

import logging

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger("pos_credit_note_gift_card.cod_usage_guard")


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def _cnug_payment_method_id_from_command(self, command):
        if not isinstance(command, (list, tuple)) or len(command) < 3:
            return False
        vals = command[2] if isinstance(command[2], dict) else {}
        payment_method_id = vals.get("payment_method_id")
        if isinstance(payment_method_id, (list, tuple)):
            payment_method_id = payment_method_id[0]
        return int(payment_method_id or 0) or False

    @api.model
    def _cnug_ui_order_is_credit_note_return(self, order_data):
        for command in order_data.get("lines") or []:
            if not isinstance(command, (list, tuple)) or len(command) < 3:
                continue
            vals = command[2] if isinstance(command[2], dict) else {}
            qty = float(vals.get("qty") or 0.0)
            if qty < 0 or vals.get("refunded_orderline_id"):
                return True
        return False

    @api.model
    def _cnug_config_from_ui_order(self, order_data):
        config_id = order_data.get("config_id")
        if isinstance(config_id, (list, tuple)):
            config_id = config_id[0]
        if config_id:
            return self.env["pos.config"].browse(int(config_id))

        session_id = order_data.get("session_id")
        if isinstance(session_id, (list, tuple)):
            session_id = session_id[0]
        if session_id:
            session = self.env["pos.session"].browse(int(session_id))
            if session.exists():
                return session.config_id
        return self.env["pos.config"]

    @api.model
    def _cnug_block_ui_credit_note_misuse(self, order_data):
        config = self._cnug_config_from_ui_order(order_data)
        credit_note_method = config.credit_note_payment_method_id if config and config.exists() else False
        if not credit_note_method:
            return

        used_credit_note_method = any(
            self._cnug_payment_method_id_from_command(command) == credit_note_method.id
            for command in order_data.get("payment_ids") or []
        )
        if not used_credit_note_method:
            return

        if self._cnug_ui_order_is_credit_note_return(order_data):
            _logger.warning(
                "[POS sync guard] ALLOW credit-note payment method on return order | "
                "order=%s method=%s(%s)",
                order_data.get("name") or order_data.get("pos_reference"),
                credit_note_method.display_name,
                credit_note_method.id,
            )
            return

        message = _(
            "Credit Note Gift Card is only used in creating credit notes. "
            "It cannot be used for COD payment, customer deposit, due settlement, or a regular POS sale."
        )
        _logger.warning(
            "[POS sync guard] BLOCKED credit-note payment method outside credit-note return | "
            "order=%s config=%s method=%s(%s) lines=%s payments=%s",
            order_data.get("name") or order_data.get("pos_reference"),
            config.display_name,
            credit_note_method.display_name,
            credit_note_method.id,
            len(order_data.get("lines") or []),
            len(order_data.get("payment_ids") or []),
        )
        raise UserError(message)

    @api.model
    def sync_from_ui(self, orders):
        for order_data in orders or []:
            if isinstance(order_data, dict):
                self._cnug_block_ui_credit_note_misuse(order_data)
        return super().sync_from_ui(orders)

    @api.model
    def collect_cod_payment(
        self,
        order_id=None,
        payment_method_id=None,
        amount=None,
        session_id=False,
        action="payment",
        order_ref=None,
        return_lines=None,
        mpesa_ref=False,
        **kwargs
    ):
        payload = order_id if isinstance(order_id, dict) else kwargs
        guarded_payment_method_id = payment_method_id
        guarded_session_id = session_id

        if payload:
            guarded_payment_method_id = (
                payload.get("payment_method_id")
                or payload.get("paymentMethodId")
                or guarded_payment_method_id
            )
            guarded_session_id = (
                payload.get("session_id")
                or payload.get("sessionId")
                or guarded_session_id
            )

        if guarded_payment_method_id:
            payment_method = self.env["pos.payment.method"].browse(int(guarded_payment_method_id))
            session = (
                self.env["pos.session"].browse(int(guarded_session_id))
                if guarded_session_id
                else self.env["pos.session"]
            )
            config = session.config_id if session and session.exists() else False
            credit_note_method = config.credit_note_payment_method_id if config else False

            _logger.warning(
                "[COD guard] collect_cod_payment precheck | order_id=%s order_ref=%s "
                "payment_method=%s(%s) session=%s config=%s credit_note_method=%s(%s) action=%s amount=%s",
                order_id,
                order_ref,
                payment_method.display_name if payment_method.exists() else "missing",
                guarded_payment_method_id,
                guarded_session_id,
                config.display_name if config else "missing",
                credit_note_method.display_name if credit_note_method else "not configured",
                credit_note_method.id if credit_note_method else False,
                action,
                amount,
            )

            if credit_note_method and payment_method == credit_note_method:
                message = _(
                    "Credit Note Gift Card is only used in creating credit notes. "
                    "It cannot be used for COD payment collection."
                )
                _logger.warning(
                    "[COD guard] BLOCKED credit-note payment method for COD collection | "
                    "order_id=%s order_ref=%s method_id=%s session_id=%s",
                    order_id,
                    order_ref,
                    guarded_payment_method_id,
                    guarded_session_id,
                )
                return {"success": False, "message": message}

        return super().collect_cod_payment(
            order_id=order_id,
            payment_method_id=payment_method_id,
            amount=amount,
            session_id=session_id,
            action=action,
            order_ref=order_ref,
            return_lines=return_lines,
            mpesa_ref=mpesa_ref,
            **kwargs
        )
