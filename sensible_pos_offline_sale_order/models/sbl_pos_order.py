# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
import logging

from odoo import api, models


_logger = logging.getLogger(__name__)


class POSOrder(models.Model):
    _inherit = "pos.order"

    def _sbl_empty_pos_sync_data(self):
        return {
            "pos.order": [],
            "pos.session": [],
            "pos.payment": [],
            "pos.order.line": [],
            "pos.pack.operation.lot": [],
            "product.attribute.custom.value": [],
        }

    @api.model
    def _sbl_should_create_sale_order_from_unpaid_pos_payload(self, order, pos_session):
        """Recover create-sale-order payloads that reached the backend without the JS flag."""
        if not pos_session.config_id.sbl_create_sale_order:
            return False
        if order.get("is_cod"):
            return False
        if order.get("state") != "paid":
            return False
        if order.get("payment_ids"):
            return False
        if not order.get("partner_id") or not order.get("lines"):
            return False
        return True

    @api.model
    def sync_from_ui(self, orders):
        remaining_orders = []
        result = self._sbl_empty_pos_sync_data()
        for order in orders:
            create_sale_order = order.pop('sbl_create_sale_order', False)
            pos_session = self.env['pos.session'].browse(order['session_id'])
            if (
                not create_sale_order
                and pos_session
                and pos_session.config_id
                and self._sbl_should_create_sale_order_from_unpaid_pos_payload(order, pos_session)
            ):
                create_sale_order = True
                _logger.info(
                    "PoS synchronisation sale order %s recovered from unpaid no-payment payload",
                    {
                        "name": order.get("name"),
                        "uuid": order.get("uuid"),
                        "amount_total": order.get("amount_total"),
                        "amount_return": order.get("amount_return"),
                    },
                )
            if (
                not pos_session
                or not pos_session.config_id
                or not pos_session.config_id.sbl_create_sale_order
                or not create_sale_order
            ):
                remaining_orders.append(order)
            else:
                self.env['sale.order'].sbl_create_order_from_pos(
                    order,
                    pos_session.id,
                    action=pos_session.config_id.sbl_create_sale_order_action,
                )
        if remaining_orders:
            result.update(super().sync_from_ui(remaining_orders))

        # Odoo 18 POS frontend always iterates these keys after sync_from_ui.
        # When this module turns the POS order into only a sale.order, no
        # pos.order/pos.order.line records are returned, so keep the shape stable.
        for key, value in self._sbl_empty_pos_sync_data().items():
            result.setdefault(key, value)
        return result
