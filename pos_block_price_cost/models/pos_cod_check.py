# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging
import time

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class PosSessionCodCheck(models.Model):
    _inherit = 'pos.session'

    def _pc_cod_to_int(self, value):
        if isinstance(value, models.BaseModel):
            return value.id
        if isinstance(value, (list, tuple)):
            return self._pc_cod_to_int(value[0] if value else False)
        try:
            return int(value)
        except (TypeError, ValueError):
            return False

    def _pc_cod_normalize_tax_ids(self, tax_ids):
        normalized = []
        for tax_id in tax_ids or []:
            if isinstance(tax_id, int):
                normalized.append(tax_id)
            elif isinstance(tax_id, models.BaseModel):
                normalized.extend(tax_id.ids)
            elif isinstance(tax_id, (list, tuple)):
                if tax_id and tax_id[0] == 4 and len(tax_id) > 1:
                    normalized.append(self._pc_cod_to_int(tax_id[1]))
                elif tax_id and tax_id[0] == 6 and len(tax_id) > 2:
                    normalized.extend(self._pc_cod_to_int(tax) for tax in tax_id[2] or [])
                else:
                    normalized.extend(self._pc_cod_to_int(tax) for tax in tax_id)
            elif isinstance(tax_id, dict):
                normalized.append(self._pc_cod_to_int(tax_id.get('id')))
            else:
                normalized.append(self._pc_cod_to_int(tax_id))
        return [tax_id for tax_id in normalized if tax_id]

    def _pc_get_product_taxes(self, product, tax_ids=None):
        taxes = self.env['account.tax'].sudo().browse(self._pc_cod_normalize_tax_ids(tax_ids))
        if taxes:
            return taxes

        company = self.config_id.company_id or self.company_id or self.env.company
        return product.taxes_id.filtered(
            lambda tax: not tax.company_id or tax.company_id == company
        )

    def _pc_get_line_price_incl(self, line_data, taxes, product):
        qty = abs(float(line_data.get('qty') or line_data.get('quantity') or 1.0)) or 1.0
        price_subtotal_incl = line_data.get('price_subtotal_incl')
        if price_subtotal_incl not in (None, False):
            return float(price_subtotal_incl) / qty

        price_incl = line_data.get('price_incl')
        if price_incl not in (None, False):
            return float(price_incl)

        price_unit = float(line_data.get('price_unit') or 0.0)
        discount = float(line_data.get('discount') or 0.0)
        price_after_discount = price_unit * (1.0 - discount / 100.0)
        if taxes:
            return taxes.compute_all(
                price_after_discount,
                currency=self.currency_id,
                quantity=1.0,
                product=product,
                partner=False,
            )['total_included']
        return price_after_discount

    def _pc_cost_incl_for_product(self, product, taxes):
        cost_excl = product.standard_price or 0.0
        if taxes:
            return taxes.compute_all(
                cost_excl,
                currency=self.currency_id,
                quantity=1.0,
                product=product,
                partner=False,
                handle_price_include=False,
            )['total_included']
        return cost_excl

    def _pc_check_cod_lines_below_cost_vat_incl(self, lines_data, source='cod_frontend'):
        self.ensure_one()
        offenders = []
        precision = self.currency_id.rounding or 0.01
        Product = self.env['product.product'].sudo()

        for index, line in enumerate(lines_data or [], start=1):
            if isinstance(line, (list, tuple)) and len(line) > 2:
                line = line[2] or {}
            if not isinstance(line, dict):
                _logger.warning(
                    "pos_block_price_cost [cod_check]: skipping malformed line #%s "
                    "from %s: %s",
                    index, source, line,
                )
                continue

            qty = float(line.get('qty') or line.get('quantity') or 1.0)
            if qty <= 0:
                continue

            product = Product.browse(self._pc_cod_to_int(line.get('product_id')))
            if not product.exists():
                continue

            cost_excl = product.standard_price or 0.0
            if cost_excl <= 0:
                continue

            taxes = self._pc_get_product_taxes(product, line.get('tax_ids'))
            price_incl = self._pc_get_line_price_incl(line, taxes, product)
            cost_incl = self._pc_cost_incl_for_product(product, taxes)
            diff = price_incl - cost_incl

            _logger.info(
                "pos_block_price_cost [cod_check]: line #%s source=%s "
                "product='%s' qty=%.4f price_incl=%.4f cost_excl=%.4f "
                "cost_incl=%.4f diff=%.4f taxes=%s",
                index,
                source,
                product.display_name,
                qty,
                price_incl,
                cost_excl,
                cost_incl,
                diff,
                taxes.ids,
            )

            if float_compare(price_incl, cost_incl, precision_rounding=precision) < 0:
                offenders.append({
                    'product_id': product.id,
                    'product_name': product.display_name,
                    'qty': qty,
                    'cost_incl': round(cost_incl, 2),
                    'price_incl': round(price_incl, 2),
                    'difference': round(cost_incl - price_incl, 2),
                })

        return offenders

    def _pc_below_cost_signature(self, lines_data, source='unknown'):
        """Stable signature of the current below-cost line snapshot."""
        offenders = self._pc_check_cod_lines_below_cost_vat_incl(lines_data, source=source)
        normalized = [
            {
                "cost_incl": item["cost_incl"],
                "price_incl": item["price_incl"],
                "product_id": item["product_id"],
                "qty": item["qty"],
            }
            for item in offenders
        ]
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def validate_cod_below_cost(self, lines_data):
        """Return COD lines whose selling price is below VAT-inclusive cost."""
        return self._pc_check_cod_lines_below_cost_vat_incl(
            lines_data,
            source='frontend_cod_button',
        )


class PosOrderCodBelowCostGuard(models.Model):
    _inherit = 'pos.order'

    pc_below_cost_override_employee_id = fields.Many2one(
        "hr.employee",
        string="Below Cost Override Employee",
        readonly=True,
        copy=False,
    )
    pc_below_cost_override_token = fields.Char(
        string="Below Cost Override Token",
        readonly=True,
        copy=False,
    )
    pc_below_cost_override_at = fields.Datetime(
        string="Below Cost Override At",
        readonly=True,
        copy=False,
    )

    def _pc_cod_to_int(self, value):
        if isinstance(value, models.BaseModel):
            return value.id
        if isinstance(value, (list, tuple)):
            return self._pc_cod_to_int(value[0] if value else False)
        try:
            return int(value)
        except (TypeError, ValueError):
            return False

    def _pc_session_for_cod_payload(self, order_data):
        session_id = (
            order_data.get('session_id')
            or order_data.get('pos_session_id')
            or order_data.get('pos_session')
        )
        session_id = self._pc_cod_to_int(session_id)
        session = self.env['pos.session'].browse(session_id) if session_id else self.env['pos.session']
        return session if session.exists() else self.env['pos.session']

    def _pc_parse_below_cost_override_token(self, token):
        if not token or "." not in token:
            return None
        payload_json, digest = token.rsplit(".", 1)
        expected = hmac.new(
            self.env["pos.session"]._pc_override_secret(),
            payload_json.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(digest, expected):
            return None
        try:
            return json.loads(payload_json)
        except json.JSONDecodeError:
            return None

    def _pc_has_valid_below_cost_override(self, order_data, session):
        token = order_data.get("pc_below_cost_override_token")
        payload = self._pc_parse_below_cost_override_token(token)
        if not payload:
            return False

        max_age_seconds = 12 * 60 * 60
        if int(time.time()) - int(payload.get("issued_at") or 0) > max_age_seconds:
            return False
        if payload.get("session_id") != session.id:
            return False
        if payload.get("order_uuid") != (order_data.get("uuid") or ""):
            return False

        signature = session._pc_below_cost_signature(
            order_data.get("lines", []),
            source="backend_pos_sync_override_verify",
        )
        if payload.get("signature") != signature:
            return False

        employee = self.env["hr.employee"].sudo().browse(payload.get("employee_id"))
        if not employee.exists():
            return False
        order_data["pc_below_cost_override_employee_id"] = employee.id
        order_data["pc_below_cost_override_at"] = fields.Datetime.now()
        return True

    def _pc_raise_for_cod_below_cost(self, order_data):
        if not order_data.get('is_cod'):
            return

        session = self._pc_session_for_cod_payload(order_data)
        if not session:
            _logger.warning(
                "pos_block_price_cost [cod_check]: cannot run backend COD "
                "below-cost guard for %s because session_id is missing",
                order_data.get('name'),
            )
            return

        offenders = session._pc_check_cod_lines_below_cost_vat_incl(
            order_data.get('lines', []),
            source='backend_cod_sync_from_ui',
        )
        if not offenders:
            return

        detail_lines = [
            "%s: selling %.2f < cost %.2f"
            % (item['product_name'], item['price_incl'], item['cost_incl'])
            for item in offenders
        ]
        _logger.warning(
            "pos_block_price_cost [cod_check]: BLOCK COD dispatch order=%s "
            "offenders=%s",
            order_data.get('name'),
            offenders,
        )
        raise UserError(
            _(
                "COD order blocked. These products are below cost price "
                "(VAT inclusive):\n%s"
            ) % "\n".join(detail_lines)
        )

    def _pc_raise_for_pos_below_cost(self, order_data):
        if order_data.get("state") == "draft":
            return

        session = self._pc_session_for_cod_payload(order_data)
        if not session:
            _logger.warning(
                "[POS_BLOCK_PRICE_COST][POS_SYNC_GUARD][ERROR] "
                "order=%s reason=missing_session",
                order_data.get("name"),
            )
            return

        _logger.info(
            "[POS_BLOCK_PRICE_COST][POS_SYNC_GUARD][START] order=%s session_id=%s",
            order_data.get("name"),
            session.id,
        )
        offenders = session._pc_check_cod_lines_below_cost_vat_incl(
            order_data.get("lines", []),
            source="backend_pos_sync_from_ui",
        )
        if not offenders:
            _logger.info(
                "[POS_BLOCK_PRICE_COST][POS_SYNC_GUARD][END] order=%s outcome=pass",
                order_data.get("name"),
            )
            return

        if self._pc_has_valid_below_cost_override(order_data, session):
            _logger.warning(
                "[POS_BLOCK_PRICE_COST][POS_SYNC_GUARD][END] order=%s "
                "outcome=override_allowed offenders=%s employee_id=%s",
                order_data.get("name"),
                offenders,
                order_data.get("pc_below_cost_override_employee_id"),
            )
            return

        detail_lines = [
            "%s: selling %.2f < cost %.2f"
            % (item['product_name'], item['price_incl'], item['cost_incl'])
            for item in offenders
        ]
        _logger.warning(
            "[POS_BLOCK_PRICE_COST][POS_SYNC_GUARD][ERROR] order=%s "
            "outcome=blocked offenders=%s",
            order_data.get("name"),
            offenders,
        )
        raise UserError(
            _(
                "POS order blocked. These products are below cost price "
                "(VAT inclusive):\n%s"
            ) % "\n".join(detail_lines)
        )

    def sync_from_ui(self, orders):
        for order_data in orders or []:
            self._pc_raise_for_pos_below_cost(order_data)
            self._pc_raise_for_cod_below_cost(order_data)
        return super().sync_from_ui(orders)
