# -*- coding: utf-8 -*-
"""Server helpers for POS exchange value adjustments.

This file intentionally sits beside the existing credit-note logic instead of
editing it.  The browser-side exchange guard uses this model method to fetch
the same configuration and paid-out commission/global-discount attribution that
credit notes already use.
"""

import logging

from odoo import api, models

from .pos_order_line import PosOrderLine as _PosOrderLine

_logger = logging.getLogger("pos_credit_note_gift_card.exchange_adjustment_guard")


class PosOrderExchangeAdjustmentGuard(models.Model):
    _inherit = "pos.order"

    @api.model
    def get_exchange_adjustment_context(self, config_id, original_line_ids=None):
        """Return config + original-line payout data for exchange returns."""
        clean_line_ids = []
        for line_id in original_line_ids or []:
            try:
                line_id = int(line_id)
            except (TypeError, ValueError):
                _logger.warning(
                    "[ExchangeAdjustmentGuard] Ignoring invalid original_line_id=%r",
                    line_id,
                )
                continue
            if line_id:
                clean_line_ids.append(line_id)

        config = self.env["pos.config"].browse(int(config_id or 0)).exists()
        if not config:
            _logger.warning(
                "[ExchangeAdjustmentGuard] Missing POS config for config_id=%s",
                config_id,
            )
            return {
                "ok": False,
                "error": "POS configuration was not found.",
                "config": {},
                "lines": {},
            }

        line_map = _PosOrderLine.get_credit_note_commission(self.env, clean_line_ids)

        payload = {
            "ok": True,
            "error": "",
            "config": {
                "discount_distribution": config.credit_note_discount_distribution,
                "commission_mode": config.credit_note_commission_mode,
                "extra_weight": config.credit_note_extra_weight,
                "base_weight": config.credit_note_base_weight,
            },
            "lines": line_map,
        }
        _logger.info(
            "[ExchangeAdjustmentGuard] config_id=%s original_line_ids=%s payload=%s",
            config.id,
            clean_line_ids,
            payload,
        )
        return payload
