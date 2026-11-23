import logging
import math

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.service.model import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


class PosAutoPriceService(models.AbstractModel):
    _name = "pos.auto.variant.price.service"
    _description = "POS Auto Variant Price Rounding Service"

    def _process_products(self, products, old_cost_by_product=None, trigger="cost_write", source=None):
        """Internal event boundary: cost snapshots must never be supplied over RPC."""
        configs = self.env["pos.config"].sudo().search([
            ("auto_variant_price_enabled", "=", True), ("company_id", "=", self.env.company.id),
        ], order="id")
        enabled = configs.filtered(lambda c: self._trigger_enabled(c, trigger))
        policies_by_pricelist = {}
        for config in enabled:
            for pricelist in self._target_pricelists(config):
                policies_by_pricelist.setdefault(pricelist.id, set()).add((
                    config.auto_variant_price_rounding_step, config.auto_variant_price_include_vat,
                    config.auto_variant_price_allow_sale_fallback,
                ))
        foreign_lists = self.env["product.pricelist"]
        for other_config in self.env["pos.config"].sudo().search([("company_id", "!=", self.env.company.id)]):
            foreign_lists |= other_config._get_available_pricelists()
        _logger.debug("[POS_AUTO_PRICE][PROCESS][START] company_id=%s trigger=%s product_ids=%s",
                      self.env.company.id, trigger, products.ids)
        for product in products.exists().sorted("id"):
            if product.company_id and product.company_id != self.env.company:
                continue
            # ORM has no row-lock API. Serialize competing events without changing costs.
            self.env.cr.execute("SELECT id FROM product_product WHERE id = %s FOR UPDATE", [product.id])
            handled = set()
            for config in configs:
                if not self._trigger_enabled(config, trigger):
                    self._log(product, config, trigger, source, "disabled", "Trigger disabled.")
                    continue
                for pricelist in self._target_pricelists(config).sorted("id"):
                    if pricelist.id in handled:
                        continue
                    handled.add(pricelist.id)
                    if len(policies_by_pricelist[pricelist.id]) > 1 or pricelist in foreign_lists:
                        self._log(product, config, trigger, source, "invalid_rule",
                                  "Shared pricelist has conflicting POS policies or is used by another company. Review its configuration.",
                                  pricelist_id=pricelist.id)
                        continue
                    try:
                        with self.env.cr.savepoint():
                            self._adjust_pricelist(product.with_company(self.env.company), config, pricelist,
                                                   (old_cost_by_product or {}).get(product.id), trigger, source)
                    except PG_CONCURRENCY_EXCEPTIONS_TO_RETRY:
                        raise  # Let Odoo retry the complete business transaction.
                    except Exception:
                        _logger.exception("[POS_AUTO_PRICE][ADJUST][ERROR] product_id=%s pricelist_id=%s",
                                          product.id, pricelist.id)
                        self._log(product, config, trigger, source, "error",
                                  "Price adjustment failed; no pricing changes from this adjustment were saved.",
                                  pricelist_id=pricelist.id)
        _logger.debug("[POS_AUTO_PRICE][PROCESS][END] company_id=%s trigger=%s", self.env.company.id, trigger)

    def _trigger_enabled(self, config, trigger):
        return bool(config.auto_variant_price_enabled and {
            "receipt": config.auto_variant_price_on_receipt,
            "landed_cost": config.auto_variant_price_on_landed_cost,
            "vendor_bill": config.auto_variant_price_on_vendor_bill,
            "manual_cost": config.auto_variant_price_on_manual_cost,
            "cost_write": config.auto_variant_price_on_manual_cost,
        }.get(trigger, False))

    def _target_pricelists(self, config):
        if not config.auto_variant_price_update_pricelist:
            return self.env["product.pricelist"]
        lists = config._get_available_pricelists() if config.auto_variant_price_pricelist_scope == "available" else config.pricelist_id
        return lists.filtered(lambda p: not p.company_id or p.company_id == self.env.company)

    def _purchase_taxes(self, product, source):
        """Document purchase taxes have already been fiscal-position mapped."""
        lines = self.env["account.move.line"]
        tax_field = "tax_ids"
        if source and source._name == "account.move":
            lines = source.invoice_line_ids.filtered(lambda l: l.product_id == product and l.display_type in (False, "product"))
        elif source and source._name == "stock.picking":
            lines = source.move_ids.purchase_line_id.filtered(lambda l: l.product_id == product)
            tax_field = "taxes_id"
        elif source and source._name == "stock.landed.cost":
            lines = source.picking_ids.move_ids.purchase_line_id.filtered(lambda l: l.product_id == product)
            tax_field = "taxes_id"
        if lines:
            signatures = {tuple(sorted(line[tax_field].ids)) for line in lines}
            if len(signatures) != 1:
                raise UserError("Several purchase tax treatments apply to this variant; review its pricing manually.")
            return lines[0][tax_field]
        return product.supplier_taxes_id.filtered(lambda t: t.company_id == self.env.company)

    def _inclusive_cost(self, product, cost, config, taxes):
        if not config.auto_variant_price_include_vat:
            return cost
        # Cost is exclusive even when a purchase tax is configured as price-included.
        return taxes.compute_all(cost, currency=self.env.company.currency_id, quantity=1,
                                 product=product, handle_price_include=False,
                                 rounding_method="round_globally")["total_included"]

    def _round_up(self, amount, step):
        ratio = amount / step
        nearest = round(ratio)
        return (nearest if abs(ratio - nearest) < 1e-10 else math.ceil(ratio)) * step

    def _adjust_pricelist(self, product, config, pricelist, old_cost, trigger, source):
        _logger.debug("[POS_AUTO_PRICE][ADJUST][START] product_id=%s pricelist_id=%s", product.id, pricelist.id)
        if config.auto_variant_price_rounding_step <= 0:
            self._log(product, config, trigger, source, "invalid_rule", "Rounding step must be positive.", pricelist_id=pricelist.id)
            return
        State = self.env["pos.auto.variant.price.state"].sudo()
        state = State.search([("product_id", "=", product.id), ("company_id", "=", self.env.company.id),
                              ("pricelist_id", "=", pricelist.id)], limit=1)
        if state:
            state.invalidate_recordset()
        new_cost = product.standard_price
        baseline = state.last_cost if state else (new_cost if old_cost is None else old_cost)
        taxes = self._purchase_taxes(product, source)
        old_inclusive = self._inclusive_cost(product, baseline, config, taxes)
        new_inclusive = self._inclusive_cost(product, new_cost, config, taxes)
        difference = new_inclusive - old_inclusive
        values = dict(pricelist_id=pricelist.id, old_cost=baseline, new_cost=new_cost,
                      old_inclusive_cost=old_inclusive, new_inclusive_cost=new_inclusive,
                      cost_difference=difference, include_vat=config.auto_variant_price_include_vat,
                      rounding_step=config.auto_variant_price_rounding_step,
                      tax_ids=[(6, 0, taxes.ids)], vat_rate=0)
        if float_compare(difference, 0, precision_digits=6) <= 0:
            if config.auto_variant_price_log_no_change:
                self._log(product, config, trigger, source, "duplicate" if abs(difference) < 1e-6 else "no_increase",
                          "Cost did not exceed the last processed cost. Both costs use the current purchase taxes.", **values)
            return
        now = fields.Datetime.now()
        rules = pricelist._get_applicable_rules(product, now)
        # Resolve native quantity tiers before creating overrides that change precedence.
        quantities = sorted({0.0, *(max(rule.min_quantity, 0) for rule in rules)})
        plans = []
        for quantity in quantities:
            price, rule_id = pricelist._get_product_price_rule(product, quantity=quantity, date=now)
            rule = self.env["product.pricelist.item"].sudo().browse(rule_id)
            if rule and rule.compute_price != "fixed":
                self._log(product, config, trigger, source, "invalid_rule",
                          "Formula/discount rules are preserved. Review this variant/pricelist manually.", **values)
                return
            if not rule and not config.auto_variant_price_allow_sale_fallback:
                self._log(product, config, trigger, source, "invalid_rule",
                          "No applicable rule. Standard sale-price fallback requires explicit enablement.", **values)
                return
            plans.append((quantity, price, rule))
        amount = self._round_up(difference, config.auto_variant_price_rounding_step)
        currency = self.env.company.currency_id
        today = fields.Date.context_today(self)
        amount = currency._convert(amount, pricelist.currency_id, self.env.company, today)
        updated = self.env["product.pricelist.item"]
        for quantity, price, rule in plans:
            if rule and rule in updated:
                continue
            new_price = price + amount
            if rule and rule.applied_on == "0_product_variant" and rule.product_id == product:
                item = rule
                item.write({"fixed_price": new_price})
            else:
                item = self.env["product.pricelist.item"].sudo().create({
                    "pricelist_id": pricelist.id, "applied_on": "0_product_variant", "product_id": product.id,
                    "product_tmpl_id": product.product_tmpl_id.id, "compute_price": "fixed", "fixed_price": new_price,
                    "min_quantity": quantity, "date_start": rule.date_start if rule else False,
                    "date_end": rule.date_end if rule else False,
                })
            updated |= item
            self._log(product, config, trigger, source, "adjusted",
                      "Variant fixed price adjusted; shared rules and accounting cost preserved.",
                      **values, rounded_increase=amount, old_pricelist_price=price, new_pricelist_price=new_price,
                      old_sale_price=product.lst_price, new_sale_price=product.lst_price,
                      pricelist_item_id=item.id, source_pricelist_item_id=rule.id,
                      **self._profit_vals(price, new_price,
                          currency._convert(old_inclusive, pricelist.currency_id, self.env.company, today),
                          currency._convert(new_inclusive, pricelist.currency_id, self.env.company, today)))
        if state:
            state.write({"last_cost": new_cost})
        else:
            State.create(dict(last_cost=new_cost, product_id=product.id, company_id=self.env.company.id, pricelist_id=pricelist.id))
        _logger.debug("[POS_AUTO_PRICE][ADJUST][END] product_id=%s pricelist_id=%s item_ids=%s increase=%s",
                      product.id, pricelist.id, updated.ids, amount)

    def _profit_vals(self, old_price, new_price, old_cost, new_cost):
        old_profit, new_profit = old_price - old_cost, new_price - new_cost
        old_percent = old_profit / old_price * 100 if old_price else 0
        new_percent = new_profit / new_price * 100 if new_price else 0
        return dict(old_profit_amount=old_profit, new_profit_amount=new_profit,
                    profit_amount_change=new_profit - old_profit, old_profit_percent=old_percent,
                    new_profit_percent=new_percent, profit_percent_change=new_percent - old_percent)

    def _log(self, product, config, trigger, source, status, message, **values):
        _logger.debug("[POS_AUTO_PRICE][DECISION][END] product_id=%s config_id=%s status=%s",
                      product.id, config.id, status)
        return self.env["pos.auto.variant.price.log"].sudo().create(dict(
            name="%s - %s" % (product.display_name, trigger), product_id=product.id,
            company_id=self.env.company.id, pos_config_id=config.id, changed_by_id=self.env.user.id,
            trigger=trigger, status=status, message=message,
            source_model=source._name if source else False, source_res_id=source.id if source else False,
            source_name=source.display_name if source else False, **values))
