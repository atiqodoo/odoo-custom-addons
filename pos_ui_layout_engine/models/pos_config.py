# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger("pos_ui_layout_engine.pos_config")

LAYOUT_FIELDS = {
    "ui_layout_mode",
    "ui_density",
    "ui_font_weight",
    "product_flex",
    "order_flex",
    "ui_action_button_placement",
    "ui_sort_products_by_sales",
    "ui_sales_ranking_days",
    "ui_sales_ranking_scope",
}


class PosConfig(models.Model):
    _inherit = "pos.config"

    ui_layout_mode = fields.Selection(
        selection=[
            ("default", "Default"),
            ("wide", "Wide"),
            ("split", "Split"),
        ],
        string="POS Layout Mode",
        default="default",
        required=True,
        help="Controls the desktop layout treatment for the POS product screen.",
    )

    ui_density = fields.Selection(
        selection=[
            ("compact", "Compact"),
            ("normal", "Normal"),
            ("large", "Large"),
        ],
        string="POS UI Density",
        default="normal",
        required=True,
        help="Controls POS font sizing and spacing density.",
    )

    ui_font_weight = fields.Selection(
        selection=[
            ("normal", "Normal"),
            ("bold", "Bold"),
        ],
        string="POS Font Weight",
        default="normal",
        required=True,
        help="Controls whether POS screen text uses normal or stronger font weight.",
    )

    product_flex = fields.Float(
        string="Product Panel Flex",
        default=3.0,
        digits=(16, 2),
        help="Desktop flex ratio for the product panel. Recommended range: 0.50 to 10.00.",
    )

    order_flex = fields.Float(
        string="Order Panel Flex",
        default=2.0,
        digits=(16, 2),
        help="Desktop flex ratio for the order panel. Recommended range: 0.50 to 10.00.",
    )

    ui_action_button_placement = fields.Selection(
        selection=[
            ("popup", "Keep in Actions Popup"),
            ("core_bar", "Move Standard Actions to Bottom Bar"),
            ("all_bar", "Move All Known Actions to Bottom Bar"),
        ],
        string="POS Action Button Placement",
        default="popup",
        required=True,
        help=(
            "Controls whether buttons normally shown inside the Actions popup are promoted "
            "to the bottom control bar next to Customer, Internal Note, and Clear All."
        ),
    )

    ui_sort_products_by_sales = fields.Boolean(
        string="Sort POS Products by Sales",
        default=True,
        help=(
            "When enabled, products in the POS product pane are ordered by quantity sold "
            "from highest to lowest after normal category/search filtering."
        ),
    )

    ui_sales_ranking_days = fields.Integer(
        string="Sales Ranking Window (Days)",
        default=90,
        help=(
            "Number of recent days used to rank best-selling products. Set to 0 to use all "
            "available POS sales history."
        ),
    )

    ui_sales_ranking_scope = fields.Selection(
        selection=[
            ("config", "This POS Shop Only"),
            ("company", "All POS Shops in Company"),
            ("session", "Current Session Only"),
        ],
        string="Sales Ranking Scope",
        default="config",
        required=True,
        help="Controls whether product sales ranking is calculated for this POS shop, the whole company, or only the current POS session.",
    )

    @api.constrains("product_flex", "order_flex")
    def _check_ui_flex_ratios(self):
        for config in self:
            for field_name, label in [
                ("product_flex", "Product Panel Flex"),
                ("order_flex", "Order Panel Flex"),
            ]:
                value = getattr(config, field_name)
                if not 0.5 <= value <= 10.0:
                    _logger.warning(
                        "[POS UI Layout][constraint] Invalid %s=%s on POS config '%s' (id=%s).",
                        field_name,
                        value,
                        config.name,
                        config.id,
                    )
                    raise ValidationError(
                        "%s must be between 0.50 and 10.00 for POS '%s'."
                        % (label, config.name)
                    )

    @api.constrains("ui_sales_ranking_days")
    def _check_ui_sales_ranking_days(self):
        for config in self:
            if config.ui_sales_ranking_days < 0:
                _logger.warning(
                    "[POS UI Layout][constraint] Invalid ui_sales_ranking_days=%s on POS config '%s' (id=%s).",
                    config.ui_sales_ranking_days,
                    config.name,
                    config.id,
                )
                raise ValidationError(
                    "Sales Ranking Window must be 0 or greater for POS '%s'." % config.name
                )

    def _layout_debug_payload(self):
        self.ensure_one()
        return {
            "ui_layout_mode": self.ui_layout_mode,
            "ui_density": self.ui_density,
            "ui_font_weight": self.ui_font_weight,
            "product_flex": self.product_flex,
            "order_flex": self.order_flex,
            "ui_action_button_placement": self.ui_action_button_placement,
            "ui_sort_products_by_sales": self.ui_sort_products_by_sales,
            "ui_sales_ranking_days": self.ui_sales_ranking_days,
            "ui_sales_ranking_scope": self.ui_sales_ranking_scope,
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record, vals in zip(records, vals_list):
            if LAYOUT_FIELDS & set(vals):
                _logger.info(
                    "[POS UI Layout][create] POS config '%s' (id=%s) layout values: %s",
                    record.name,
                    record.id,
                    record._layout_debug_payload(),
                )
        return records

    def write(self, vals):
        tracked_vals = {key: vals[key] for key in LAYOUT_FIELDS & set(vals)}
        if tracked_vals:
            for record in self:
                _logger.info(
                    "[POS UI Layout][write] POS config '%s' (id=%s) updating layout fields: %s",
                    record.name,
                    record.id,
                    tracked_vals,
                )
        result = super().write(vals)
        if tracked_vals:
            for record in self:
                _logger.debug(
                    "[POS UI Layout][write] POS config '%s' (id=%s) final layout values: %s",
                    record.name,
                    record.id,
                    record._layout_debug_payload(),
                )
        return result
