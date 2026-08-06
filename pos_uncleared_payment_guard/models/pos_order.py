# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger("pos_uncleared_payment_guard.pos_order")


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def _process_order(self, order, existing_order):
        order_id = super()._process_order(order, existing_order)
        pos_order = self.browse(order_id).exists()
        if pos_order:
            pos_order._upg_create_uncleared_holds()
        return order_id

    def _upg_is_customer_account_settlement_order(self):
        self.ensure_one()
        return bool(self.partner_id and not self.lines and self.payment_ids)

    def _upg_create_uncleared_holds(self):
        Hold = self.env["pos.uncleared.payment.hold"].sudo()
        for order in self:
            if not order._upg_is_customer_account_settlement_order():
                _logger.debug(
                    "[UPG][PosOrder] order=%s skipped: partner=%s lines=%d payments=%d",
                    order.name,
                    order.partner_id.display_name if order.partner_id else "none",
                    len(order.lines),
                    len(order.payment_ids),
                )
                continue
            for payment in order.payment_ids.filtered(lambda p: p.amount > 0 and not p.is_change):
                if not payment._upg_is_uncleared_guard_payment():
                    continue
                existing = Hold.search([("pos_payment_id", "=", payment.id)], limit=1)
                if existing:
                    _logger.info(
                        "[UPG][PosOrder] duplicate hold skipped order=%s payment=%s hold=%s",
                        order.name,
                        payment.id,
                        existing.name,
                    )
                    continue
                vals = payment._upg_prepare_hold_vals()
                _logger.warning(
                    "[UPG][PosOrder] guarded settlement/deposit detected order=%s payment=%s method=%s amount=%.2f",
                    order.name,
                    payment.id,
                    payment.payment_method_id.display_name,
                    payment.amount,
                )
                Hold.create(vals)
