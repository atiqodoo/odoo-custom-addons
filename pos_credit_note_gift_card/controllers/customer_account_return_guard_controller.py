# -*- coding: utf-8 -*-
"""JSON endpoint for Customer Account return blocking."""

import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger("pos_credit_note_gift_card.customer_account_return_guard")


class CustomerAccountReturnGuardController(http.Controller):

    @http.route(
        "/pos/credit_note/customer_account_return_guard",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def customer_account_return_guard(self, original_order_ids=None, **kwargs):
        _logger.info(
            "[CustomerAccountReturnGuardController] original_order_ids=%s kwargs=%s",
            original_order_ids,
            kwargs,
        )
        try:
            result = request.env["pos.order"].check_customer_account_return_block(
                original_order_ids or []
            )
            _logger.debug("[CustomerAccountReturnGuardController] result=%s", result)
            return {"ok": True, "payload": result, "error": None}
        except Exception as exc:
            _logger.exception(
                "[CustomerAccountReturnGuardController] Unexpected error: %s", exc
            )
            return {"ok": False, "payload": None, "error": str(exc)}
