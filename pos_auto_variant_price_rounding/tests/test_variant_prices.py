from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged, new_test_user
from odoo.addons.stock_account.tests.test_anglo_saxon_valuation_reconciliation_common import ValuationReconciliationTestCommon


@tagged("post_install", "-at_install")
class TestVariantPrices(ValuationReconciliationTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["pos.config"].search([]).write({"auto_variant_price_enabled": False})
        cls.pricelist = cls.env["product.pricelist"].create({
            "name": "Variant price test", "company_id": cls.env.company.id,
            "currency_id": cls.env.company.currency_id.id,
        })
        cls.config = cls.env["pos.config"].create({
            "name": "Variant price test", "journal_id": cls.company_data["default_journal_sale"].id,
            "invoice_journal_id": cls.company_data["default_journal_sale"].id,
            "pricelist_id": cls.pricelist.id, "use_pricelist": True,
            "available_pricelist_ids": [Command.set(cls.pricelist.ids)],
            "auto_variant_price_enabled": True, "auto_variant_price_rounding_step": 50,
        })
        attribute = cls.env["product.attribute"].create({"name": "Test shade", "create_variant": "always"})
        shades = cls.env["product.attribute.value"].create([
            {"name": name, "attribute_id": attribute.id} for name in ("White", "Accent")
        ])
        cls.template = cls.env["product.template"].create({
            "name": "Variant pricing test", "list_price": 1, "available_in_pos": True,
            "supplier_taxes_id": False, "taxes_id": False,
            "attribute_line_ids": [Command.create({"attribute_id": attribute.id,
                                                   "value_ids": [Command.set(shades.ids)]})],
        })
        cls.product, cls.sibling = cls.template.product_variant_ids.sorted("id")
        cls.template.product_variant_ids.with_context(disable_auto_svl=True).write({"standard_price": 100})
        cls.service = cls.env["pos.auto.variant.price.service"]
        cls.tax = cls.env["account.tax"].create({
            "name": "Purchase tax 16", "amount": 16, "type_tax_use": "purchase",
            "amount_type": "percent", "company_id": cls.env.company.id,
        })

    def _rule(self, price=200, variant=None, **values):
        return self.env["product.pricelist.item"].create(dict(
            pricelist_id=self.pricelist.id, applied_on="0_product_variant" if variant else "1_product",
            product_id=variant.id if variant else False, product_tmpl_id=self.template.id,
            compute_price="fixed", fixed_price=price, **values))

    def _increase(self, cost=110, source=None):
        self.product.with_context(disable_auto_svl=True).write({"standard_price": cost})
        self.service._process_products(self.product, {self.product.id: 100}, trigger="vendor_bill", source=source)

    def _price(self, product=None, quantity=1):
        return self.pricelist._get_product_price(product or self.product, quantity=quantity)

    def test_template_rule_is_overridden_only_for_affected_variant(self):
        shared = self._rule()
        self._increase()
        self.assertEqual(shared.fixed_price, 200)
        self.assertEqual(self._price(), 250)
        self.assertEqual(self._price(self.sibling), 200)
        self.assertEqual(self.template.list_price, 1)
        self.assertEqual(self.product.standard_price, 110)
        self.assertFalse(self.product.stock_valuation_layer_ids)
        self.assertEqual(self.env["pos.auto.variant.price.state"].search_count([
            ("product_id", "=", self.product.id), ("pricelist_id", "=", self.pricelist.id)]), 1)

    def test_existing_variant_rule_and_quantity_tiers(self):
        self._rule(200, self.product)
        tier = self._rule(180, self.product, min_quantity=10)
        self._increase()
        self.assertEqual(self._price(quantity=1), 250)
        self.assertEqual(self._price(quantity=10), 230)
        self.assertEqual(tier.fixed_price, 230)

    def test_shared_quantity_tiers_preserved(self):
        self._rule(200)
        self._rule(180, min_quantity=10)
        self._increase()
        self.assertEqual(self._price(quantity=1), 250)
        self.assertEqual(self._price(quantity=10), 230)
        self.assertEqual(self._price(self.sibling, 10), 180)

    def test_repeat_and_decrease_do_not_adjust(self):
        rule = self._rule(200, self.product)
        self._increase()
        self._increase()
        self._increase(105)
        self.assertEqual(rule.fixed_price, 250)

    def test_purchase_tax_and_price_included_tax(self):
        self.product.supplier_taxes_id = self.tax
        self.assertAlmostEqual(self.service._inclusive_cost(self.product, 100, self.config, self.tax), 116)
        self.tax.price_include_override = "tax_included"
        self.assertAlmostEqual(self.service._inclusive_cost(self.product, 100, self.config, self.tax), 116)
        rule = self._rule(200, self.product)
        self._increase(145)
        self.assertEqual(rule.fixed_price, 300)  # 45 * 1.16 = 52.2, rounded to 100

    def test_bill_tax_overrides_product_tax_and_no_accounting_writes(self):
        self.product.supplier_taxes_id = self.tax
        vendor = self.env["res.partner"].create({"name": "Variant test vendor"})
        bill = self.env["account.move"].create({
            "move_type": "in_invoice", "partner_id": vendor.id, "invoice_date": fields.Date.today(),
            "invoice_line_ids": [Command.create({"product_id": self.product.id, "quantity": 1,
                "price_unit": 100, "tax_ids": [Command.clear()],
                "account_id": self.company_data["default_account_expense"].id})],
        })
        before = bill.line_ids.read(["balance", "amount_currency", "tax_ids"])
        rule = self._rule(200, self.product)
        self._increase(145, bill)
        self.assertEqual(rule.fixed_price, 250)  # Bill is tax-exempt: increase is 45.
        self.assertEqual(before, bill.line_ids.read(["balance", "amount_currency", "tax_ids"]))
        self.assertEqual(bill.state, "draft")

    def test_formula_preserved_and_missing_rule_requires_opt_in(self):
        rule = self._rule(200, self.product)
        rule.write({"compute_price": "percentage", "percent_price": 10})
        self._increase()
        self.assertEqual(rule.compute_price, "percentage")
        self.assertFalse(self.env["pos.auto.variant.price.state"].search([("product_id", "=", self.product.id)]))
        rule.unlink()
        self._increase()
        self.assertFalse(self.pricelist.item_ids)
        self.config.auto_variant_price_allow_sale_fallback = True
        self._increase()
        self.assertEqual(self._price(), 51)

    def test_shared_pricelist_updated_once_across_configs(self):
        self.config.copy({"name": "Second price test"})
        rule = self._rule(200, self.product)
        self._increase()
        self.assertEqual(rule.fixed_price, 250)

    def test_failure_rolls_back_rule_changes_and_baseline(self):
        rule = self._rule(200, self.product)
        with patch.object(type(self.service), "_log", side_effect=RuntimeError("test rollback")):
            with self.assertRaises(RuntimeError):
                self._increase()
        self.assertEqual(rule.fixed_price, 200)
        self.assertFalse(self.env["pos.auto.variant.price.state"].search([("product_id", "=", self.product.id)]))

    def test_snapshot_access_and_revision_create_write_delete(self):
        user = new_test_user(self.env, login="variant_cashier", groups="base.group_user,point_of_sale.group_pos_user")
        config = self.config.with_user(user)
        first = config.get_variant_price_snapshot(self.product.ids)
        rule = self._rule(200, self.product)
        second = config.get_variant_price_snapshot(self.product.ids, first["revision"])
        self.assertNotEqual(first["revision"], second["revision"])
        self.assertIn(rule.id, [r["id"] for r in second["rules"]])
        self.assertNotIn("standard_price", second["rules"][0])
        self.assertIsNone(config.get_variant_price_snapshot(self.product.ids, second["revision"])["rules"])
        rule.fixed_price = 250
        third = config.get_variant_price_snapshot(self.product.ids, second["revision"])
        self.assertNotEqual(third["revision"], second["revision"])
        rule.unlink()
        self.assertEqual(config.get_variant_price_snapshot(self.product.ids, third["revision"])["rules"], [])
        outsider = new_test_user(self.env, login="variant_outsider", groups="base.group_user")
        with self.assertRaises(AccessError):
            self.config.with_user(outsider).get_variant_price_snapshot(self.product.ids)

    def test_other_company_product_is_not_adjusted(self):
        company = self.env["res.company"].create({"name": "Other variant company"})
        other = self.env["product.product"].create({"name": "Other variant", "company_id": company.id})
        self.service._process_products(other, {other.id: 0}, trigger="vendor_bill")
        self.assertFalse(self.env["pos.auto.variant.price.state"].search([("product_id", "=", other.id)]))

    def test_rounding_boundaries(self):
        self.assertEqual(self.service._round_up(50.00000000000001, 50), 50)
        self.assertEqual(self.service._round_up(50.01, 50), 100)
        self.assertEqual(self.service._round_up(0.0998, 50), 50)

    def test_conflicting_shared_config_policy_skips_adjustment(self):
        self.config.copy({"name": "Conflicting policy", "auto_variant_price_rounding_step": 100})
        rule = self._rule(200, self.product)
        self._increase()
        self.assertEqual(rule.fixed_price, 200)
        log = self.env["pos.auto.variant.price.log"].search([("product_id", "=", self.product.id)], limit=1)
        self.assertEqual(log.status, "invalid_rule")

    def test_other_company_logs_are_hidden(self):
        company = self.env["res.company"].create({"name": "Private price company"})
        log = self.env["pos.auto.variant.price.log"].sudo().create({
            "product_id": self.product.id, "company_id": company.id,
            "trigger": "vendor_bill", "status": "disabled",
        })
        user = new_test_user(self.env, login="variant_log_reader", groups="base.group_user,point_of_sale.group_pos_user",
                             company_id=self.env.company.id, company_ids=[Command.set(self.env.company.ids)])
        self.assertFalse(self.env["pos.auto.variant.price.log"].with_user(user).search([("id", "=", log.id)]))

    def test_posted_bill_keeps_native_accounting_and_checks_after_post(self):
        self._rule(200, self.product)
        vendor = self.env["res.partner"].create({"name": "Posting test vendor"})
        bill = self.env["account.move"].create({
            "move_type": "in_invoice", "partner_id": vendor.id, "invoice_date": fields.Date.today(),
            "invoice_line_ids": [Command.create({"product_id": self.product.id, "quantity": 2,
                "price_unit": 100, "tax_ids": [Command.set(self.tax.ids)],
                "account_id": self.company_data["default_account_expense"].id})],
        })
        original = type(self.service)._process_products
        checked = []

        def check_after_post(service, products, **kwargs):
            checked.append(kwargs["source"].state)
            return original(service, products, **kwargs)

        with patch.object(type(self.service), "_process_products", check_after_post):
            bill.action_post()
        self.assertEqual(checked, ["posted"])
        self.assertEqual(bill.state, "posted")
        self.assertAlmostEqual(bill.amount_total, 232)
        self.assertAlmostEqual(sum(bill.line_ids.mapped("balance")), 0)
        self.assertEqual(self.product.standard_price, 100)
        self.assertEqual(self._price(), 200)
