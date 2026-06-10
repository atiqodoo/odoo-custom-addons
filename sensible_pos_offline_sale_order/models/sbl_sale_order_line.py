# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
from collections import Counter

from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    sbl_pos_lot_names = fields.Json(
        string="POS Lot/Serial Numbers",
        copy=False,
        help="Lot/serial numbers selected in POS when this sale order line was created from POS.",
    )

    @api.model
    def _sbl_get_line_data(self, order_line):
        return order_line[2] if isinstance(order_line, list) else order_line

    @api.model
    def _sbl_prepare_tax_ids_from_pos(self, tax_ids):
        if not tax_ids:
            return [(6, 0, [])]
        if all(isinstance(tax_id, int) for tax_id in tax_ids):
            return [(6, 0, tax_ids)]
        return tax_ids

    @api.model
    def _sbl_get_pos_lot_names(self, order_line_data):
        lot_names = []
        for pack_lot_command in order_line_data.get("pack_lot_ids") or []:
            if isinstance(pack_lot_command, (list, tuple)) and len(pack_lot_command) >= 3:
                pack_lot_data = pack_lot_command[2] or {}
            elif isinstance(pack_lot_command, dict):
                pack_lot_data = pack_lot_command
            else:
                continue

            lot_name = pack_lot_data.get("lot_name")
            if lot_name:
                lot_names.append(lot_name)
        return lot_names

    @api.model
    def _sbl_prepare_from_pos(self, sequence, order_line):
        order_line_data = self._sbl_get_line_data(order_line)
        price_unit = order_line_data.get("price_unit", 0.0)
        vals = {
            "sequence": sequence,
            "product_id": order_line_data["product_id"],
            "product_uom_qty": order_line_data["qty"],
            "discount": order_line_data["discount"],
            "price_unit": price_unit,
            "technical_price_unit": price_unit,
            "tax_id": self._sbl_prepare_tax_ids_from_pos(order_line_data.get("tax_ids")),
        }
        lot_names = self._sbl_get_pos_lot_names(order_line_data)
        if lot_names:
            vals["sbl_pos_lot_names"] = lot_names
        if "price_locked" in self._fields:
            vals["price_locked"] = True
        return vals

    def read_converted(self):
        results = super().read_converted()
        results_by_id = {line_data["id"]: line_data for line_data in results}

        for sale_line in self:
            line_data = results_by_id.get(sale_line.id)
            if not line_data or line_data.get("lot_names") or not sale_line.sbl_pos_lot_names:
                continue

            lot_names = [name for name in sale_line.sbl_pos_lot_names if name]
            if not lot_names:
                continue

            line_data["lot_names"] = lot_names
            if len(lot_names) == 1:
                line_data["lot_qty_by_name"] = {lot_names[0]: line_data["product_uom_qty"]}
            else:
                line_data["lot_qty_by_name"] = dict(Counter(lot_names))

        return results

    def _get_sale_order_line_multiline_description_sale(self):
        res = super()._get_sale_order_line_multiline_description_sale()

        for sequence, order_line in enumerate(
            self.env.context.get("pos_order_lines_data", []), start=1
        ):
            line_data = self._sbl_get_line_data(order_line)
            if line_data.get("customer_note", False) and self.sequence == sequence:
                res += f"\n{line_data.get('customer_note')}"

        return res
