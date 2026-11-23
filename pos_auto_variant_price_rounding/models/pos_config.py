# -*- coding: utf-8 -*-

import logging
import uuid

from odoo import fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    _inherit = "pos.config"

    auto_variant_price_enabled = fields.Boolean(
        string="Auto Increase Variant Prices",
        default=False,
        help="Automatically increase product variant selling prices when inclusive cost rises.",
    )
    auto_variant_price_rounding_step = fields.Float(
        string="Rounding Step",
        default=50.0,
        help="Cost increases are rounded upward to this amount before updating the selling price.",
    )
    auto_variant_price_include_vat = fields.Boolean(
        string="Include VAT in Cost",
        default=True,
        help="Compare accounting costs including the applicable purchase taxes using Odoo's tax engine.",
    )
    auto_variant_price_vat_rate = fields.Float(
        string="VAT Rate (%)",
        default=16.0,
        help="Legacy setting, retained for historical compatibility. New checks use purchase taxes.",
    )
    auto_variant_price_on_receipt = fields.Boolean(
        string="Apply on Incoming Receipts",
        default=True,
        help="Apply the formula after supplier incoming deliveries are validated.",
    )
    auto_variant_price_on_landed_cost = fields.Boolean(
        string="Apply on Landed Cost",
        default=True,
        help="Apply the formula after landed costs are validated.",
    )
    auto_variant_price_on_vendor_bill = fields.Boolean(
        string="Apply on Vendor Bill",
        default=True,
        help="Apply the formula after vendor bills are posted and Odoo updates purchase valuation.",
    )
    auto_variant_price_on_manual_cost = fields.Boolean(
        string="Apply on Manual Cost Increase",
        default=True,
        help="Apply the formula when a user manually increases product variant cost.",
    )
    auto_variant_price_update_pricelist = fields.Boolean(
        string="Update POS Pricelist Fixed Price",
        default=True,
        help="Update variant fixed-price rules only. Shared rules and the template sale price remain unchanged.",
    )
    auto_variant_price_pricelist_scope = fields.Selection(
        [
            ("default", "Default POS Pricelist Only"),
            ("available", "All Available POS Pricelists"),
        ],
        string="Pricelist Update Scope",
        default="available",
        help="Choose which POS pricelist rules are updated when a cost increase changes selling price.",
    )
    auto_variant_price_log_no_change = fields.Boolean(
        string="Log No-Change Decisions",
        default=True,
        help="Create audit records when the app checks a cost change but does not update the price.",
    )

    auto_variant_price_allow_sale_fallback = fields.Boolean(
        string="Allow Standard Sale Price Fallback", default=False,
        help="Allow creation of a variant rule from the standard sale price when no rule applies. Review default prices first.",
    )
    auto_variant_price_sync_interval = fields.Integer(
        string="Price Sync Recovery Interval (seconds)", default=60,
        help="Connected POS terminals check for missed price updates at this interval. Minimum 10 seconds.",
    )
    auto_variant_price_revision = fields.Char(readonly=True, copy=False)

    def _notify_variant_prices(self):
        for config in self:
            _logger.debug("[POS_AUTO_PRICE][NOTIFY][START] config_id=%s", config.id)
            revision = uuid.uuid4().hex
            config.write({"auto_variant_price_revision": revision})
            # Native bus messages are delivered after commit.
            config._notify("VARIANT_PRICES_CHANGED", {"revision": revision})
            _logger.debug("[POS_AUTO_PRICE][NOTIFY][END] config_id=%s revision=%s", config.id, revision)

    def get_variant_price_snapshot(self, product_ids, revision=False):
        """Read-only POS endpoint. No sudo; never return purchase costs or tokens."""
        self.ensure_one()
        self.check_access("read")
        if not self.env.user.has_group("point_of_sale.group_pos_user") or self.company_id not in self.env.companies:
            raise AccessError("This POS configuration is not available to you.")
        _logger.debug("[POS_AUTO_PRICE][SNAPSHOT][START] config_id=%s", self.id)
        result = {"revision": self.auto_variant_price_revision or "initial",
                  "interval": max(10, self.auto_variant_price_sync_interval), "rules": None}
        if revision != result["revision"]:
            products = self.env["product.product"].search([
                ("id", "in", product_ids), ("available_in_pos", "=", True),
                ("company_id", "in", [False, self.company_id.id]),
            ])
            lists = self._get_available_pricelists()
            # Include referenced base pricelists already allowed by the native POS loader.
            pending = lists
            while pending:
                bases = pending.item_ids.base_pricelist_id - lists
                bases = bases.filtered(lambda p: not p.company_id or p.company_id == self.company_id)
                lists |= bases
                pending = bases
            domain = [("pricelist_id", "in", lists.ids),
                      "|", ("product_id", "=", False), ("product_id", "in", products.ids),
                      "|", ("product_tmpl_id", "=", False), ("product_tmpl_id", "in", products.product_tmpl_id.ids)]
            Item = self.env["product.pricelist.item"]
            result["rules"] = Item.search_read(domain, ["id", *Item._load_pos_data_fields(self.id)], load=False)
        _logger.debug("[POS_AUTO_PRICE][SNAPSHOT][END] config_id=%s changed=%s", self.id, result["rules"] is not None)
        return result
