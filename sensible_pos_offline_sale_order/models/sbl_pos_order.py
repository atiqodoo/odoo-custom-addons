# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
from odoo import api, models


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
    def sync_from_ui(self, orders):
        remaining_orders = []
        result = self._sbl_empty_pos_sync_data()
        for order in orders:
            create_sale_order = order.pop('sbl_create_sale_order', False)
            pos_session = self.env['pos.session'].browse(order['session_id'])
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
