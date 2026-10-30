from datetime import timedelta

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged


@tagged("post_install", "-at_install")
class TestAccountingClearance(AccountTestInvoicingCommon):
    """Exercise real ledger detection and hold transitions without posting POS sales."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, upg_skip_live_detector=True))
        cls.env.user.sudo().write({"groups_id": [Command.link(
            cls.env.ref("pos_uncleared_payment_guard.group_pos_uncleared_payment_manager").id,
        )]})
        cls.cash_journal = cls.company_data["default_journal_cash"]
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.outstanding = cls.env["account.account"].create({
            "name": "Cheque outstanding receipts", "code": "UPGCLR",
            "account_type": "asset_current", "reconcile": True,
        })
        cls.bank_journal.inbound_payment_method_line_ids.payment_account_id = cls.outstanding
        cls.method = cls.env["pos.payment.method"].create({
            "name": "Guarded cheque",
            "journal_id": cls.cash_journal.id,
            "company_id": cls.env.company.id,
        })
        cls.config = cls.env["pos.config"].create({
            "name": "Cheque clearance test",
            "payment_method_ids": [Command.set(cls.method.ids)],
            "journal_id": cls.company_data["default_journal_misc"].id,
            "invoice_journal_id": cls.company_data["default_journal_sale"].id,
        })
        cls.session = cls.env["pos.session"].create({"config_id": cls.config.id})
        cls.partner = cls.env["res.partner"].create({"name": "Cheque customer"})
        cls.order = cls.env["pos.order"].create({
            "session_id": cls.session.id,
            "partner_id": cls.partner.id,
            "amount_total": 0,
            "amount_tax": 0,
            "amount_paid": 0,
            "amount_return": 0,
        })
        cls.detector = cls.env["pos.uncleared.payment.accounting.detector"]

    def _hold(self, state="manual_cleared", **extra):
        return self.env["pos.uncleared.payment.hold"].create({
            "partner_id": self.partner.id,
            "commercial_partner_id": self.partner.id,
            "pos_order_id": self.order.id,
            "payment_method_id": self.method.id,
            "pos_config_id": self.config.id,
            "pos_session_id": self.session.id,
            "company_id": self.env.company.id,
            "currency_id": self.env.company.currency_id.id,
            "amount": 35000,
            "state": state,
            "deposit_bank_journal_id": self.bank_journal.id,
            **extra,
        })

    def _bank_receipt(self, reference="Cheque clearance regression"):
        # A posted statement with a resolved counterpart is reconciled in Odoo.
        return self.env["account.bank.statement.line"].create({
            "journal_id": self.bank_journal.id,
            "date": fields.Date.today(),
            "payment_ref": reference,
            "amount": 35000,
            "counterpart_account_id": self.cash_journal.default_account_id.id,
        })

    def _transfer(self, hold, amount=35000, post=True, target=None):
        transfer = self.env["account.move"].create({
            "journal_id": self.company_data["default_journal_misc"].id,
            "line_ids": [
                Command.create({"account_id": self.cash_journal.default_account_id.id, "credit": amount}),
                Command.create({"account_id": (target or self.outstanding).id, "debit": amount}),
            ],
        })
        if post:
            transfer.action_post()
        return transfer

    def _reconcile_transfer(self, transfer, amount=35000, journal=None):
        bank = journal or self.bank_journal
        receipt = self.env["account.bank.statement.line"].create({
            "journal_id": bank.id, "amount": amount,
            "payment_ref": "No cheque reference required",
            "counterpart_account_id": self.outstanding.id,
        })
        (transfer.line_ids.filtered(lambda line: line.account_id == self.outstanding)
         | receipt.move_id.line_ids.filtered(lambda line: line.account_id == self.outstanding)).reconcile()
        return receipt

    def test_manual_clearance_becomes_accounting_cleared(self):
        hold = self._hold(clear_reason="Manager authorization", clear_reference="Manual reference")
        receipt = self._bank_receipt()
        self.assertTrue(receipt.is_reconciled)
        hold._upg_link_transfer(receipt.move_id)
        before = receipt.move_id.line_ids.read(["account_id", "debit", "credit"])

        self.env["pos.uncleared.payment.hold"].cron_detect_accounting_reconciliation()
        self.assertEqual(hold.state, "accounting_cleared")
        self.assertEqual(hold.accounting_transfer_move_id, receipt.move_id)
        self.assertEqual(hold.bank_statement_line_id, receipt)
        self.assertEqual(hold.clear_reference, receipt.move_id.name)
        cleared_date = hold.cleared_date
        self.assertTrue(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.cleared_date, cleared_date)
        self.assertEqual(receipt.move_id.line_ids.read(["account_id", "debit", "credit"]), before)

    def test_pending_hold_still_clears(self):
        hold = self._hold("pending")
        receipt = self._bank_receipt()
        hold._upg_link_transfer(receipt.move_id)
        self.assertTrue(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "accounting_cleared")

    def test_manual_cod_hold_still_updates_order(self):
        self.order.write({"is_cod": True, "cod_state": "partial"})
        collection = self.env["pos.cod.collection"].create({
            "order_id": self.order.id,
            "session_id": self.session.id,
            "payment_method_id": self.method.id,
            "amount": 35000,
        })
        hold = self._hold(cod_collection_id=collection.id)
        receipt = self._bank_receipt()
        hold._upg_link_transfer(receipt.move_id)
        self.assertTrue(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "accounting_cleared")
        self.assertEqual(hold.accounting_transfer_move_id, receipt.move_id)
        self.assertEqual(self.order.cod_state, "paid")

    def test_transfer_without_bank_clearance_preserves_manual_release(self):
        hold = self._hold()
        transfer = self._transfer(hold)
        hold._upg_link_transfer(transfer)
        self.assertFalse(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "manual_cleared")
        self.assertEqual(hold.accounting_transfer_move_id, transfer)
        self.assertFalse(hold.bank_statement_line_id)

    def test_missing_evidence_does_not_clear(self):
        hold = self._hold()
        self.assertFalse(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "manual_cleared")

    def test_future_cheque_does_not_clear(self):
        hold = self._hold(cheque_date=fields.Date.today() + timedelta(days=1))
        receipt = self._bank_receipt()
        hold._upg_link_transfer(receipt.move_id)
        self.assertFalse(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "manual_cleared")

    def test_cancelled_hold_is_not_reopened(self):
        hold = self._hold("cancelled")
        self._bank_receipt()
        self.assertFalse(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "cancelled")
        self.assertFalse(hold.bank_statement_line_id)

    def test_other_company_bank_receipt_does_not_clear(self):
        hold = self._hold()
        other = self.setup_other_company()
        self.env["account.bank.statement.line"].with_company(other["company"]).create({
            "journal_id": other["default_journal_bank"].id,
            "amount": 35000,
            "payment_ref": "Other company cheque",
            "counterpart_account_id": other["default_journal_cash"].default_account_id.id,
        })
        self.assertFalse(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "manual_cleared")

    def test_viewer_cannot_write_clearance_state(self):
        hold = self._hold()
        viewer = new_test_user(
            self.env, login="upg_clearance_viewer",
            groups="pos_uncleared_payment_guard.group_pos_uncleared_payment_viewer",
        )
        with self.assertRaises(AccessError):
            hold.with_user(viewer).write({"state": "accounting_cleared"})
        with self.assertRaises(UserError):
            hold.with_user(viewer).action_open_transfer_link_wizard()

    def test_blank_reference_transfer_reconciles_through_exact_links(self):
        hold = self._hold()
        transfer = self._transfer(hold)
        self.assertFalse(transfer.ref)
        wizard = self.env["pos.uncleared.payment.link.transfer.wizard"].create({
            "hold_id": hold.id, "move_id": transfer.id,
        })
        wizard.action_link()
        self.assertEqual(hold.state, "manual_cleared")
        receipt = self._reconcile_transfer(transfer)
        self.assertTrue(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "accounting_cleared")
        self.assertEqual(hold.bank_statement_line_id, receipt)
        self.assertEqual(hold.confirmed_bank_statement_line_ids, receipt)

    def test_same_amount_unrelated_bank_receipt_cannot_clear(self):
        hold = self._hold()
        transfer = self._transfer(hold)
        hold._upg_link_transfer(transfer)
        # Even a reconciled receipt with the exact hold reference is insufficient.
        self._bank_receipt(reference=hold.name)
        self.assertFalse(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "manual_cleared")
        self.assertFalse(hold.bank_statement_line_id)

    def test_without_selection_matching_references_do_not_clear(self):
        hold = self._hold()
        receipt = self._bank_receipt()
        receipt.move_id.ref = hold.name
        self.assertFalse(self.detector.upg_check_hold(hold))
        self.assertIn("Link Transfer", hold.accounting_detection_note)

    def test_partial_bank_confirmation_waits_for_full_amount(self):
        hold = self._hold()
        transfer = self._transfer(hold)
        hold._upg_link_transfer(transfer)
        first = self._reconcile_transfer(transfer, amount=20000)
        self.assertFalse(self.detector.upg_check_hold(hold))
        second = self._reconcile_transfer(transfer, amount=15000)
        self.assertTrue(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.confirmed_bank_statement_line_ids, first | second)

    def test_unreconciliation_revokes_accounting_confirmation_not_manual_release(self):
        hold = self._hold()
        transfer = self._transfer(hold)
        hold._upg_link_transfer(transfer)
        self._reconcile_transfer(transfer)
        self.assertTrue(self.detector.upg_check_hold(hold))
        transfer.line_ids.remove_move_reconcile()
        self.env["pos.uncleared.payment.hold"].cron_detect_accounting_reconciliation()
        self.assertEqual(hold.state, "manual_cleared")
        self.assertFalse(hold.bank_statement_line_id)

    def test_invalid_transfer_rejected(self):
        hold = self._hold()
        for transfer in (
            self._transfer(hold, amount=34000),
            self._transfer(hold, post=False),
            self._transfer(hold, target=self.company_data["default_account_revenue"]),
            self._transfer(hold, target=self.cash_journal.default_account_id),
        ):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                hold._upg_link_transfer(transfer)

    def test_transfer_cannot_be_reused_for_another_cheque(self):
        hold = self._hold()
        transfer = self._transfer(hold)
        hold._upg_link_transfer(transfer)
        other = self._hold()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            other._upg_link_transfer(transfer)

    def test_reconciliation_in_wrong_bank_cannot_clear(self):
        hold = self._hold()
        transfer = self._transfer(hold)
        hold._upg_link_transfer(transfer)
        other_bank = self.env["account.journal"].create({
            "name": "Different deposit bank", "code": "UPG2", "type": "bank",
        })
        self._reconcile_transfer(transfer, journal=other_bank)
        self.assertFalse(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "manual_cleared")

    def test_foreign_currency_link_rejected(self):
        hold = self._hold()
        foreign = self.env["res.currency"].with_context(active_test=False).search([("id", "!=", hold.currency_id.id)], limit=1)
        hold.currency_id = foreign
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            hold._upg_link_transfer(self._transfer(hold))

    def test_link_from_other_company_rejected(self):
        hold = self._hold()
        other = self.setup_other_company()
        transfer = self.env["account.move"].with_company(other["company"]).create({
            "journal_id": other["default_journal_misc"].id,
            "line_ids": [
                Command.create({"account_id": other["default_journal_cash"].default_account_id.id, "credit": 35000}),
                Command.create({"account_id": other["default_journal_bank"].default_account_id.id, "debit": 35000}),
            ],
        })
        transfer.action_post()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            hold.sudo()._upg_link_transfer(transfer)

    def test_unreconciliation_restores_pending_restriction(self):
        hold = self._hold("pending")
        transfer = self._transfer(hold)
        hold._upg_link_transfer(transfer)
        self._reconcile_transfer(transfer)
        self.assertTrue(self.detector.upg_check_hold(hold))
        transfer.line_ids.remove_move_reconcile()
        self.env["pos.uncleared.payment.hold"].cron_detect_accounting_reconciliation()
        self.assertEqual(hold.state, "accounting_transfer_seen")
        self.assertFalse(hold.confirmed_bank_statement_line_ids)

    def test_posted_reversal_invalidates_confirmation(self):
        hold = self._hold()
        transfer = self._transfer(hold)
        hold._upg_link_transfer(transfer)
        self._reconcile_transfer(transfer)
        self.assertTrue(self.detector.upg_check_hold(hold))
        reverse = transfer._reverse_moves(default_values_list=[{"date": fields.Date.today()}])
        reverse.action_post()
        self.assertFalse(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.state, "manual_cleared")

    def test_standard_statement_deletion_detaches_audit(self):
        hold = self._hold()
        receipt = self._bank_receipt()
        hold._upg_link_transfer(receipt.move_id)
        reference = receipt.move_id.name
        receipt.move_id.button_draft()
        receipt.unlink()
        hold.invalidate_recordset()
        self.assertFalse(hold.linked_transfer_move_id)
        self.assertEqual(hold.previous_transfer_reference, reference)
        self.assertEqual(hold.state, "manual_cleared")

    def test_live_detector_sql_error_does_not_abort_accounting(self):
        from unittest.mock import patch
        self.env = self.env(context=dict(self.env.context, upg_skip_live_detector=False))
        self.detector = self.env["pos.uncleared.payment.accounting.detector"]
        hold = self._hold()
        transfer = self._transfer(hold)
        hold._upg_link_transfer(transfer)
        def fail(detector, checked):
            detector.env.cr.execute("SELECT 1 / %s", [0])
        with patch.object(type(self.detector), "upg_check_hold", fail):
            transfer.line_ids[:1].write({"name": "Ordinary valid edit"})
            self.env.cr.execute("SELECT 1")
            self.assertEqual(self.env.cr.fetchone()[0], 1)

    def test_standard_internal_transfer_clearing_chain(self):
        hold = self._hold()
        clearing = self.env["account.account"].create({"name": "Cheque transfer clearing", "code": "CHQTRF", "account_type": "asset_current", "reconcile": True})
        self.env.company.transfer_account_id = clearing
        outgoing = self._transfer(hold, target=clearing)
        incoming = self.env["account.move"].create({
            "journal_id": self.company_data["default_journal_misc"].id,
            "line_ids": [Command.create({"account_id": clearing.id, "credit": 35000}), Command.create({"account_id": self.outstanding.id, "debit": 35000})],
        })
        incoming.action_post()
        (outgoing.line_ids | incoming.line_ids).filtered(lambda line: line.account_id == clearing).reconcile()
        hold._upg_link_transfer(outgoing)
        receipt = self._reconcile_transfer(incoming)
        self.assertTrue(self.detector.upg_check_hold(hold))
        self.assertEqual(hold.bank_statement_line_id, receipt)
