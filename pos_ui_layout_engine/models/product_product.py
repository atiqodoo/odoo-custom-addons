# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger("pos_ui_layout_engine.product_product")


class ProductProduct(models.Model):
    _inherit = "product.product"

    pos_ui_sold_qty = fields.Float(
        string="POS UI Sold Quantity",
        compute="_compute_pos_ui_sales_rank_defaults",
        help="Runtime variant POS sales quantity used by POS UI Layout Engine for debugging.",
    )
    pos_ui_sales_rank = fields.Integer(
        string="POS UI Sales Rank",
        compute="_compute_pos_ui_sales_rank_defaults",
        help="Runtime variant POS sales rank used by POS UI Layout Engine for debugging.",
    )
    pos_ui_template_sold_qty = fields.Float(
        string="POS UI Template Sold Quantity",
        compute="_compute_pos_ui_sales_rank_defaults",
        help="Runtime total POS sales quantity across all variants of the same product template.",
    )
    pos_ui_template_sales_rank = fields.Integer(
        string="POS UI Template Sales Rank",
        compute="_compute_pos_ui_sales_rank_defaults",
        help="Runtime product-template sales rank used by POS UI Layout Engine for product ordering.",
    )

    def _compute_pos_ui_sales_rank_defaults(self):
        for product in self:
            product.pos_ui_sold_qty = 0.0
            product.pos_ui_sales_rank = 0
            product.pos_ui_template_sold_qty = 0.0
            product.pos_ui_template_sales_rank = 0

    @staticmethod
    def _ui_sales_rank_domain(config):
        domain = [
            ("order_id.state", "in", ["paid", "done", "invoiced"]),
            ("product_id", "!=", False),
        ]

        if config.ui_sales_ranking_scope == "config":
            domain.append(("order_id.config_id", "=", config.id))
        elif config.ui_sales_ranking_scope == "session":
            session = config.current_session_id or config.session_ids.filtered(
                lambda pos_session: pos_session.state != "closed"
            )[:1]
            if session:
                domain.append(("order_id.session_id", "=", session.id))
            else:
                domain.append(("order_id.session_id", "=", 0))
        elif config.company_id:
            domain.append(("order_id.company_id", "=", config.company_id.id))

        if config.ui_sales_ranking_days:
            date_from = fields.Datetime.now() - timedelta(days=config.ui_sales_ranking_days)
            domain.append(("order_id.date_order", ">=", fields.Datetime.to_string(date_from)))
        return domain

    @classmethod
    def _ui_sales_rank_payload(cls, product):
        return {
            "id": product.get("id"),
            "name": product.get("display_name") or product.get("name"),
            "pos_ui_sold_qty": product.get("pos_ui_sold_qty", 0.0),
            "pos_ui_sales_rank": product.get("pos_ui_sales_rank", 0),
            "pos_ui_template_sold_qty": product.get("pos_ui_template_sold_qty", 0.0),
            "pos_ui_template_sales_rank": product.get("pos_ui_template_sales_rank", 0),
        }

    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        return fields_list + [
            "pos_ui_sold_qty",
            "pos_ui_sales_rank",
            "pos_ui_template_sold_qty",
            "pos_ui_template_sales_rank",
        ]

    def _process_pos_ui_product_product(self, products, config):
        super()._process_pos_ui_product_product(products, config)
        self._pos_ui_apply_sales_rank(products, config)

    def _pos_ui_sales_score_maps(self, product_ids, config):
        if not product_ids:
            return {}, {}, {}

        sales_by_product = {}
        sales_by_template = {}
        template_by_product = {}
        if config.ui_sort_products_by_sales:
            product_records = self.sudo().browse(product_ids).exists()
            template_ids = product_records.product_tmpl_id.ids
            all_variant_records = self.sudo().search([("product_tmpl_id", "in", template_ids)])
            all_variant_ids = all_variant_records.ids
            template_by_product = {
                product.id: product.product_tmpl_id.id
                for product in all_variant_records
                if product.product_tmpl_id
            }

            domain = self._ui_sales_rank_domain(config)
            domain.append(("product_id", "in", all_variant_ids))
            grouped = self.env["pos.order.line"].sudo().read_group(
                domain,
                ["qty:sum"],
                ["product_id"],
                lazy=False,
            )
            sales_by_product = {
                row["product_id"][0]: row.get("qty", 0.0)
                for row in grouped
                if row.get("product_id")
            }
            for product_id, sold_qty in sales_by_product.items():
                template_id = template_by_product.get(product_id)
                if template_id:
                    sales_by_template[template_id] = (
                        sales_by_template.get(template_id, 0.0) + sold_qty
                    )
        return sales_by_product, sales_by_template, template_by_product

    def _pos_ui_apply_sales_rank(self, products, config):
        if not products:
            return

        product_ids = [product["id"] for product in products if product.get("id")]
        if not product_ids:
            return

        sales_by_product, sales_by_template, template_by_product = self._pos_ui_sales_score_maps(
            product_ids,
            config.sudo(),
        )

        sorted_variant_scores = sorted(set(sales_by_product.values()), reverse=True)
        rank_by_variant_score = {
            score: index + 1 for index, score in enumerate(sorted_variant_scores)
        }
        sorted_template_scores = sorted(set(sales_by_template.values()), reverse=True)
        rank_by_template_score = {
            score: index + 1 for index, score in enumerate(sorted_template_scores)
        }

        for product in products:
            template_id = product.get("product_tmpl_id")
            if isinstance(template_id, (list, tuple)):
                template_id = template_id[0]
            elif isinstance(template_id, dict):
                template_id = template_id.get("id")

            sold_qty = float(sales_by_product.get(product["id"], 0.0))
            template_sold_qty = float(sales_by_template.get(template_id, 0.0))
            product["pos_ui_sold_qty"] = sold_qty
            product["pos_ui_sales_rank"] = (
                rank_by_variant_score.get(sold_qty, 0) if sold_qty else 0
            )
            product["pos_ui_template_sold_qty"] = template_sold_qty
            product["pos_ui_template_sales_rank"] = (
                rank_by_template_score.get(template_sold_qty, 0) if template_sold_qty else 0
            )

        top_products = sorted(
            products,
            key=lambda product: (
                -product.get("pos_ui_template_sold_qty", 0.0),
                product.get("display_name") or product.get("name") or "",
            ),
        )[:10]
        _logger.info(
            "[POS UI Layout][sales_rank] config='%s' (id=%s) enabled=%s days=%s scope=%s "
            "ranked_variants=%s ranked_templates=%s top_template_products=%s",
            config.name,
            config.id,
            config.ui_sort_products_by_sales,
            config.ui_sales_ranking_days,
            config.ui_sales_ranking_scope,
            len(sales_by_product),
            len(sales_by_template),
            [self._ui_sales_rank_payload(product) for product in top_products],
        )

    @api.model
    def get_pos_ui_sales_ranking_for_products(self, product_ids, config_id):
        config = self.env["pos.config"].sudo().browse(config_id).exists()
        if not config:
            _logger.warning(
                "[POS UI Layout][sales_rank_rpc] Missing POS config id=%s for products=%s",
                config_id,
                product_ids,
            )
            return {}

        products = self.sudo().browse(product_ids).exists()
        sales_by_product, sales_by_template, template_by_product = self._pos_ui_sales_score_maps(
            products.ids,
            config,
        )
        sorted_variant_scores = sorted(set(sales_by_product.values()), reverse=True)
        rank_by_variant_score = {
            score: index + 1 for index, score in enumerate(sorted_variant_scores)
        }
        sorted_template_scores = sorted(set(sales_by_template.values()), reverse=True)
        rank_by_template_score = {
            score: index + 1 for index, score in enumerate(sorted_template_scores)
        }

        payload = {}
        for product in products:
            template_id = template_by_product.get(product.id, product.product_tmpl_id.id)
            sold_qty = float(sales_by_product.get(product.id, 0.0))
            template_sold_qty = float(sales_by_template.get(template_id, 0.0))
            payload[product.id] = {
                "pos_ui_sold_qty": sold_qty,
                "pos_ui_sales_rank": rank_by_variant_score.get(sold_qty, 0) if sold_qty else 0,
                "pos_ui_template_sold_qty": template_sold_qty,
                "pos_ui_template_sales_rank": (
                    rank_by_template_score.get(template_sold_qty, 0)
                    if template_sold_qty
                    else 0
                ),
            }

        top_payload = sorted(
            payload.items(),
            key=lambda item: (-item[1]["pos_ui_template_sold_qty"], item[0]),
        )[:10]
        _logger.info(
            "[POS UI Layout][sales_rank_rpc] config='%s' (id=%s) days=%s scope=%s "
            "requested=%s returned=%s top=%s",
            config.name,
            config.id,
            config.ui_sales_ranking_days,
            config.ui_sales_ranking_scope,
            len(product_ids),
            len(payload),
            top_payload,
        )
        return payload
