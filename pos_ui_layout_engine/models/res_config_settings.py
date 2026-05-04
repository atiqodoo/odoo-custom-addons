# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger("pos_ui_layout_engine.res_config_settings")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ui_layout_mode = fields.Selection(
        related="pos_config_id.ui_layout_mode",
        readonly=False,
    )
    ui_density = fields.Selection(
        related="pos_config_id.ui_density",
        readonly=False,
    )
    ui_font_weight = fields.Selection(
        related="pos_config_id.ui_font_weight",
        readonly=False,
    )
    product_flex = fields.Float(
        related="pos_config_id.product_flex",
        readonly=False,
    )
    order_flex = fields.Float(
        related="pos_config_id.order_flex",
        readonly=False,
    )
    ui_action_button_placement = fields.Selection(
        related="pos_config_id.ui_action_button_placement",
        readonly=False,
    )
    ui_sort_products_by_sales = fields.Boolean(
        related="pos_config_id.ui_sort_products_by_sales",
        readonly=False,
    )
    ui_sales_ranking_days = fields.Integer(
        related="pos_config_id.ui_sales_ranking_days",
        readonly=False,
    )
    ui_sales_ranking_scope = fields.Selection(
        related="pos_config_id.ui_sales_ranking_scope",
        readonly=False,
    )

    def set_values(self):
        for settings in self:
            if settings.pos_config_id:
                _logger.info(
                    "[POS UI Layout][settings] Saving layout settings for POS config '%s' (id=%s): "
                    "layout=%s density=%s weight=%s product_flex=%s order_flex=%s "
                    "action_buttons=%s sort_by_sales=%s ranking_days=%s ranking_scope=%s",
                    settings.pos_config_id.name,
                    settings.pos_config_id.id,
                    settings.ui_layout_mode,
                    settings.ui_density,
                    settings.ui_font_weight,
                    settings.product_flex,
                    settings.order_flex,
                    settings.ui_action_button_placement,
                    settings.ui_sort_products_by_sales,
                    settings.ui_sales_ranking_days,
                    settings.ui_sales_ranking_scope,
                )
        return super().set_values()
