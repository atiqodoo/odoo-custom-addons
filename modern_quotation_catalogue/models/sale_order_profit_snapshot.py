# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    mqc_profit_cost_unit_excl_vat_snapshot = fields.Monetary(
        string='MQC Cost / Unit Excl. VAT Snapshot',
        currency_field='currency_id',
        copy=False,
    )
    mqc_profit_cost_unit_incl_vat_snapshot = fields.Monetary(
        string='MQC Cost / Unit Incl. VAT Snapshot',
        currency_field='currency_id',
        copy=False,
    )
    mqc_profit_per_unit_incl_vat_snapshot = fields.Monetary(
        string='MQC Profit / Unit Incl. VAT Snapshot',
        currency_field='currency_id',
        copy=False,
    )
    mqc_profit_total_incl_vat_snapshot = fields.Monetary(
        string='MQC Total Profit Incl. VAT Snapshot',
        currency_field='currency_id',
        copy=False,
    )
    mqc_profit_snapshot_at = fields.Datetime(
        string='MQC Profit Snapshot At',
        copy=False,
    )

    def _mqc_capture_profit_snapshot(self, force_cost=False):
        for line in self.filtered(lambda item: not item.display_type and item.product_id):
            values = line._mqc_prepare_profit_snapshot_values(force_cost=force_cost)
            line.write(values)
            _logger.info(
                '%s | PROFIT SNAPSHOT CAPTURED | line_id=%s | order_id=%s | product_id=%s | values=%s',
                'MODERN QUOTATION CATALOGUE',
                line.id,
                line.order_id.id,
                line.product_id.id,
                values,
            )

    def _mqc_prepare_profit_snapshot_values(self, force_cost=False):
        self.ensure_one()
        cost_unit_excl = self.mqc_profit_cost_unit_excl_vat_snapshot
        cost_unit_incl = self.mqc_profit_cost_unit_incl_vat_snapshot
        if force_cost or not self.mqc_profit_snapshot_at:
            cost_unit_excl = self._mqc_get_current_cost_unit_excl_vat()
            cost_unit_incl = self._mqc_get_cost_unit_incl_vat(cost_unit_excl)

        qty = self.product_uom_qty or 0.0
        selling_unit_incl = (self.price_total / qty) if qty else self.price_unit
        profit_per_unit = selling_unit_incl - cost_unit_incl
        total_profit = self.price_total - (cost_unit_incl * qty)
        return {
            'mqc_profit_cost_unit_excl_vat_snapshot': cost_unit_excl,
            'mqc_profit_cost_unit_incl_vat_snapshot': cost_unit_incl,
            'mqc_profit_per_unit_incl_vat_snapshot': profit_per_unit,
            'mqc_profit_total_incl_vat_snapshot': total_profit,
            'mqc_profit_snapshot_at': fields.Datetime.now(),
        }

    def _mqc_get_current_cost_unit_excl_vat(self):
        self.ensure_one()
        cost = getattr(self, 'purchase_price', 0.0) or self.product_id.standard_price or 0.0
        if self.product_id.uom_id and self.product_uom and self.product_id.uom_id != self.product_uom:
            cost = self.product_id.uom_id._compute_price(cost, self.product_uom)

        source_currency = self.product_id.company_id.currency_id or self.order_id.company_id.currency_id
        target_currency = self.currency_id or self.order_id.currency_id
        if source_currency and target_currency and source_currency != target_currency:
            cost = source_currency._convert(
                cost,
                target_currency,
                self.order_id.company_id,
                self.order_id.date_order or fields.Date.context_today(self),
            )
        return cost

    def _mqc_get_cost_unit_incl_vat(self, cost_unit_excl):
        self.ensure_one()
        taxes = self.tax_id or self.product_id.taxes_id.filtered(
            lambda tax: not tax.company_id or tax.company_id == self.order_id.company_id
        )
        if not taxes:
            return cost_unit_excl
        tax_result = taxes.compute_all(
            cost_unit_excl,
            currency=self.currency_id,
            quantity=1.0,
            product=self.product_id,
            partner=self.order_id.partner_shipping_id or self.order_id.partner_id,
            handle_price_include=False,
        )
        return tax_result.get('total_included', cost_unit_excl)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mqc_profit_total_incl_vat_snapshot = fields.Monetary(
        string='MQC Total Profit Incl. VAT Snapshot',
        compute='_compute_mqc_profit_total_incl_vat_snapshot',
        currency_field='currency_id',
    )

    @api.depends('order_line.mqc_profit_total_incl_vat_snapshot')
    def _compute_mqc_profit_total_incl_vat_snapshot(self):
        for order in self:
            order.mqc_profit_total_incl_vat_snapshot = sum(
                order.order_line.filtered(lambda line: not line.display_type).mapped('mqc_profit_total_incl_vat_snapshot')
            )

    def _mqc_ensure_profit_snapshots(self):
        lines = self.mapped('order_line').filtered(
            lambda line: not line.display_type and line.product_id and not line.mqc_profit_snapshot_at
        )
        lines._mqc_capture_profit_snapshot(force_cost=True)
