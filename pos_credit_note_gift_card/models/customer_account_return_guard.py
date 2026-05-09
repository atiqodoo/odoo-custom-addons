# -*- coding: utf-8 -*-
"""
customer_account_return_guard.py
================================
Server-side guard for credit-note returns of Customer Account sales.

Business rule
-------------
If the original POS order was paid with Customer Account / credit
(``pos.payment.method.type == 'pay_later'`` or the optional
``pcl_is_credit_method`` flag), a cashier must not create a gift-card
credit note for the return. The return should be completed through the
Customer Account payment method so the customer's receivable balance is
reduced.
"""

import logging

from odoo import _, api, models

_logger = logging.getLogger("pos_credit_note_gift_card.customer_account_return_guard")


class PosOrderCustomerAccountReturnGuard(models.Model):
    _inherit = "pos.order"

    @api.model
    def check_customer_account_return_block(self, original_order_ids):
        """Return a structured block result for original sale order ids."""
        clean_ids = []
        for order_id in original_order_ids or []:
            try:
                order_id = int(order_id)
            except (TypeError, ValueError):
                _logger.warning(
                    "[CustomerAccountReturnGuard] Ignoring invalid original_order_id=%r",
                    order_id,
                )
                continue
            if order_id:
                clean_ids.append(order_id)

        orders = self.browse(clean_ids).exists()
        blocked_orders = []

        _logger.info(
            "[CustomerAccountReturnGuard] Checking original_order_ids=%s resolved=%s",
            clean_ids,
            orders.ids,
        )

        for order in orders:
            credit_payments = order.payment_ids.filtered(
                lambda payment: self._cn_is_customer_account_payment_method(
                    payment.payment_method_id
                )
            )
            payment_debug = [
                {
                    "payment_id": payment.id,
                    "method_id": payment.payment_method_id.id,
                    "method_name": payment.payment_method_id.name,
                    "method_type": payment.payment_method_id.type,
                    "pcl_is_credit_method": bool(
                        getattr(payment.payment_method_id, "pcl_is_credit_method", False)
                    ),
                    "amount": payment.amount,
                }
                for payment in order.payment_ids
            ]
            _logger.debug(
                "[CustomerAccountReturnGuard] order=%s id=%s payment_debug=%s",
                order.name,
                order.id,
                payment_debug,
            )

            if credit_payments:
                method_names = ", ".join(credit_payments.mapped("payment_method_id.name"))
                blocked_orders.append(
                    {
                        "id": order.id,
                        "name": order.name,
                        "payment_methods": method_names,
                    }
                )
                _logger.warning(
                    "[CustomerAccountReturnGuard] BLOCK original order '%s' id=%s "
                    "paid by Customer Account methods=%s",
                    order.name,
                    order.id,
                    method_names,
                )

        if not blocked_orders:
            return {
                "blocked": False,
                "message": "",
                "orders": [],
            }

        order_names = ", ".join(order["name"] for order in blocked_orders)
        message = _(
            "Credit note generation is blocked because the original POS order "
            "%(orders)s was paid by Customer Account. Complete this return using "
            "the Customer Account payment method so the customer's account balance "
            "is corrected.",
            orders=order_names,
        )
        return {
            "blocked": True,
            "message": message,
            "orders": blocked_orders,
        }

    @api.model
    def _cn_is_customer_account_payment_method(self, payment_method):
        """True for Odoo Customer Account / optional pos_credit_limit marker."""
        if not payment_method:
            return False
        return bool(
            payment_method.type == "pay_later"
            or getattr(payment_method, "pcl_is_credit_method", False)
        )

    def validate_return_for_credit_note(self, config_id):
        """Append the Customer Account block to the existing validation result."""
        result = super().validate_return_for_credit_note(config_id)
        for order in self:
            original_order_ids = order.lines.mapped("refunded_orderline_id.order_id").ids
            guard = self.check_customer_account_return_block(original_order_ids)
            if guard.get("blocked"):
                result.setdefault("errors", []).append(guard["message"])
                result["ok"] = False
                _logger.warning(
                    "[CustomerAccountReturnGuard] validate_return_for_credit_note blocked "
                    "return_order=%s original_order_ids=%s",
                    order.name,
                    original_order_ids,
                )
        return result
