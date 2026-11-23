from datetime import date
from pathlib import Path

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import new_test_user, tagged
from odoo.tools import SQL
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.base.models.ir_ui_view import get_view_arch_from_file


@tagged("post_install", "-at_install")
class TestLoyaltyReporting(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Reporting customer"})
        cls.program = cls.env["loyalty.program"].create({
            "name": "Reporting program", "program_type": "loyalty", "company_id": cls.env.company.id,
        })
        cls.card = cls.env["loyalty.card"].create({
            "partner_id": cls.partner.id, "program_id": cls.program.id,
            "points": 0, "create_date": "2020-01-01 00:00:00",
        })
        cls._set_created(cls.card, "2020-01-01 00:00:00")
        cls.auditor = new_test_user(cls.env, login="reporting_auditor",
            groups="base.group_user,base.group_allow_export,loyalty_points_manager.group_loyalty_auditor", tz="Africa/Nairobi")
        cls.ordinary = new_test_user(cls.env, login="reporting_ordinary", groups="base.group_user")
        cls.config = cls.env["pos.config"].create({
            "name": "Reporting POS", "journal_id": cls.company_data["default_journal_sale"].id,
            "invoice_journal_id": cls.company_data["default_journal_sale"].id,
            "payment_method_ids": [Command.clear()],
        })
        cls.session = cls.env["pos.session"].create({"config_id": cls.config.id})

    @staticmethod
    def _set_created(record, timestamp):
        # Odoo deliberately ignores supplied log-access timestamps in create().
        # Historical fixtures require a parameterized update of this system field.
        record.flush_recordset()
        record.env.cr.execute(SQL("UPDATE %s SET create_date = %s WHERE id = %s",
                                 SQL.identifier(record._table), timestamp, record.id))
        record.invalidate_recordset(["create_date"])

    def history(self, issued=0, used=0, at="2020-01-02 12:00:00", card=None, **values):
        card = card or self.card
        history = self.env["loyalty.history"].sudo().create({
            "card_id": card.id, "description": "Reporting fixture", "issued": issued, "used": used,
            "create_date": at, **values,
        })
        self._set_created(history, at)
        card.points += issued - used
        return history

    def event(self, history, at="2020-01-02 12:00:00", **values):
        return self.env["loyalty.audit.event"].sudo().create({
            "history_id": history.id, "card_id": history.card_id.id,
            "company_id": self.env.company.id, "captured_at": at,
            "event_key": "report:%s" % history.id, "trigger": "Reporting fixture",
            "issued": history.issued, "used": history.used, "balance_before": 0,
            "balance_after": history.issued - history.used, "evidence_quality": "captured", **values,
        })

    def summary(self, **context):
        return self.env["loyalty.customer.report"].with_user(self.auditor).with_context(**context).search([
            ("partner_id", "=", self.partner.id), ("program_id", "=", self.program.id),
        ])

    def movements(self, **context):
        return self.env["loyalty.movement.report"].with_user(self.auditor).with_context(**context).search([
            ("partner_id", "=", self.partner.id), ("program_id", "=", self.program.id),
        ])

    def test_current_balance_counted_once_per_card(self):
        self.history(100)
        self.history(used=20, at="2020-01-03 12:00:00")
        summary = self.summary()
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary.current_balance, 80)
        self.assertEqual(summary.lifetime_used, 20)
        grouped = summary._read_group([], ["program_id"], ["current_balance:sum"])
        self.assertIn((self.program, 80.0), grouped)

    def test_period_totals_and_as_of_balance_are_separate(self):
        self.history(100)
        self.history(used=20, at="2020-01-03 12:00:00")
        summary = self.summary(lpm_date_from="2020-01-03", lpm_date_to="2020-01-03", lpm_as_of="2020-01-02")
        self.assertEqual((summary.current_balance, summary.balance_as_of), (80, 100))
        self.assertEqual((summary.period_issued, summary.period_used), (0, 20))
        self.assertEqual(summary.balance_quality, "reconstructed")
        self.assertEqual(len(self.movements(lpm_date_from="2020-01-03", lpm_date_to="2020-01-03")), 1)

    def test_audit_replaces_history_without_double_counting(self):
        history = self.history(100)
        self.event(history)
        self.assertEqual(len(self.movements()), 1)
        self.assertEqual(self.summary().lifetime_issued, 100)
        self.assertEqual(self.summary(lpm_as_of="2020-01-02").balance_quality, "captured")

    def test_uncovered_history_residual_is_not_lost(self):
        history = self.history(100)
        self.event(history)
        history.issued = 120
        self.card.points = 120
        movements = self.movements()
        self.assertEqual(len(movements), 2)
        self.assertEqual(sum(movements.mapped("issued")), 120)
        self.assertEqual(set(movements.mapped("date_quality")), {"captured", "reconstructed"})

    def test_peak_combines_simultaneous_card_balances_not_individual_peaks(self):
        self.history(100)
        self.history(used=100, at="2020-01-03 12:00:00")
        other = self.env["loyalty.card"].create({"partner_id": self.partner.id,
            "program_id": self.program.id, "points": 0})
        self._set_created(other, "2020-01-01 00:00:00")
        self.history(100, at="2020-01-04 12:00:00", card=other)
        summary = self.summary(lpm_as_of="2020-01-05")
        self.assertEqual(summary.card_count, 2)
        self.assertEqual(summary.current_balance, 100)
        self.assertEqual(summary.peak_recorded_balance, 100)

    def test_unreconciled_history_is_not_presented_as_known_balance(self):
        self.history(100)
        self.card.points = 999
        summary = self.summary(lpm_as_of="2020-01-02")
        self.assertEqual(summary.balance_quality, "unavailable")
        self.assertEqual(summary.peak_quality, "unavailable")
        self.assertEqual(summary.current_balance, 999)
        self.assertEqual(self.summary().balance_quality, "current")

    def test_known_opening_balance_is_anchored_at_first_capture(self):
        history = self.history(100)
        self.card.points = 600
        self.event(history, balance_before=500, balance_after=600)
        summary = self.summary(lpm_as_of="2020-01-02")
        self.assertEqual(summary.balance_as_of, 600)
        self.assertEqual(summary.peak_recorded_balance, 600)
        self.assertEqual(self.summary(lpm_as_of="2020-01-01").balance_quality, "unavailable")

    def test_local_day_boundaries(self):
        self.history(10, at="2020-01-02 21:30:00")  # Jan 3 in the auditor's timezone.
        self.assertEqual(self.summary(lpm_as_of="2020-01-02").balance_as_of, 0)
        self.assertEqual(self.summary(lpm_as_of="2020-01-03").balance_as_of, 10)
        self.assertEqual(len(self.movements(lpm_date_from="2020-01-03", lpm_date_to="2020-01-03")), 1)

    def test_sorting_and_threshold_searches_are_native(self):
        self.history(100)
        other_partner = self.partner.copy({"name": "Higher balance"})
        self.env["loyalty.card"].create({"program_id": self.program.id,
            "partner_id": other_partner.id, "points": 500})
        report = self.env["loyalty.customer.report"].with_user(self.auditor)
        rows = report.search([("program_id", "=", self.program.id), ("current_balance", ">", 0)],
                             order="current_balance desc")
        self.assertEqual(rows[0].partner_id, other_partner)
        rows = report.search([("program_id", "=", self.program.id)], order="lifetime_issued desc")
        self.assertEqual(rows[0].partner_id, self.partner)

    def purchase(self, at, state="paid"):
        return self.env["pos.order"].create({
            "session_id": self.session.id, "partner_id": self.partner.id, "date_order": at,
            "state": state, "amount_total": 100, "amount_tax": 0, "amount_paid": 100, "amount_return": 0,
        })

    def test_dormancy_is_configurable_and_distinct_from_never_purchased(self):
        self.assertTrue(self.summary().never_purchased)
        self.assertFalse(self.summary(lpm_dormant_days=1).dormant)
        self.purchase("2020-01-01 12:00:00")
        self.purchase("2020-01-09 12:00:00", state="cancel")
        self.assertTrue(self.summary(lpm_as_of="2020-01-10", lpm_dormant_days=5).dormant)
        self.assertFalse(self.summary(lpm_as_of="2020-01-10", lpm_dormant_days=20).dormant)
        self.assertFalse(self.summary(lpm_as_of="2020-01-10").dormant)

    def test_order_and_collection_sessions_are_independent(self):
        order = self.purchase("2020-01-02 12:00:00")
        config = self.env["pos.config"].create({"name": "Collection reporting POS",
            "journal_id": self.company_data["default_journal_sale"].id,
            "invoice_journal_id": self.company_data["default_journal_sale"].id,
            "payment_method_ids": [Command.clear()]})
        collection = self.env["pos.session"].create({"config_id": config.id})
        history = self.history(100, order_model="pos.order", order_id=order.id)
        self.event(history, source_model="pos.order", source_order_id=order.id,
                   origin_session_id=self.session.id, collection_session_id=collection.id)
        movement = self.movements()
        self.assertEqual(movement.origin_session_id, self.session)
        self.assertEqual(movement.collection_session_id, collection)
        self.assertEqual(movement.pos_order_id, order)
        self.assertEqual(movement._read_group([], ["origin_session_id"], ["issued:sum"])[0][1], 100)

    def test_cancellation_events_survive_history_deletion(self):
        history = self.history(100)
        event = self.event(history)
        history.unlink()
        self.card.points = 0
        event.copy({"history_id": False, "event_key": "cancel:report", "captured_at": "2020-01-03 12:00:00",
                    "issued": -100, "policy": "actual_cancellation_movement"})
        movements = self.movements()
        self.assertEqual(sum(movements.mapped("issued")), 100)
        self.assertEqual(sum(movements.mapped("adjustment_points")), -100)
        self.assertEqual(sum(movements.mapped("net_points")), 0)

    def test_reports_are_read_only_and_company_scoped(self):
        self.history(100)
        other_company = self.env["res.company"].sudo().create({"name": "Reporting other company"})
        other_program = self.env["loyalty.program"].sudo().create({"name": "Other reporting program",
            "program_type": "loyalty", "company_id": other_company.id})
        other_card = self.env["loyalty.card"].sudo().create({"partner_id": self.partner.id,
            "program_id": other_program.id, "points": 0})
        self.history(900, card=other_card)
        for name in ("loyalty.customer.report", "loyalty.movement.report"):
            report = self.env[name].with_user(self.auditor)
            self.assertFalse(report.search([("program_id", "=", other_program.id)]))
            with self.assertRaises(AccessError):
                report.with_user(self.ordinary).search([])
            with self.assertRaises(AccessError):
                report.create({})
            row = report.search([("program_id", "=", self.program.id)], limit=1)
            with self.assertRaises(AccessError):
                row.unlink()

    def test_options_validation_and_saved_context(self):
        wizard = self.env["loyalty.report.options"].with_user(self.auditor).create({
            "date_from": "2020-01-02", "date_to": "2020-01-03", "as_of": "2020-01-02", "dormant_days": 5,
        })
        action = wizard.action_open_report()
        self.assertEqual(action["context"]["lpm_as_of"], "2020-01-02")
        self.assertEqual(action["context"]["lpm_dormant_days"], 5)
        wizard.date_from = date(2020, 1, 4)
        with self.assertRaises(ValidationError):
            wizard.action_open_report()
        with self.assertRaises(AccessError):
            wizard.with_user(self.ordinary).action_open_report()

    def test_native_views_and_safe_measure_metadata(self):
        for model in ("loyalty.customer.report", "loyalty.movement.report"):
            report = self.env[model].with_user(self.auditor)
            for view_type in ("list", "pivot", "graph", "search"):
                self.assertTrue(report.get_view(view_type=view_type)["arch"])
            self.assertTrue(report.fields_get())
        self.assertFalse(self.env["loyalty.history"]._fields["current_points_balance"].aggregator)
        self.assertFalse(self.env["loyalty.customer.report"]._fields["peak_recorded_balance"].aggregator)

    def test_all_addon_views_load_from_files_in_xml_developer_mode(self):
        # Normal get_view tests use arch_db; developer mode reads the source XML.
        addon = Path(__file__).resolve().parents[1]
        checked = 0
        for path in addon.rglob("*.xml"):
            for record in etree.parse(str(path)).xpath('//record[@model="ir.ui.view"]'):
                if record.find('field[@name="arch"]') is None:
                    continue
                xmlid = "loyalty_points_manager.%s" % record.get("id")
                with self.subTest(xmlid=xmlid):
                    arch = get_view_arch_from_file(str(path), xmlid)
                    self.assertIsNotNone(etree.fromstring(arch.encode()))
                checked += 1
        self.assertGreater(checked, 0)

    def test_peak_preserves_separate_movements_in_the_same_second(self):
        first = self.history(100)
        self.event(first)
        second = self.history(used=100)
        self.event(second, balance_before=100, balance_after=0)
        summary = self.summary(lpm_as_of="2020-01-02")
        self.assertEqual(summary.balance_as_of, 0)
        self.assertEqual(summary.peak_recorded_balance, 100)

    def test_shared_cards_do_not_expose_other_company_movements(self):
        self.program.company_id = False
        allowed = self.history(100)
        self.event(allowed)
        hidden = self.history(500)
        other_company = self.env["res.company"].sudo().create({"name": "Shared-card hidden company"})
        self.event(hidden, company_id=other_company.id, balance_before=100, balance_after=600)
        rows = self.movements()
        self.assertEqual(len(rows), 1)
        self.assertEqual(sum(rows.mapped("issued")), 100)
        summary = self.summary(lpm_as_of="2020-01-02")
        self.assertEqual(summary.lifetime_issued, 100)
        self.assertEqual(summary.current_balance, 600)  # The card itself is explicitly shared.
        self.assertEqual(summary.balance_quality, "unavailable")

    def test_export_and_grouping_keep_report_context(self):
        self.history(100)
        self.history(used=20, at="2020-01-03 12:00:00")
        rows = self.summary(lpm_as_of="2020-01-02", lpm_date_from="2020-01-03", lpm_date_to="2020-01-03")
        exported = rows.export_data(["current_balance", "balance_as_of", "period_used"])["datas"]
        self.assertEqual(exported[0], [80.0, 100.0, 20.0])
        aggregates = rows._read_group([("partner_id", "=", self.partner.id)], ["program_id"],
                                      ["balance_as_of:sum", "period_used:sum"])
        self.assertEqual(aggregates[0][1:], (100.0, 20.0))
