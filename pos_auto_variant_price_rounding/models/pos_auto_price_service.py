# -*- coding: utf-8 -*-

import logging
import math

from odoo import api, fields, models
from odoo.tools.float_utils import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class PosAutoPriceService(models.AbstractModel):
    _name = "pos.auto.variant.price.service"
    _description = "POS Auto Variant Price Rounding Service"

    _SKIP_CONTEXT_KEY = "skip_pos_auto_variant_price"

    def process_products(self, products, old_cost_by_product=None, trigger="cost_write", source=None):
        old_cost_by_product = old_cost_by_product or {}
        config = self._get_active_config()
        _logger.debug(
            "[POS_AUTO_PRICE] process start trigger=%s source=%s products=%s config=%s",
            trigger,
            source.display_name if source else None,
            products.ids,
            config.id if config else None,
        )
        for product in products.exists():
            old_cost = old_cost_by_product.get(product.id)
            self._process_product(product, old_cost, trigger, source, config)

    def _get_active_config(self):
        return self.env["pos.config"].sudo().search(
            [
                ("auto_variant_price_enabled", "=", True),
                ("company_id", "=", self.env.company.id),
            ],
            order="id",
            limit=1,
        )

    def _trigger_enabled(self, config, trigger):
        if not config or not config.auto_variant_price_enabled:
            return False
        return {
            "receipt": config.auto_variant_price_on_receipt,
            "landed_cost": config.auto_variant_price_on_landed_cost,
            "vendor_bill": config.auto_variant_price_on_vendor_bill,
            "manual_cost": config.auto_variant_price_on_manual_cost,
            "cost_write": config.auto_variant_price_on_manual_cost,
        }.get(trigger, False)

    def _inclusive_cost(self, product, base_cost, config):
        if base_cost is None:
            base_cost = product.standard_price or 0.0
        if config and config.auto_variant_price_include_vat:
            return base_cost * (1.0 + ((config.auto_variant_price_vat_rate or 0.0) / 100.0))
        return base_cost

    def _round_up(self, amount, step):
        if float_is_zero(amount, precision_digits=6):
            return 0.0
        return math.ceil(amount / step) * step

    def _process_product(self, product, old_cost, trigger, source, config):
        product = product.with_company(product.company_id or self.env.company)
        new_cost = product.standard_price or 0.0
        old_inclusive = self._inclusive_cost(product, old_cost, config)
        new_inclusive = self._inclusive_cost(product, new_cost, config)
        old_sale = product.lst_price or 0.0
        log_vals = self._base_log_vals(
            product, config, trigger, source, old_cost, new_cost, old_inclusive, new_inclusive, old_sale
        )

        if not self._trigger_enabled(config, trigger):
            _logger.info(
                "[POS_AUTO_PRICE] disabled product=%s trigger=%s old_cost=%s new_cost=%s",
                product.display_name,
                trigger,
                old_cost,
                new_cost,
            )
            self._create_log(dict(log_vals, status="disabled", message="Auto price update is disabled for this trigger."))
            return

        step = config.auto_variant_price_rounding_step or 0.0
        if step <= 0.0:
            _logger.warning("[POS_AUTO_PRICE] invalid rounding step config=%s step=%s", config.id, step)
            self._create_log(dict(log_vals, status="invalid_rule", message="Rounding step must be greater than zero."))
            return

        baseline = product.pos_auto_price_last_inclusive_cost
        if float_is_zero(baseline, precision_digits=6):
            baseline = old_inclusive
        difference = new_inclusive - baseline
        log_vals["cost_difference"] = difference

        if float_compare(difference, 0.0, precision_digits=6) <= 0:
            status = "duplicate" if float_compare(new_inclusive, baseline, precision_digits=6) == 0 else "no_increase"
            _logger.info(
                "[POS_AUTO_PRICE] no adjustment product=%s trigger=%s baseline=%s new_inclusive=%s status=%s",
                product.display_name,
                trigger,
                baseline,
                new_inclusive,
                status,
            )
            if config.auto_variant_price_log_no_change:
                self._create_log(dict(log_vals, status=status, message="Inclusive cost did not rise above the last processed cost."))
            return

        rounded_increase = self._round_up(difference, step)
        pricelist_items = self._find_pos_pricelist_items(product, config)
        primary_pricelist_item = pricelist_items[:1]
        old_pos_price = primary_pricelist_item.fixed_price if primary_pricelist_item else old_sale
        new_sale = old_sale + rounded_increase
        new_pos_price = old_pos_price + rounded_increase
        log_vals.update(
            {
                "rounded_increase": rounded_increase,
                "new_sale_price": new_sale,
                "old_pricelist_price": old_pos_price,
                "new_pricelist_price": new_pos_price,
                "pricelist_item_id": primary_pricelist_item.id if primary_pricelist_item else False,
                **self._profit_vals(old_pos_price, new_pos_price, old_inclusive, new_inclusive),
            }
        )
        _logger.info(
            "[POS_AUTO_PRICE] adjusting product=%s trigger=%s old_sale=%s new_sale=%s old_pos_price=%s new_pos_price=%s baseline_cost=%s new_cost=%s diff=%s rounded=%s",
            product.display_name,
            trigger,
            old_sale,
            new_sale,
            old_pos_price,
            new_pos_price,
            baseline,
            new_inclusive,
            difference,
            rounded_increase,
        )
        try:
            product.with_context(**{self._SKIP_CONTEXT_KEY: True}).sudo().write(
                {
                    "lst_price": new_sale,
                    "pos_auto_price_last_inclusive_cost": new_inclusive,
                    "pos_auto_price_last_sale_price": new_sale,
                }
            )
            updated_items = self._update_pos_pricelists(product, config, pricelist_items, rounded_increase, new_pos_price)
            log = self._create_log(dict(log_vals, status="adjusted", message="Selling price increased by rounded cost increase."))
            if updated_items:
                log.sudo().write({
                    "message": "%s Updated pricelist item ids: %s" % (
                        log.message or "",
                        ", ".join(str(item_id) for item_id in updated_items.ids),
                    )
                })
            product.with_context(**{self._SKIP_CONTEXT_KEY: True}).sudo().write({"pos_auto_price_last_log_id": log.id})
        except Exception as exc:
            _logger.exception("[POS_AUTO_PRICE] failed product=%s", product.display_name)
            self._create_log(dict(log_vals, status="error", message=str(exc)))

    def _base_log_vals(self, product, config, trigger, source, old_cost, new_cost, old_inclusive, new_inclusive, old_sale):
        return {
            "name": "%s - %s" % (product.display_name, trigger),
            "product_id": product.id,
            "company_id": (product.company_id or self.env.company).id,
            "pos_config_id": config.id if config else False,
            "changed_by_id": self.env.user.id,
            "trigger": trigger,
            "source_model": source._name if source else False,
            "source_res_id": source.id if source else False,
            "source_name": source.display_name if source else False,
            "old_cost": old_cost or 0.0,
            "new_cost": new_cost or 0.0,
            "old_inclusive_cost": old_inclusive or 0.0,
            "new_inclusive_cost": new_inclusive or 0.0,
            "old_sale_price": old_sale or 0.0,
            "new_sale_price": old_sale or 0.0,
            "old_pricelist_price": 0.0,
            "new_pricelist_price": 0.0,
            "pricelist_item_id": False,
            **self._profit_vals(old_sale or 0.0, old_sale or 0.0, old_inclusive or 0.0, new_inclusive or 0.0),
            "rounding_step": config.auto_variant_price_rounding_step if config else 0.0,
            "vat_rate": config.auto_variant_price_vat_rate if config else 0.0,
            "include_vat": config.auto_variant_price_include_vat if config else False,
        }

    def _profit_vals(self, old_price, new_price, old_cost, new_cost):
        old_profit = (old_price or 0.0) - (old_cost or 0.0)
        new_profit = (new_price or 0.0) - (new_cost or 0.0)
        old_percent = old_profit / old_price * 100.0 if old_price else 0.0
        new_percent = new_profit / new_price * 100.0 if new_price else 0.0
        return {
            "old_profit_amount": old_profit,
            "new_profit_amount": new_profit,
            "profit_amount_change": new_profit - old_profit,
            "old_profit_percent": old_percent,
            "new_profit_percent": new_percent,
            "profit_percent_change": new_percent - old_percent,
        }

    def _target_pricelists(self, config):
        if not config or not config.auto_variant_price_update_pricelist:
            return self.env["product.pricelist"]
        if config.auto_variant_price_pricelist_scope == "available":
            return config._get_available_pricelists()
        return config.pricelist_id

    def _find_pos_pricelist_items(self, product, config):
        pricelists = self._target_pricelists(config)
        if not pricelists:
            return self.env["product.pricelist.item"]
        now = fields.Datetime.now()
        return self.env["product.pricelist.item"].sudo().search(
            [
                ("pricelist_id", "in", pricelists.ids),
                ("compute_price", "=", "fixed"),
                "|",
                ("date_start", "=", False),
                ("date_start", "<=", now),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", now),
                "|",
                "&",
                ("applied_on", "=", "0_product_variant"),
                ("product_id", "=", product.id),
                "&",
                ("applied_on", "=", "1_product"),
                ("product_tmpl_id", "=", product.product_tmpl_id.id),
            ],
            order="pricelist_id, applied_on, min_quantity desc, id",
        )

    def _update_pos_pricelists(self, product, config, items, rounded_increase, fallback_new_price):
        if not config or not config.auto_variant_price_update_pricelist:
            return self.env["product.pricelist.item"]
        if items:
            updated_items = self.env["product.pricelist.item"]
            for item in items:
                new_price = (item.fixed_price or 0.0) + rounded_increase
                _logger.info(
                    "[POS_AUTO_PRICE] updating pricelist item=%s pricelist=%s product=%s old_fixed_price=%s new_fixed_price=%s",
                    item.id,
                    item.pricelist_id.display_name,
                    product.display_name,
                    item.fixed_price,
                    new_price,
                )
                item.sudo().write({"fixed_price": new_price})
                updated_items |= item
            return updated_items
        pricelists = self._target_pricelists(config)
        pricelist = pricelists[:1]
        if not pricelist:
            _logger.debug("[POS_AUTO_PRICE] no POS pricelist configured for config=%s", config.id)
            return self.env["product.pricelist.item"]
        item = self.env["product.pricelist.item"].sudo().create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "0_product_variant",
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_id": product.id,
                "compute_price": "fixed",
                "fixed_price": fallback_new_price,
            }
        )
        _logger.info(
            "[POS_AUTO_PRICE] created pricelist item=%s pricelist=%s product=%s fixed_price=%s",
            item.id,
            pricelist.display_name,
            product.display_name,
            fallback_new_price,
        )
        return item

    @api.model
    def _create_log(self, vals):
        _logger.debug("[POS_AUTO_PRICE] log vals=%s", vals)
        return self.env["pos.auto.variant.price.log"].sudo().create(vals)
