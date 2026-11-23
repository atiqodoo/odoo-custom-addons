import json
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestLoyaltyAudit(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Audit customer"})
        cls.category = cls.env["product.category"].create({"name": "Audit paint"})
        cls.product = cls.env["product.product"].create({
            "name": "Audit paint", "type": "consu", "categ_id": cls.category.id,
            "list_price": 3800, "taxes_id": [Command.clear()],
        })
        cls.other_product = cls.env["product.product"].create({
            "name": "Audit brush", "type": "consu", "taxes_id": [Command.clear()],
        })
        cls.program = cls.env["loyalty.program"].create({
            "name": "Audit program", "program_type": "loyalty", "trigger": "auto", "applies_on": "both",
            "company_id": cls.env.company.id, "lpm_tier_earning_policy": "variant_rules_multiplier_fallback",
            "rule_ids": [Command.create({"reward_point_mode": "money", "reward_point_amount": 0.01,
                                          "minimum_qty": 0})],
            "reward_ids": [Command.create({"reward_type": "discount", "discount_mode": "per_point",
                                            "discount": 1, "required_points": 1})],
        })
        cls.tier = cls.env["loyalty.tier"].create({
            "program_id": cls.program.id, "name": "CHUI", "code": "AUDIT", "multiplier": 0.8,
            "condition_ids": [Command.create({"condition_type": "points_balance", "operator": ">",
                                               "value_float": 500})],
            "product_rule_ids": [Command.create({"categ_id": cls.category.id,
                "uom_id": cls.product.uom_id.id, "points_per_qty": 20})],
        })
        cls.card = cls.env["loyalty.card"].create({
            "program_id": cls.program.id, "partner_id": cls.partner.id, "points": 462.5,
        })
        cls.order = cls.env["sale.order"].create({
            "partner_id": cls.partner.id,
            "order_line": [Command.create({"product_id": cls.product.id, "product_uom_qty": 10,
                "price_unit": 3800, "tax_id": [Command.clear()]}),
                Command.create({"product_id": cls.other_product.id, "product_uom_qty": 2,
                    "price_unit": 100, "tax_id": [Command.clear()]}),
                Command.create({"display_type": "line_note", "name": "Audit informational note"})],
        })
        cls.config = cls.env["pos.config"].create({
            "name": "Audit POS", "journal_id": cls.company_data["default_journal_sale"].id,
            "invoice_journal_id": cls.company_data["default_journal_sale"].id,
            "payment_method_ids": [Command.clear()],
        })
        cls.session = cls.env["pos.session"].create({"config_id": cls.config.id})
        cls.auditor = new_test_user(cls.env, login="loyalty_auditor_test",
            groups="base.group_user,loyalty_points_manager.group_loyalty_auditor")
        cls.ordinary = new_test_user(cls.env, login="loyalty_ordinary_test", groups="base.group_user")

    def calculate(self, base=382):
        return self.env["loyalty.tier.engine"].lpm_apply_tier_earning_policy(
            self.partner, self.program, self.order, base,
        )

    def record(self, result, **kwargs):
        points = result["final_points"]
        history = self.env["loyalty.history"].create({
            "card_id": self.card.id, "description": "Audit test",
            "order_model": self.order._name, "order_id": self.order.id, "issued": points,
        })
        return self.env["loyalty.audit.event"]._record(
            history, self.order, result, event_key="test", trigger="test", **kwargs,
        )

    def make_pos(self, **values):
        return self.env["pos.order"].create({
            "session_id": self.session.id, "partner_id": self.partner.id,
            "amount_total": 38000, "amount_tax": 0, "amount_paid": 38000, "amount_return": 0,
            "lines": [Command.create({"product_id": self.product.id, "qty": 10, "price_unit": 3800,
                "price_subtotal": 38000, "price_subtotal_incl": 38000, "tax_ids": [Command.clear()]})],
            **values,
        })

    def test_gap_captures_actual_conditions_and_all_lines(self):
        result = self.calculate()
        self.assertEqual(result["final_points"], 382)
        event = self.record(result, before=462.5)
        self.assertEqual(event.reason, "no_tier_matched")
        self.assertEqual(event.condition_ids.actual, 462.5)
        self.assertFalse(event.condition_ids.passed)
        self.assertEqual(len(event.line_ids), 3)
        self.assertEqual(sum(event.line_ids.mapped("earned")), 382)
        self.assertEqual(event.balance_after, 844.5)
        self.assertEqual(event.history_id.audit_status, "captured")

    def test_matched_tier_records_rules_and_fallback(self):
        self.card.points = 600
        event = self.record(self.calculate(), before=600)
        paint = event.line_ids.filtered(lambda row: row.product_name == self.product.display_name)
        brush = event.line_ids.filtered(lambda row: row.product_name == self.other_product.display_name)
        self.assertEqual(paint.earned, 200)
        self.assertEqual(paint.method, "product_rule")
        self.assertEqual(brush.method, "multiplier_fallback")
        self.assertAlmostEqual(brush.earned, 1.6)
        self.assertIn('"points_per_qty": 20.0', paint.explanation)
        self.assertEqual(event.condition_ids.actual, 600)

    def test_snapshot_survives_policy_product_and_order_edits(self):
        self.card.points = 600
        event = self.record(self.calculate())
        snapshot = event.evidence_json
        values = event.line_ids.mapped("earned")
        self.tier.product_rule_ids.points_per_qty = 99
        self.product.name = "Changed later"
        self.order.order_line[0].product_uom_qty = 2
        self.card.points = 2000
        self.assertEqual(event.evidence_json, snapshot)
        self.assertEqual(event.line_ids.mapped("earned"), values)
        self.assertEqual(event.condition_ids.actual, 600)

    def test_base_only_and_order_rounding_reconcile(self):
        self.program.lpm_tier_earning_policy = "none"
        event = self.record(self.calculate(381.234567))
        self.assertAlmostEqual(sum(event.line_ids.mapped("earned")), event.issued, places=6)
        self.assertIn("allocation", event.line_ids[0].method.lower().replace("allocated", "allocation"))

    def test_retries_do_not_duplicate_evidence(self):
        event = self.record(self.calculate())
        duplicate = self.env["loyalty.audit.event"]._record(
            event.history_id, self.order, self.calculate(), event_key="test", trigger="retry",
        )
        self.assertEqual(event, duplicate)
        self.assertEqual(len(event.history_id.audit_event_ids), 1)

    def test_legacy_preview_does_not_claim_original_calculation(self):
        history = self.env["loyalty.history"].create({
            "card_id": self.card.id, "description": "Legacy", "issued": 382,
            "order_model": self.order._name, "order_id": self.order.id,
        })
        self.assertEqual(history.audit_status, "unavailable")
        self.assertIn("Current source values only", history.current_source_lines_html)
        self.assertIn("Audit informational note", history.current_source_lines_html)
        self.assertFalse(history.audit_event_ids)

    def test_auditors_read_only_and_ordinary_users_denied(self):
        event = self.record(self.calculate())
        event.with_user(self.auditor).read(["issued"])
        for model, record in [("loyalty.audit.event", event), ("loyalty.audit.line", event.line_ids[0]),
                              ("loyalty.audit.condition", event.condition_ids)]:
            with self.assertRaises(AccessError):
                record.with_user(self.ordinary).read(["id"])
            with self.assertRaises(AccessError):
                record.with_user(self.auditor).unlink()
            with self.assertRaises(AccessError):
                self.env[model].with_user(self.auditor).create({})
        with self.assertRaises(AccessError):
            event.with_user(self.auditor).write({"issued": 99})

    def test_company_rules_cover_event_lines_conditions(self):
        event = self.record(self.calculate())
        event.company_id = self.env["res.company"].sudo().create({"name": "Other audit company"})
        for record in (event, event.line_ids, event.condition_ids):
            with self.assertRaises(AccessError):
                record.with_user(self.auditor).with_context(allowed_company_ids=self.env.company.ids).read(["id"])

    def test_history_removal_keeps_snapshot(self):
        event = self.record(self.calculate())
        event.history_id.unlink()
        self.assertTrue(event.exists())
        self.assertFalse(event.history_id)
        self.assertTrue(event.line_ids)

    def test_pos_award_and_retry(self):
        order = self.make_pos()
        vals = {"program_id": self.program.id, "points": 380, "won": 380, "spent": 0,
                "partner_id": self.partner.id}
        order.confirm_coupon_programs({str(self.card.id): vals})
        history = self.env["loyalty.history"].search([("order_model", "=", "pos.order"), ("order_id", "=", order.id)])
        self.assertEqual(history.issued, 380)
        self.assertEqual(history.audit_status, "captured")
        self.assertEqual(history.audit_event_ids.balance_before, 462.5)
        order.confirm_coupon_programs({str(self.card.id): vals})
        self.assertEqual(len(history.audit_event_ids), 1)
        self.assertEqual(self.card.points, 842.5)

    def test_pos_new_card_mapping(self):
        new_partner = self.partner.copy({"name": "New audit card customer"})
        order = self.make_pos(partner_id=new_partner.id)
        order.confirm_coupon_programs({-1: {"program_id": self.program.id, "points": 380,
            "won": 380, "spent": 0, "partner_id": new_partner.id}})
        history = self.env["loyalty.history"].search([("order_model", "=", "pos.order"), ("order_id", "=", order.id)])
        self.assertEqual(history.audit_status, "captured")
        self.assertTrue(history.card_id.id > 0)

    def test_pos_mixed_award_keeps_gross_movements(self):
        order = self.make_pos()
        order.lines = [Command.create({"product_id": self.other_product.id, "qty": 1, "price_unit": -20,
            "price_subtotal": -20, "price_subtotal_incl": -20, "is_reward_line": True,
            "coupon_id": self.card.id, "reward_id": self.program.reward_ids.id,
            "points_cost": 20, "tax_ids": [Command.clear()]})]
        order.confirm_coupon_programs({self.card.id: {"program_id": self.program.id,
            "points": 360, "won": 380, "spent": 20, "partner_id": self.partner.id}})
        history = self.env["loyalty.history"].search([("order_model", "=", "pos.order"), ("order_id", "=", order.id)])
        self.assertEqual((history.issued, history.used), (380, 20))
        self.assertEqual(self.card.points, 822.5)
        self.assertEqual(sum(history.audit_line_ids.mapped("used")), 20)

    def test_sale_award_appends_to_existing_redemption_history(self):
        history = self.env["loyalty.history"].create({"card_id": self.card.id, "description": "Redeem",
            "order_model": self.order._name, "order_id": self.order.id, "used": 10})
        self.env["loyalty.audit.event"]._record(history, self.order, event_key="redeem", trigger="redeem", before=472.5)
        self.order.coupon_point_ids = [Command.create({"coupon_id": self.card.id, "points": 382})]
        self.order._lpm_award_backend_loyalty_points(trigger="test")
        self.assertEqual(len(history.audit_event_ids), 2)
        self.assertEqual((history.issued, history.used), (382, 10))
        self.assertEqual(history.audit_status, "captured")

    def test_cod_collections_use_frozen_evidence_and_reconcile(self):
        self.card.points = 600
        order = self.make_pos(is_cod=True)
        with patch.object(type(order), "_lpm_cod_paid_total", return_value=19000):
            order._lpm_award_cod_payment_points({"amount": 19000})
        self.tier.product_rule_ids.points_per_qty = 99
        with patch.object(type(order), "_lpm_cod_paid_total", return_value=38000):
            order._lpm_award_cod_payment_points({"amount": 19000})
        histories = self.env["loyalty.history"].search([("order_model", "=", "pos.order"), ("order_id", "=", order.id)])
        self.assertEqual(sum(histories.mapped("issued")), 200)
        self.assertEqual(len(histories), 2)
        for history in histories:
            self.assertEqual(sum(history.audit_line_ids.mapped("earned")), history.issued)
            self.assertIn('"paid_ratio"', history.audit_event_ids.payment_details)
        with patch.object(type(order), "_lpm_cod_paid_total", return_value=38000):
            self.assertFalse(order._lpm_award_cod_payment_points({"amount": 19000}))

    def test_audit_failure_rolls_back_award(self):
        order = self.make_pos()
        before = self.card.points
        with self.assertRaisesRegex(RuntimeError, "audit failure"), self.cr.savepoint():
            with patch.object(type(self.env["loyalty.audit.event"]), "_record", side_effect=RuntimeError("audit failure")):
                order.confirm_coupon_programs({self.card.id: {"program_id": self.program.id,
                    "points": 380, "won": 380, "spent": 0, "partner_id": self.partner.id}})
        self.assertEqual(self.card.points, before)
        self.assertFalse(self.env["loyalty.history"].search([("order_model", "=", "pos.order"), ("order_id", "=", order.id)]))

    def test_standard_and_action_forms_show_audit(self):
        form = self.env["loyalty.history"].with_user(self.auditor).get_view(
            self.env.ref("loyalty.loyalty_history_form").id, "form",
        )
        self.assertIn("audit_line_ids", form["arch"])
        views = self.env.ref("loyalty_points_manager.action_lpm_loyalty_history_log").views
        self.assertEqual(views[0][1], "list")
        self.assertIn((self.env.ref("loyalty.loyalty_history_form").id, "form"), views)

    def test_zero_payment_retains_redemption_audit(self):
        order = self.make_pos(amount_total=0, amount_paid=0)
        order.confirm_coupon_programs({self.card.id: {"program_id": self.program.id,
            "points": -20, "won": 0, "spent": 20, "partner_id": self.partner.id}})
        history = self.env["loyalty.history"].search([("order_model", "=", "pos.order"), ("order_id", "=", order.id)])
        self.assertEqual((history.issued, history.used), (0, 20))
        self.assertEqual(self.card.points, 442.5)
        self.assertEqual(sum(history.audit_line_ids.mapped("earned")), 0)
        self.assertEqual(sum(history.audit_line_ids.mapped("used")), 20)

    def test_rpc_context_cannot_forge_calculation_evidence(self):
        order = self.make_pos()
        order = order.with_context(lpm_audit_coupons={str(self.card.id): {"won": 999999}}, lpm_audit_token="fake")
        order.confirm_coupon_programs({self.card.id: {"program_id": self.program.id,
            "points": 380, "won": 380, "spent": 0, "partner_id": self.partner.id,
            "_lpm_audit_result": {"final_points": 999999}}})
        history = self.env["loyalty.history"].search([("order_model", "=", "pos.order"), ("order_id", "=", order.id)])
        self.assertEqual(history.issued, 380)
        self.assertEqual(history.audit_event_ids.reason, "no_tier_matched")

    def test_partial_legacy_cod_evidence_is_labelled(self):
        event = self.record({"final_points": 100, "base_points": 380, "policy": "multiplier"})
        self.assertEqual(event.evidence_quality, "partial")
        self.assertEqual(event.history_id.audit_status, "partial")

    def test_current_source_preview_escapes_product_text(self):
        self.product.name = "<script>alert('audit')</script>"
        event = self.record(self.calculate())
        preview = event.history_id.current_source_lines_html
        self.assertNotIn("<script>", preview)
        self.assertIn("&lt;script&gt;", preview)

    def test_cancellation_records_actual_movement_and_retains_originals(self):
        event = self.record(self.calculate(), before=462.5)
        before = self.card.points
        self.card.points -= event.issued
        event.history_id.unlink()
        event._record_cancellation(self.order, {self.card.id: before})
        cancellations = self.env["loyalty.audit.event"].search([("trigger", "=", "Sales cancellation"),
            ("source_order_id", "=", self.order.id)])
        self.assertEqual(len(cancellations), 1)
        self.assertEqual(cancellations.issued, -event.issued)
        self.assertEqual(json.loads(cancellations.evidence_json)["difference"], 0)
        event._record_cancellation(self.order, {self.card.id: before})
        self.assertEqual(self.env["loyalty.audit.event"].search_count([("event_key", "=", cancellations.event_key)]), 1)

    def test_refund_signed_contributions_reconcile(self):
        self.program.lpm_tier_earning_policy = "none"
        self.order.order_line[0].product_uom_qty = -10
        event = self.record(self.calculate(-378))
        self.assertEqual(sum(event.line_ids.mapped("earned")), -378)

    def test_multiple_programs_keep_independent_events(self):
        second_program = self.program.copy({"name": "Second audit program", "lpm_tier_earning_policy": "none"})
        second_card = self.env["loyalty.card"].create({"program_id": second_program.id,
            "partner_id": self.partner.id, "points": 25})
        order = self.make_pos()
        order.confirm_coupon_programs({card.id: {"program_id": card.program_id.id,
            "points": 380, "won": 380, "spent": 0, "partner_id": self.partner.id}
            for card in self.card | second_card})
        histories = self.env["loyalty.history"].search([("order_model", "=", "pos.order"), ("order_id", "=", order.id)])
        self.assertEqual(len(histories.audit_event_ids), 2)
        self.assertEqual(set(histories.program_id.ids), {self.program.id, second_program.id})
        self.assertEqual(second_card.points, 405)
        for history in histories:
            self.assertEqual(sum(history.audit_line_ids.mapped("earned")), 380)

    def test_cod_audit_failure_rolls_back_only_loyalty(self):
        from odoo.addons.pos_cod.models.pos_order import PosOrder
        order = self.make_pos(is_cod=True)
        before = self.card.points
        result = {"success": True, "amount": 19000, "cod_state": "pending"}
        with patch.object(PosOrder, "collect_cod_payment", return_value=result), \
             patch.object(type(order), "_lpm_resolve_cod_order_from_result", return_value=order), \
             patch.object(type(order), "_lpm_cod_paid_total", return_value=19000), \
             patch.object(type(self.env["loyalty.audit.event"]), "_record", side_effect=RuntimeError("audit failure")):
            response = order.collect_cod_payment(action="payment")
        self.assertTrue(response["success"])
        self.assertIn("loyalty_error", response)
        self.assertEqual(self.card.points, before)
        self.assertFalse(self.env["loyalty.history"].search([("order_model", "=", "pos.order"), ("order_id", "=", order.id)]))
