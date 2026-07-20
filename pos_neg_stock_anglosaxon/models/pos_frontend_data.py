# -*- coding: utf-8 -*-
"""Read-only policy data exposed to the POS frontend."""

import logging

from odoo import api, fields, models

from .res_config_settings import BLOCK_TINTED_OVERSELL_PARAM


_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    _inherit = "pos.config"

    block_tinted_oversell_without_normal_lot = fields.Boolean(
        compute="_compute_block_tinted_oversell_without_normal_lot",
        compute_sudo=True,
        string="Block Tinted POS Oversell Without a Normal Lot",
    )

    def _compute_block_tinted_oversell_without_normal_lot(self):
        enabled = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(BLOCK_TINTED_OVERSELL_PARAM, default="False")
            == "True"
        )
        for config in self:
            config.block_tinted_oversell_without_normal_lot = enabled


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _load_pos_data_fields(self, config_id):
        field_names = super()._load_pos_data_fields(config_id)
        if "is_tinted_product" in self._fields and "is_tinted_product" not in field_names:
            field_names.append("is_tinted_product")
        return field_names


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    @api.model
    def get_temporary_lot_guard_stock_snapshot(self, company_id, product_id):
        """Return current net warehouse stock for frontend lot-cap decisions.

        This method is deliberately read-only. It delegates quantity computation
        to standard ``product.product.qty_available`` with the POS warehouse
        context and does not write quants, moves, valuation layers, or accounts.
        """
        self.check_access("read")
        config = self.env["pos.config"].browse(self.env.context.get("config_id")).exists()
        product = self.env["product.product"].browse(product_id).exists()
        company = self.env["res.company"].browse(company_id).exists()
        if not config or not product or not company:
            _logger.warning(
                "[NegStock][POS_TEMP_LOT_GUARD] stock snapshot unavailable | "
                "config_id=%s company_id=%s product_id=%s",
                self.env.context.get("config_id"),
                company_id,
                product_id,
            )
            return {
                "net_available_quantity": 0.0,
                "warehouse_id": False,
                "product_id": product_id,
            }

        warehouse = config.warehouse_id
        net_available = product.with_company(company).with_context(
            warehouse_id=warehouse.id,
        ).qty_available
        result = {
            "net_available_quantity": net_available,
            "warehouse_id": warehouse.id,
            "warehouse_name": warehouse.display_name,
            "product_id": product.id,
            "product_name": product.display_name,
            "uom_rounding": product.uom_id.rounding,
        }
        _logger.info(
            "[NegStock][POS_TEMP_LOT_GUARD] stock snapshot | %s",
            result,
        )
        return result
