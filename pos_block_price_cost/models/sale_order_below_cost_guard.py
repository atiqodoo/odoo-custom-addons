# -*- coding: utf-8 -*-
import logging

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class PosSessionSaleOrderBelowCostGuard(models.Model):
    _inherit = "pos.session"

    def _pc_to_int(self, value):
        if isinstance(value, models.BaseModel):
            return value.id
        try:
            return int(value)
        except (TypeError, ValueError):
            return False

    def _pc_normalize_tax_ids(self, tax_ids):
        normalized = []
        for tax_id in tax_ids or []:
            if isinstance(tax_id, int):
                normalized.append(tax_id)
            elif isinstance(tax_id, models.BaseModel):
                normalized.extend(tax_id.ids)
            elif isinstance(tax_id, (list, tuple)):
                if tax_id and tax_id[0] == 4 and len(tax_id) > 1:
                    normalized.append(self._pc_to_int(tax_id[1]))
                elif tax_id and tax_id[0] == 6 and len(tax_id) > 2:
                    normalized.extend(self._pc_to_int(tax) for tax in tax_id[2] or [])
            elif isinstance(tax_id, dict):
                normalized.append(self._pc_to_int(tax_id.get("id")))
            else:
                normalized.append(self._pc_to_int(tax_id))
        return [tax_id for tax_id in normalized if tax_id]

    def _pc_get_line_price_incl(self, line_data, taxes, product):
        qty = abs(float(line_data.get("qty") or line_data.get("quantity") or 1.0)) or 1.0
        price_subtotal_incl = line_data.get("price_subtotal_incl")
        if price_subtotal_incl not in (None, False):
            return float(price_subtotal_incl) / qty

        price_incl = line_data.get("price_incl")
        if price_incl not in (None, False):
            return float(price_incl)

        price_unit = float(line_data.get("price_unit") or 0.0)
        discount = float(line_data.get("discount") or 0.0)
        price_after_discount = price_unit * (1.0 - discount / 100.0)
        if taxes:
            return taxes.compute_all(
                price_after_discount,
                currency=self.currency_id,
                quantity=1.0,
                product=product,
                partner=False,
            )["total_included"]
        return price_after_discount

    def _pc_check_lines_below_cost_vat_incl(self, lines_data, source="unknown"):
        self.ensure_one()
        offenders = []
        Product = self.env["product.product"].sudo()
        Tax = self.env["account.tax"].sudo()
        precision = self.currency_id.rounding or 0.01

        _logger.info(
            "pos_block_price_cost [sale_order_guard]: checking %s line(s), "
            "source=%s, session=%s, config=%s",
            len(lines_data or []),
            source,
            self.id,
            self.config_id.display_name,
        )

        for index, line_data in enumerate(lines_data or [], start=1):
            if isinstance(line_data, (list, tuple)) and len(line_data) > 2:
                line_data = line_data[2] or {}
            if not isinstance(line_data, dict):
                _logger.warning(
                    "pos_block_price_cost [sale_order_guard]: skipping malformed "
                    "line #%s from %s: %s",
                    index,
                    source,
                    line_data,
                )
                continue

            qty = float(line_data.get("qty") or line_data.get("quantity") or 0.0)
            if qty <= 0:
                _logger.debug(
                    "pos_block_price_cost [sale_order_guard]: skipping refund/zero "
                    "line #%s, qty=%s",
                    index,
                    qty,
                )
                continue

            product_id = self._pc_to_int(line_data.get("product_id"))
            product = Product.browse(product_id)
            if not product.exists():
                _logger.warning(
                    "pos_block_price_cost [sale_order_guard]: product missing on "
                    "line #%s, product_id=%s",
                    index,
                    product_id,
                )
                continue

            cost_excl = product.standard_price or 0.0
            if cost_excl <= 0:
                _logger.debug(
                    "pos_block_price_cost [sale_order_guard]: skipping '%s' because "
                    "standard_price is %.4f",
                    product.display_name,
                    cost_excl,
                )
                continue

            tax_ids = self._pc_normalize_tax_ids(line_data.get("tax_ids"))
            taxes = Tax.browse(tax_ids)
            price_incl = self._pc_get_line_price_incl(line_data, taxes, product)
            if taxes:
                cost_incl = taxes.compute_all(
                    cost_excl,
                    currency=self.currency_id,
                    quantity=1.0,
                    product=product,
                    partner=False,
                    handle_price_include=False,
                )["total_included"]
            else:
                cost_incl = cost_excl

            diff = price_incl - cost_incl
            _logger.info(
                "pos_block_price_cost [sale_order_guard]: line #%s product='%s' "
                "qty=%.4f price_incl=%.4f cost_excl=%.4f cost_incl=%.4f "
                "diff=%.4f taxes=%s source=%s",
                index,
                product.display_name,
                qty,
                price_incl,
                cost_excl,
                cost_incl,
                diff,
                tax_ids,
                source,
            )

            if float_compare(price_incl, cost_incl, precision_rounding=precision) < 0:
                offenders.append({
                    "product_id": product.id,
                    "product_name": product.display_name,
                    "qty": qty,
                    "price_incl": round(price_incl, 2),
                    "cost_incl": round(cost_incl, 2),
                    "difference": round(cost_incl - price_incl, 2),
                })

        if offenders:
            _logger.warning(
                "pos_block_price_cost [sale_order_guard]: BLOCK source=%s "
                "session=%s offenders=%s",
                source,
                self.id,
                offenders,
            )
        else:
            _logger.info(
                "pos_block_price_cost [sale_order_guard]: PASS source=%s session=%s",
                source,
                self.id,
            )
        return offenders

    def validate_sale_order_below_cost(self, lines_data):
        return self._pc_check_lines_below_cost_vat_incl(
            lines_data,
            source="frontend_create_sale_order",
        )


class SaleOrderBelowCostGuard(models.Model):
    _inherit = "sale.order"

    def _pc_raise_for_below_cost_sale_order(self, order_data, pos_session):
        offenders = pos_session._pc_check_lines_below_cost_vat_incl(
            order_data.get("lines", []),
            source="backend_sbl_create_order_from_pos",
        )
        if not offenders:
            return

        detail_lines = [
            "%s: selling %.2f < cost %.2f"
            % (item["product_name"], item["price_incl"], item["cost_incl"])
            for item in offenders
        ]
        raise UserError(
            _(
                "Sale order blocked. These products are below cost price "
                "(VAT inclusive):\n%s"
            ) % "\n".join(detail_lines)
        )

    def sbl_create_order_from_pos(self, order_data, pos_session_id, action):
        pos_session = self.env["pos.session"].browse(pos_session_id)
        if pos_session.exists():
            self._pc_raise_for_below_cost_sale_order(order_data, pos_session)
        else:
            _logger.error(
                "pos_block_price_cost [sale_order_guard]: cannot validate below-cost "
                "sale order because session id %s does not exist",
                pos_session_id,
            )
        return super().sbl_create_order_from_pos(order_data, pos_session_id, action)
