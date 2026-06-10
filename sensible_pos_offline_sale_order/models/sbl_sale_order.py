# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
import logging

from odoo import Command, _, api, fields, models


_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    sbl_uuid = fields.Char(string='Uuid', readonly=True, copy=False)
    sbl_session_id = fields.Many2one('pos.session', string='Session')

    def _sbl_get_open_sale_order(self, order):
        return self.env["sale.order"].search([('sbl_uuid', '=', order.get('uuid'))], limit=1)

    @staticmethod
    def _sbl_get_order_log_representation(order):
        return dict((k, order.get(k)) for k in ("name", "uuid"))

    @api.model
    def _sbl_prepare_from_pos(self, order_data, pos_session_id):
        PosSession = self.env["pos.session"]
        session = PosSession.browse(order_data["session_id"])
        SaleOrderLine = self.env["sale.order.line"]
        order_lines = [
            Command.create(SaleOrderLine._sbl_prepare_from_pos(sequence, line_data))
            for sequence, line_data in enumerate(order_data["lines"], start=1)
        ]
        vals = {
            "partner_id": order_data["partner_id"],
            "origin": _("Point of Sale %s") % (session.name),
            "client_order_ref": order_data["name"],
            "user_id": order_data["user_id"],
            "pricelist_id": order_data["pricelist_id"],
            "fiscal_position_id": order_data["fiscal_position_id"],
            "order_line": order_lines,
            "sbl_uuid": order_data["uuid"],
            "sbl_session_id": pos_session_id,
        }
        return vals

    def _sbl_reapply_pos_line_prices(self, order_data):
        """Keep POS manual prices after sale.order create/onchange recomputations."""
        SaleOrderLine = self.env["sale.order.line"]
        pos_lines_data = order_data.get("lines", [])
        for sequence, pos_line in enumerate(pos_lines_data, start=1):
            line_data = SaleOrderLine._sbl_get_line_data(pos_line)
            price_unit = line_data.get("price_unit")
            if price_unit is None:
                continue

            sale_line = self.order_line.filtered(lambda line: line.sequence == sequence)[:1]
            if not sale_line:
                continue

            vals = {
                "price_unit": price_unit,
                "technical_price_unit": price_unit,
            }
            if "price_locked" in sale_line._fields:
                vals["price_locked"] = True
            sale_line.write(vals)

    @api.model
    def sbl_create_order_from_pos(self, order_data, pos_session_id, action):
        # Create Draft Sale order
        existing_order = self._sbl_get_open_sale_order(order_data)
        order_log_name = self._sbl_get_order_log_representation(order_data)
        if existing_order:
            _logger.info("PoS synchronisation sale order %s sync ignored for existing Sale order %s ", order_log_name, existing_order.name,)
            return True
        order_vals = self._sbl_prepare_from_pos(order_data, pos_session_id)
        sale_order = self.with_context(
            pos_order_lines_data=order_data.get("lines", [])
        ).create(order_vals)
        sale_order._sbl_reapply_pos_line_prices(order_data)
        sale_order._recompute_taxes()
        sale_order._sbl_reapply_pos_line_prices(order_data)

        # confirm sale order
        if action in ["confirmed", "delivered", "invoiced"]:
            sale_order.action_confirm()
            sale_order._sbl_reapply_pos_line_prices(order_data)

        # delivered picking
        if action in ["delivered", "invoiced"]:
            # mark all moves are delivered
            for move in sale_order.mapped("picking_ids.move_ids_without_package"):
                move.quantity = move.product_uom_qty
            sale_order.mapped("picking_ids").button_validate()

        if action in ["invoiced"]:
            # create and confirm invoices
            invoices = sale_order._create_invoices()
            invoices.action_post()
        return True
