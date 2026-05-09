# -*- coding: utf-8 -*-
"""JSON endpoint for POS exchange adjustment guard."""

import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger("pos_credit_note_gift_card.exchange_adjustment_guard")


class ExchangeAdjustmentGuardController(http.Controller):

    @http.route(
        "/pos/credit_note/exchange_adjustment_context",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def exchange_adjustment_context(
        self, config_id=None, original_line_ids=None, **kwargs
    ):
        _logger.info(
            "[ExchangeAdjustmentGuardController] config_id=%s original_line_ids=%s kwargs=%s",
            config_id,
            original_line_ids,
            kwargs,
        )
        try:
            result = request.env["pos.order"].get_exchange_adjustment_context(
                config_id=config_id,
                original_line_ids=original_line_ids or [],
            )
            _logger.debug("[ExchangeAdjustmentGuardController] result=%s", result)
            return {"ok": True, "payload": result, "error": None}
        except Exception as exc:
            _logger.exception(
                "[ExchangeAdjustmentGuardController] Unexpected error: %s", exc
            )
            return {"ok": False, "payload": None, "error": str(exc)}
