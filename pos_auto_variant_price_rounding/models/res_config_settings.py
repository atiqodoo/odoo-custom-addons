# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    auto_variant_price_enabled = fields.Boolean(
        related="pos_config_id.auto_variant_price_enabled",
        readonly=False,
    )
    auto_variant_price_rounding_step = fields.Float(
        related="pos_config_id.auto_variant_price_rounding_step",
        readonly=False,
    )
    auto_variant_price_include_vat = fields.Boolean(
        related="pos_config_id.auto_variant_price_include_vat",
        readonly=False,
    )
    auto_variant_price_vat_rate = fields.Float(
        related="pos_config_id.auto_variant_price_vat_rate",
        readonly=False,
    )
    auto_variant_price_on_receipt = fields.Boolean(
        related="pos_config_id.auto_variant_price_on_receipt",
        readonly=False,
    )
    auto_variant_price_on_landed_cost = fields.Boolean(
        related="pos_config_id.auto_variant_price_on_landed_cost",
        readonly=False,
    )
    auto_variant_price_on_vendor_bill = fields.Boolean(
        related="pos_config_id.auto_variant_price_on_vendor_bill",
        readonly=False,
    )
    auto_variant_price_on_manual_cost = fields.Boolean(
        related="pos_config_id.auto_variant_price_on_manual_cost",
        readonly=False,
    )
    auto_variant_price_update_pricelist = fields.Boolean(
        related="pos_config_id.auto_variant_price_update_pricelist",
        readonly=False,
    )
    auto_variant_price_pricelist_scope = fields.Selection(
        related="pos_config_id.auto_variant_price_pricelist_scope",
        readonly=False,
    )
    auto_variant_price_log_no_change = fields.Boolean(
        related="pos_config_id.auto_variant_price_log_no_change",
        readonly=False,
    )
