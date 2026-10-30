from datetime import timedelta

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged


@tagged("post_install", "-at_install")
class TestChequeDepositControl(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.sudo().write({"groups_id": [Command.link(cls.env.ref(
            "pos_uncleared_payment_guard.group_pos_uncleared_payment_manager").id)]})
        cls.cash = cls.company_data["default_journal_cash"]
        cls.bank = cls.company_data["default_journal_bank"]
        cls.outstanding = cls.env["account.account"].create({
            "name": "Deposit test outstanding", "code": "PCD001", "account_type": "asset_current", "reconcile": True,
        })
        cls.bank.inbound_payment_method_line_ids.payment_account_id = cls.outstanding
        cls.method = cls.env["pos.payment.method"].create({
            "name": "Cheque deposit test", "journal_id": cls.cash.id,
            "company_id": cls.env.company.id, "upg_is_uncleared_guard_method": True, "pcd_is_cheque": True,
        })
        cls.config = cls.env["pos.config"].create({
            "name": "Cheque deposit control test", "payment_method_ids": [Command.set(cls.method.ids)],
            "journal_id": cls.company_data["default_journal_misc"].id,
            "invoice_journal_id": cls.company_data["default_journal_sale"].id,
            "upg_deposit_bank_journal_ids": [Command.set(cls.bank.ids)], "pcd_enabled": True,
        })
        cls.session = cls.env["pos.session"].create({"config_id": cls.config.id})
        cls.partner = cls.env["res.partner"].create({"name": "Cheque deposit test customer"})
        cls.order = cls.env["pos.order"].create({
            "session_id": cls.session.id, "partner_id": cls.partner.id,
            "amount_total": 0, "amount_tax": 0, "amount_paid": 0, "amount_return": 0,
        })
        cls.today = fields.Date.context_today(cls.config)

    def _hold(self, **extra):
        payment = self.env["pos.payment"].create({
            "pos_order_id": self.order.id, "payment_method_id": self.method.id, "amount": 9500,
        })
        return self.env["pos.uncleared.payment.hold"].create({
            "partner_id": self.partner.id, "commercial_partner_id": self.partner.id,
            "pos_order_id": self.order.id, "pos_payment_id": payment.id,
            "payment_method_id": self.method.id, "pos_config_id": self.config.id,
            "pos_session_id": self.session.id, "company_id": self.env.company.id,
            "currency_id": self.env.company.currency_id.id, "amount": 9500,
            "cheque_number": "54", "cheque_date": self.today,
            "deposit_bank_journal_id": self.bank.id, **extra,
        })

    def _move(self, hold=None, amount=9500, target=None, source=None):
        return self.env["account.move"].create({
            "journal_id": self.company_data["default_journal_misc"].id,
            "pcd_hold_id": hold.id if hold else False, "pcd_deposit_date": self.today,
            "line_ids": [
                Command.create({"account_id": (source or self.cash.default_account_id).id, "credit": amount}),
                Command.create({"account_id": (target or self.outstanding).id, "debit": amount}),
            ],
        })

    def _receipt(self, move, **extra):
        receipt = self.env["ir.attachment"].create({
            "name": "bank-deposit.txt", "raw": b"Bank deposit receipt test fixture",
            "res_model": "account.move", "res_id": move.id, "company_id": move.company_id.id, **extra,
        })
        move.pcd_receipt_ids = [Command.link(receipt.id)]
        return receipt

    def _reminders(self, **kwargs):
        return self.env["pos.uncleared.payment.hold"].pcd_pos_reminders(self.config.id, **kwargs)

    def test_post_requires_cheque_even_when_blank(self):
        move = self._move()
        with self.assertRaisesRegex(ValidationError, "Select the cheque"), self.cr.savepoint():
            move.action_post()
        self.assertEqual(move.state, "draft")

    def test_receipt_required(self):
        move = self._move(self._hold())
        with self.assertRaisesRegex(ValidationError, "Attach the bank deposit receipt"), self.cr.savepoint():
            move.action_post()

    def test_receipt_links_and_hides_banking_reminder_only(self):
        hold = self._hold()
        self.assertEqual(self._reminders()["count"], 1)
        move = self._move(hold)
        self._receipt(move)
        move.action_post()
        self.assertEqual(hold.linked_transfer_move_id, move)
        self.assertEqual(hold.state, "accounting_transfer_seen")
        self.assertEqual(self._reminders()["count"], 0)
        self.assertFalse(hold.bank_statement_line_id)

    def test_unrelated_journal_entry_posts_without_receipt(self):
        move = self._move(source=self.company_data["default_account_revenue"])
        move.action_post()
        self.assertEqual(move.state, "posted")

    def test_reverse_direction_does_not_require_receipt(self):
        move = self._move(source=self.outstanding, target=self.cash.default_account_id)
        move.action_post()
        self.assertEqual(move.state, "posted")

    def test_draft_and_manual_clearance_do_not_hide_reminder(self):
        hold = self._hold(state="manual_cleared")
        move = self._move(hold)
        self._receipt(move)
        self.assertEqual(self._reminders()["count"], 1)

    def test_future_cheque_and_cancelled_cheque_not_due(self):
        self._hold(cheque_date=self.today + timedelta(days=1))
        self._hold(state="cancelled")
        self.assertEqual(self._reminders()["count"], 0)

    def test_overdue_cheque_can_be_deposited_later(self):
        hold = self._hold(cheque_date=self.today - timedelta(days=2))
        move = self._move(hold)
        self._receipt(move)
        move.action_post()
        self.assertEqual(self._reminders()["count"], 0)

    def test_future_or_early_deposit_date_rejected(self):
        hold = self._hold()
        move = self._move(hold)
        self._receipt(move)
        for date in (self.today + timedelta(days=1), self.today - timedelta(days=1)):
            move.pcd_deposit_date = date
            with self.assertRaises(ValidationError), self.cr.savepoint():
                move.action_post()

    def test_wrong_amount_rejected(self):
        move = self._move(self._hold(), amount=9400)
        self._receipt(move)
        with self.assertRaisesRegex(ValidationError, "full cheque amount"), self.cr.savepoint():
            move.action_post()

    def test_same_amount_and_date_do_not_hide_other_cheque(self):
        first, second = self._hold(), self._hold()
        move = self._move(first)
        self._receipt(move)
        move.action_post()
        self.assertEqual([row["id"] for row in self._reminders()["rows"]], [second.id])

    def test_count_is_not_limited_by_page(self):
        self._hold()
        self._hold()
        self._hold()
        result = self._reminders(limit=1)
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["rows"]), 1)
        self.assertNotEqual(result["rows"][0]["id"], self._reminders(offset=1, limit=1)["rows"][0]["id"])

    def test_multiple_destination_banks(self):
        second_outstanding = self.outstanding.copy({"code": "PCD002"})
        second_bank = self.bank.copy({"name": "Second cheque destination", "code": "PCD2"})
        second_bank.inbound_payment_method_line_ids.payment_account_id = second_outstanding
        self.config.upg_deposit_bank_journal_ids = [Command.link(second_bank.id)]
        hold = self._hold(deposit_bank_journal_id=second_bank.id)
        move = self._move(hold, target=second_outstanding)
        self._receipt(move)
        move.action_post()
        self.assertEqual(self._reminders()["count"], 0)

    def test_wrong_bank_account_rejected(self):
        other_account = self.outstanding.copy({"code": "PCD003"})
        move = self._move(self._hold(), target=other_account)
        self._receipt(move)
        with self.assertRaisesRegex(ValidationError, "Outstanding Receipts"), self.cr.savepoint():
            move.action_post()

    def test_empty_url_public_or_unrelated_receipt_rejected(self):
        move = self._move(self._hold())
        receipt = self._receipt(move)
        variations = [
            {"raw": False}, {"type": "url", "url": "https://example.invalid/receipt"},
            {"public": True}, {"res_id": move.id + 100000},
        ]
        for values in variations:
            with self.assertRaises(UserError), self.cr.savepoint():
                receipt.write(values)
                move.action_post()

    def test_posted_receipt_and_fields_protected(self):
        move = self._move(self._hold())
        receipt = self._receipt(move)
        move.action_post()
        for values in ({"raw": b"replaced"}, {"public": True}, {"res_id": 0}):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                receipt.write(values)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            receipt.unlink()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            move.write({"pcd_receipt_ids": [Command.clear()]})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            move.line_ids[0].write({"account_id": self.outstanding.id})

    def test_reset_restores_reminder_and_allows_correction(self):
        hold = self._hold()
        move = self._move(hold)
        receipt = self._receipt(move)
        move.action_post()
        move.button_draft()
        self.assertFalse(hold.linked_transfer_move_id)
        self.assertEqual(self._reminders()["count"], 1)
        receipt.write({"raw": b"Corrected receipt"})
        move.action_post()
        self.assertEqual(self._reminders()["count"], 0)

    def test_reversal_restores_banking_reminder(self):
        move = self._move(self._hold())
        self._receipt(move)
        move.action_post()
        reversal = move._reverse_moves([{"date": self.today}])
        reversal.action_post()
        self.assertEqual(self._reminders()["count"], 1)

    def test_direct_state_write_cannot_bypass_receipt(self):
        move = self._move(self._hold())
        with self.assertRaises(ValidationError), self.cr.savepoint():
            move.write({"state": "posted"})

    def test_foreign_currency_rejected(self):
        currency = self.env.ref("base.EUR") if self.env.company.currency_id != self.env.ref("base.EUR") else self.env.ref("base.USD")
        currency.active = True
        hold = self._hold(currency_id=currency.id)
        move = self._move(hold)
        self._receipt(move)
        with self.assertRaisesRegex(ValidationError, "company-currency"), self.cr.savepoint():
            move.action_post()

    def test_cashier_cannot_disable_control_or_read_receipts(self):
        cashier = new_test_user(self.env, login="pcd_cashier", groups="point_of_sale.group_pos_user")
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.config.with_user(cashier).write({"pcd_enabled": False})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.config.with_user(cashier).write({"pcd_popup_interval_seconds": 1})
        hold = self._hold()
        result = hold.with_user(cashier).pcd_pos_reminders(self.config.id)
        self.assertEqual(result["count"], 1)
        self.assertNotIn("cheque_account_number", result["rows"][0])
        self.assertNotIn("pcd_receipt_ids", result["rows"][0])

    def test_accountant_without_cheque_manager_cannot_post_cheque(self):
        accountant = new_test_user(self.env, login="pcd_accountant", groups="account.group_account_user,pos_uncleared_payment_guard.group_pos_uncleared_payment_viewer")
        move = self._move(self._hold())
        self._receipt(move)
        with self.assertRaises(UserError), self.cr.savepoint():
            move.with_user(accountant).action_post()

    def test_other_company_config_is_not_visible(self):
        other = self.setup_other_company()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env["pos.uncleared.payment.hold"].with_context(allowed_company_ids=[other["company"].id]).pcd_pos_reminders(self.config.id)

    def test_company_rule_and_cross_company_cheque(self):
        other = self.setup_other_company()
        hold = self._hold()
        viewer = new_test_user(self.env, login="pcd_other_company", groups="pos_uncleared_payment_guard.group_pos_uncleared_payment_viewer",
                               company_id=other["company"].id, company_ids=[Command.set(other["company"].ids)])
        with self.assertRaises(AccessError):
            hold.with_user(viewer).check_access("read")
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env["account.move"].with_company(other["company"]).create({
                "journal_id": other["default_journal_misc"].id, "pcd_hold_id": hold.id,
            })

    def test_editing_unrelated_posted_entry_into_cheque_transfer_is_blocked(self):
        move = self._move(source=self.company_data["default_account_revenue"])
        move.action_post()
        credit = move.line_ids.filtered(lambda line: line.credit)
        with self.assertRaisesRegex(ValidationError, "Select the cheque"), self.cr.savepoint():
            credit.write({"account_id": self.cash.default_account_id.id})

    def test_wrong_company_receipt_is_rejected(self):
        other = self.setup_other_company()
        move = self._move(self._hold())
        self._receipt(move, company_id=other["company"].id)
        with self.assertRaises(UserError), self.cr.savepoint():
            move.action_post()

    def test_failed_direct_post_does_not_leave_entry_posted(self):
        move = self._move(self._hold())
        # The production boundary itself rolls back even if another addon catches the error.
        with self.assertRaises(ValidationError):
            move.write({"state": "posted"})
        self.assertEqual(move.state, "draft")

    def test_configuration_requires_banks_and_valid_interval(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.config.write({"upg_deposit_bank_journal_ids": [Command.clear()]})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.config.write({"pcd_refresh_seconds": 0})
        for interval in (0, -1):
            with self.assertRaisesRegex(ValidationError, "popup repeat interval must be positive"), self.cr.savepoint():
                self.config.write({"pcd_popup_interval_seconds": interval})

    def test_popup_interval_is_independent_of_refresh_interval(self):
        self.config.write({"pcd_popup_interval_seconds": 180, "pcd_refresh_seconds": 45})
        self.assertEqual(self.config.pcd_popup_interval_seconds, 180)
        self.assertEqual(self.config.pcd_refresh_seconds, 45)

    def test_unconfigured_pos_does_not_enforce_receipt(self):
        self.config.pcd_enabled = False
        move = self._move()
        move.action_post()
        self.assertEqual(move.state, "posted")

    def test_old_sessions_are_included_and_other_pos_is_excluded(self):
        hold = self._hold()
        hold.pos_session_id = False
        self.assertEqual(self._reminders()["count"], 1)
        other_config = self.config.copy({"name": "Other POS for reminder isolation", "pcd_enabled": False})
        hold.pos_config_id = other_config
        self.assertEqual(self._reminders()["count"], 0)

    def test_batch_posting_is_atomic_with_missing_receipt(self):
        valid, invalid = self._move(self._hold()), self._move(self._hold())
        self._receipt(valid)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            (valid | invalid).action_post()
        self.assertEqual(valid.state, "draft")
        self.assertEqual(invalid.state, "draft")

    def test_scheduled_posting_rechecks_evidence_when_due(self):
        move = self._move(self._hold())
        move.date = self.today + timedelta(days=1)
        self.assertFalse(move._post(soft=True))
        self.assertEqual(move.state, "draft")
        move.date = self.today
        with self.assertRaisesRegex(ValidationError, "Attach the bank deposit receipt"), self.cr.savepoint():
            move._post(soft=False)

    def test_missing_cheque_date_blocks_deposit_posting(self):
        move = self._move(self._hold(cheque_date=False))
        self._receipt(move)
        with self.assertRaisesRegex(ValidationError, "cheque date is required"), self.cr.savepoint():
            move.action_post()
