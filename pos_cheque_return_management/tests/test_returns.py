from uuid import uuid4
from unittest.mock import patch

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged


@tagged("post_install", "-at_install")
class TestChequeReturns(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, upg_skip_live_detector=True))
        cls.env.user.sudo().write({"groups_id": [Command.link(cls.env.ref("pos_cheque_return_management.group_cheque_return_accountant").id)]})
        cls.cash = cls.company_data["default_journal_cash"]
        cls.bank = cls.company_data["default_journal_bank"]
        cls.misc = cls.company_data["default_journal_misc"]
        cls.ar = cls.company_data["default_account_receivable"]
        cls.revenue = cls.company_data["default_account_revenue"]
        cls.cod_ar = cls.env["account.account"].create({"name": "Cheque Test COD Receivable", "code": "CHQCOD", "account_type": "asset_receivable", "reconcile": True})
        cls.partner = cls.env["res.partner"].create({"name": "Cheque return customer", "property_account_receivable_id": cls.ar.id})
        cls.method = cls.env["pos.payment.method"].create({"name": "Cheque return test", "journal_id": cls.cash.id})
        cls.config = cls.env["pos.config"].create({
            "name": "Cheque return test", "journal_id": cls.misc.id,
            "invoice_journal_id": cls.company_data["default_journal_sale"].id,
            "payment_method_ids": [Command.set(cls.method.ids)], "cod_ar_account_id": cls.cod_ar.id,
        })
        cls.session = cls.env["pos.session"].create({"config_id": cls.config.id})

    def _entry(self, debit, credit, amount):
        move = self.env["account.move"].create({
            "journal_id": self.misc.id, "date": fields.Date.today(),
            "line_ids": [
                Command.create({"account_id": debit.id, "debit": amount, "partner_id": self.partner.id}),
                Command.create({"account_id": credit.id, "credit": amount, "partner_id": self.partner.id}),
            ],
        })
        move.action_post()
        return move

    def _order(self, amount=0, cod=False):
        return self.env["pos.order"].create({
            "session_id": self.session.id, "partner_id": self.partner.id,
            "amount_total": amount, "amount_tax": 0, "amount_paid": 0, "amount_return": 0,
            "is_cod": cod, "cod_state": "partial" if cod else "pending",
        })

    def _hold(self, amount=35000, direct_cod=False, cod_total=None):
        order = self._order((cod_total or amount) if direct_cod else 0, direct_cod)
        account = self.cod_ar if direct_cod else self.ar
        receipt = self._entry(self.cash.default_account_id, account, amount)
        source = receipt.line_ids.filtered(lambda line: line.credit > 0)
        collection = self.env["pos.cod.collection"]
        if direct_cod:
            invoice = self._entry(self.cod_ar, self.revenue, cod_total or amount)
            order.cod_ar_move_id = invoice
            (invoice.line_ids.filtered(lambda line: line.account_id == self.cod_ar) | source).reconcile()
            collection = self.env["pos.cod.collection"].create({"order_id": order.id, "session_id": self.session.id, "payment_method_id": self.method.id, "kind": "payment", "amount": amount, "move_id": receipt.id})
            order.cod_state = "paid"
        hold = self.env["pos.uncleared.payment.hold"].create({
            "partner_id": self.partner.id, "commercial_partner_id": self.partner.id,
            "pos_order_id": order.id, "cod_collection_id": collection.id,
            "payment_method_id": self.method.id, "pos_config_id": self.config.id,
            "pos_session_id": self.session.id, "company_id": self.env.company.id,
            "currency_id": self.env.company.currency_id.id, "amount": amount,
            "state": "manual_cleared", "deposit_bank_journal_id": self.bank.id,
        })
        return hold, source

    def _statement(self, amount, account):
        return self.env["account.bank.statement.line"].create({
            "journal_id": self.bank.id, "amount": amount, "payment_ref": "Bank evidence",
            "partner_id": self.partner.id, "counterpart_account_id": account.id,
        })

    def _report(self, hold, source, statement=True, reason=None):
        bank_line = self._statement(-hold.amount, source.account_id) if statement is True else statement
        case = hold._cheque_report_return(
            reason or self.env.ref("pos_cheque_return_management.reason_insufficient_funds"),
            "Bank confirmed return", source, bank_line,
        )
        case.correction_journal_id = self.misc
        return case

    def _application(self, hold, source, amount=1100):
        order = self._order(amount, True)
        invoice = self._entry(self.cod_ar, self.revenue, amount)
        order.cod_ar_move_id = invoice
        bridge = self._entry(self.ar, self.cod_ar, amount)
        debit = bridge.line_ids.filtered(lambda line: line.account_id == self.ar)
        credit = bridge.line_ids - debit
        (source | debit).reconcile()
        (invoice.line_ids.filtered(lambda line: line.account_id == self.cod_ar) | credit).reconcile()
        application = self.env["pos.cod.deposit.application"].sudo().create({
            "operation_uuid": str(uuid4()), "order_id": order.id, "partner_id": self.partner.id,
            "commercial_partner_id": self.partner.id, "company_id": self.env.company.id,
            "currency_id": self.env.company.currency_id.id, "pos_config_id": self.config.id,
            "pos_session_id": self.session.id, "requested_amount": amount, "amount": amount,
            "default_receivable_account_id": self.ar.id, "cod_receivable_account_id": self.cod_ar.id,
            "transfer_journal_id": self.misc.id, "move_id": bridge.id,
            "source_credit_line_ids": [Command.set(source.ids)],
            "cod_source_line_ids": [Command.set(invoice.line_ids.filtered(lambda line: line.account_id == self.cod_ar).ids)],
            "bridge_receivable_line_id": debit.id, "bridge_cod_line_id": credit.id, "state": "posted",
        })
        order.cod_state = "paid"
        return order, application

    def test_purchase_debt_restored_not_full_unused_deposit(self):
        hold, source = self._hold()
        sale = self._entry(self.ar, self.revenue, 10000)
        invoice_line = sale.line_ids.filtered(lambda line: line.account_id == self.ar)
        (source | invoice_line).reconcile()
        self.assertEqual(source.amount_residual, -25000)
        case = self._report(hold, source)
        case.action_confirm_accounting()
        self.assertEqual(invoice_line.amount_residual, 10000)
        self.assertTrue(source.reconciled)
        self.assertEqual(hold.state, "returned")
        self.assertEqual(case.state, "accounted")
        principal = case._principal_line()
        self.assertTrue(principal.reconciled)
        # The guard must not add 35000 again after accounting restored the debt.
        totals = self.env["pos.uncleared.payment.hold"]._upg_pending_amounts_for_partner(self.partner, self.env.company.id)
        self.assertEqual(totals["pending_total"], 0)

    def test_unposted_return_blocks_manual_release(self):
        hold, source = self._hold()
        self._report(hold, source, statement=False)
        totals = self.env["pos.uncleared.payment.hold"]._upg_pending_amounts_for_partner(self.partner, self.env.company.id)
        self.assertEqual(totals["pending_total"], 35000)
        with self.assertRaises(UserError):
            hold._upg_mark_manual_cleared("Try to override")
        with self.assertRaises(UserError):
            hold.write({"state": "pending"})
        self.assertFalse(self.env["pos.uncleared.payment.accounting.detector"].upg_check_hold(hold))

    def test_direct_cod_returns_to_open_cards(self):
        hold, source = self._hold(7000, direct_cod=True)
        order = hold.pos_order_id
        case = self._report(hold, source)
        case.action_confirm_accounting()
        order.invalidate_recordset()
        self.assertEqual(order._cod_open_amount(), 7000)
        self.assertEqual(order.cod_amount_open, 7000)
        self.assertEqual(order.cod_state, "partial")
        self.assertEqual(order.upg_cod_uncleared_state, "returned")
        self.assertEqual(order.cod_ar_move_id.line_ids.filtered(lambda line: line.account_id == self.cod_ar).amount_residual, 7000)

    def test_deposit_cod_restores_only_allocated_amount(self):
        hold, source = self._hold()
        order, application = self._application(hold, source)
        case = self._report(hold, source)
        self.assertEqual(hold.cheque_funding_ids.amount, 1100)
        case.action_confirm_accounting()
        order.invalidate_recordset()
        self.assertEqual(order._cod_open_amount(), 1100)
        self.assertEqual(order.cod_amount_open, 1100)
        self.assertEqual(order.cod_amount_paid, 0)
        self.assertEqual(order.cod_state, "partial")
        self.assertEqual(application.state, "posted")
        self.assertEqual(application.amount, 1100)
        self.assertEqual(application.bridge_receivable_line_id.amount_residual, 0)
        self.assertEqual(sum(case.correction_move_ids.line_ids.mapped("balance")), 0)
        moves = case.correction_move_ids
        case.action_confirm_accounting()
        self.assertEqual(case.correction_move_ids, moves)
        self.assertEqual(len(order.cod_collection_ids.filtered(lambda row: row.kind == "cheque_return")), 1)

    def test_rebank_same_cheque_restores_cod_once(self):
        hold, source = self._hold()
        order, app = self._application(hold, source)
        case = self._report(hold, source)
        case.action_confirm_accounting()
        credit = self._statement(35000, self.ar)
        new_source = credit.move_id.line_ids.filtered(lambda line: line.account_id == self.ar)
        wizard = self.env["pos.cheque.return.wizard"].create({"hold_id": hold.id, "operation": "rebank", "receipt_credit_line_id": new_source.id, "statement_id": credit.id})
        wizard.action_apply()
        self.assertEqual(hold.state, "rebank_pending")
        attempt = hold.active_attempt_id
        attempt.action_confirm_rebank()
        self.assertEqual(attempt.number, 2)
        self.assertEqual(hold.state, "accounting_cleared")
        self.assertEqual(order._cod_open_amount(), 0)
        self.assertEqual(order.cod_state, "paid")
        self.assertEqual(new_source.amount_residual, -33900)
        with self.assertRaises(UserError):
            attempt.action_confirm_rebank()

    def test_second_return_after_rebank_does_not_duplicate_debt(self):
        hold, source = self._hold()
        order, app = self._application(hold, source)
        self._report(hold, source).action_confirm_accounting()
        credit = self._statement(35000, self.ar)
        new_source = credit.move_id.line_ids.filtered(lambda line: line.account_id == self.ar)
        self.env["pos.cheque.return.wizard"].create({"hold_id": hold.id, "operation": "rebank", "receipt_credit_line_id": new_source.id, "statement_id": credit.id}).action_apply()
        hold.active_attempt_id.action_confirm_rebank()
        self._report(hold, new_source).action_confirm_accounting()
        self.assertEqual(order._cod_open_amount(), 1100)
        self.assertEqual(order.cod_state, "partial")

    def test_fraud_cannot_be_rebanked(self):
        hold, source = self._hold()
        self._report(hold, source, reason=self.env.ref("pos_cheque_return_management.reason_suspected_fraud")).action_confirm_accounting()
        credit = self._statement(35000, self.ar)
        new_source = credit.move_id.line_ids.filtered(lambda line: line.account_id == self.ar)
        with self.assertRaises(UserError):
            self.env["pos.cheque.return.wizard"].create({"hold_id": hold.id, "operation": "rebank", "receipt_credit_line_id": new_source.id, "statement_id": credit.id}).action_apply()

    def test_positive_outgoing_cheque_refund_is_not_customer_bounce(self):
        hold, source = self._hold()
        credit = self._statement(35000, self.ar)
        with self.assertRaises(ValidationError):
            self._report(hold, source, statement=credit)
        self.assertEqual(hold.state, "manual_cleared")

    def test_fee_and_refund_do_not_change_principal(self):
        hold, source = self._hold()
        case = self._report(hold, source)
        expense = self.company_data["default_account_expense"]
        charge = self._statement(-702, expense)
        fee = self.env["pos.cheque.bank.fee"].create({"return_id": case.id, "statement_id": charge.id, "kind": "charge"})
        refund = self._statement(702, expense)
        self.env["pos.cheque.bank.fee"].create({"return_id": case.id, "statement_id": refund.id, "kind": "refund", "refund_of_id": fee.id})
        self.assertEqual(case.amount, 35000)
        self.assertEqual(case.state, "reported")
        self.assertEqual(hold.state, "returned")

    def test_confirmation_failure_rolls_back_invoice_reconciliation(self):
        hold, source = self._hold()
        sale = self._entry(self.ar, self.revenue, 10000)
        debit = sale.line_ids.filtered(lambda line: line.account_id == self.ar)
        (source | debit).reconcile()
        case = self._report(hold, source)
        before = source.matched_debit_ids.ids
        with patch.object(type(case), "_correct_cod_funding", side_effect=UserError("Failed correction")):
            with self.assertRaises(UserError):
                case.action_confirm_accounting()
        source.invalidate_recordset()
        self.assertEqual(source.matched_debit_ids.ids, before)
        self.assertEqual(debit.amount_residual, 0)
        self.assertEqual(case.state, "reported")

    def test_reporter_cannot_confirm_accounting(self):
        hold, source = self._hold()
        case = self._report(hold, source)
        reporter = new_test_user(self.env, login="cheque_reporter", groups="pos_cheque_return_management.group_cheque_return_manager")
        with self.assertRaises(UserError):
            case.with_user(reporter).action_confirm_accounting()

    def test_duplicate_bank_return_is_rejected(self):
        hold, source = self._hold()
        self._report(hold, source)
        with self.assertRaises(UserError):
            self._report(hold, source)

    def test_company_mismatch_in_return_is_rejected(self):
        hold, source = self._hold()
        other = self.setup_other_company()
        bank_line = self.env["account.bank.statement.line"].with_company(other["company"]).create({"journal_id": other["default_journal_bank"].id, "amount": -35000, "counterpart_account_id": other["default_account_receivable"].id, "partner_id": self.partner.id})
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._report(hold, source, statement=bank_line).action_confirm_accounting()

    def test_valid_cash_payment_survives_direct_cod_bounce(self):
        hold, source = self._hold(7000, direct_cod=True, cod_total=10000)
        order = hold.pos_order_id
        cash = self._entry(self.cash.default_account_id, self.cod_ar, 3000)
        debit = order.cod_ar_move_id.line_ids.filtered(lambda line: line.account_id == self.cod_ar)
        (debit | cash.line_ids.filtered(lambda line: line.account_id == self.cod_ar)).reconcile()
        self.env["pos.cod.collection"].create({"order_id": order.id, "session_id": self.session.id, "kind": "payment", "amount": 3000, "move_id": cash.id})
        self._report(hold, source).action_confirm_accounting()
        self.assertEqual(order.cod_amount_paid, 3000)
        self.assertEqual(order.cod_amount_open, 7000)
        self.assertEqual(debit.amount_residual, 7000)
        self.assertTrue(cash.line_ids.filtered(lambda line: line.account_id == self.cod_ar).reconciled)

    def test_replacement_has_its_own_bank_confirmation_and_receipt(self):
        hold, source = self._hold()
        order, app = self._application(hold, source)
        self._report(hold, source).action_confirm_accounting()
        replacement, replacement_source = self._hold()
        bank_credit = self._statement(35000, self.cash.default_account_id)
        replacement._upg_link_transfer(bank_credit.move_id)
        self.assertEqual(replacement.state, "accounting_cleared")
        wizard = self.env["pos.cheque.return.wizard"].create({
            "hold_id": hold.id, "operation": "replace", "replacement_hold_id": replacement.id,
            "receipt_credit_line_id": replacement_source.id,
        })
        wizard.action_apply()
        self.assertEqual(hold.state, "replaced")
        self.assertEqual(replacement.replacement_for_id, hold)
        self.assertEqual(order._cod_open_amount(), 0)
        self.assertEqual(replacement_source.amount_residual, -33900)
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_replacement_manual_clearance_is_insufficient(self):
        hold, source = self._hold()
        self._report(hold, source).action_confirm_accounting()
        replacement, new_source = self._hold()
        wizard = self.env["pos.cheque.return.wizard"].create({
            "hold_id": hold.id, "operation": "replace", "replacement_hold_id": replacement.id,
            "receipt_credit_line_id": new_source.id,
        })
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertEqual(hold.state, "returned")

    def test_reported_return_adjusts_available_credit_once(self):
        hold, source = self._hold()
        case = self._report(hold, source, statement=False)
        info = self.partner.get_credit_info(self.partner.id, self.env.company.id)
        self.assertEqual(info["deposit_balance"], 0)
        self.assertEqual(info["total_due"], 0)
        case.return_statement_id = self._statement(-35000, self.ar)
        case.action_confirm_accounting()
        info = self.partner.get_credit_info(self.partner.id, self.env.company.id)
        self.assertEqual(info["total_due"], 0)
        self.assertEqual(info["deposit_balance"], 0)

    def test_return_cancels_unposted_cod_reservation(self):
        hold, source = self._hold()
        payment = self.env["pos.payment"].create({"pos_order_id": hold.pos_order_id.id, "payment_method_id": self.method.id, "amount": 35000})
        hold.pos_payment_id = payment
        order = self._order(1100, True)
        reservation = self.env["pos.cod.session.deposit.reservation"].sudo().create({
            "operation_uuid": str(uuid4()), "order_id": order.id, "partner_id": self.partner.id,
            "commercial_partner_id": self.partner.id, "company_id": self.env.company.id,
            "currency_id": self.env.company.currency_id.id, "source_session_id": self.session.id,
            "pos_config_id": self.config.id, "amount": 1100, "source_payment_ids": [Command.set(payment.ids)],
        })
        self._report(hold, source, statement=False)
        self.assertEqual(reservation.state, "cancelled")
        self.assertEqual(order.cod_session_deposit_reserved_amount, 0)

    def test_unallocated_historical_cod_application_requires_review(self):
        hold, source = self._hold()
        order, app = self._application(hold, source)
        source.remove_move_reconcile()
        case = self._report(hold, source)
        with self.assertRaises(UserError):
            case.action_confirm_accounting()
        self.assertEqual(case.state, "reported")
        self.env["pos.cheque.cod.funding"].create({"hold_id": hold.id, "application_id": app.id, "amount": 1100})
        case.action_confirm_accounting()
        self.assertEqual(order._cod_open_amount(), 1100)

    def test_locked_accounting_period_rolls_back_cod_correction(self):
        hold, source = self._hold()
        order, app = self._application(hold, source)
        case = self._report(hold, source)
        original = source.matched_debit_ids
        self.env.company.fiscalyear_lock_date = fields.Date.today()
        # Odoo may move the accounting date into an open period. The service
        # must either use that standard behaviour or leave the whole return pending.
        try:
            case.action_confirm_accounting()
        except UserError:
            self.assertEqual(case.state, "reported")
            self.assertEqual(source.matched_debit_ids, original)
        else:
            self.assertTrue(all(move.date > fields.Date.today() for move in case.correction_move_ids))

    def test_technical_rejection_has_no_automatic_penalty(self):
        hold, source = self._hold()
        case = self._report(hold, source, reason=self.env.ref("pos_cheque_return_management.reason_technical"))
        case.action_confirm_accounting()
        self.assertFalse(case.fee_ids)
        self.assertEqual(case.inline_bank_fee, 0)

    def test_fee_refund_does_not_release_failed_cheque(self):
        hold, source = self._hold()
        case = self._report(hold, source)
        expense = self.company_data["default_account_expense"]
        fee = self.env["pos.cheque.bank.fee"].create({"return_id": case.id, "statement_id": self._statement(-702, expense).id, "kind": "charge"})
        self.env["pos.cheque.bank.fee"].create({"return_id": case.id, "statement_id": self._statement(702, expense).id, "kind": "refund", "refund_of_id": fee.id})
        self.assertEqual(hold.state, "returned")
        self.assertFalse(self.env["pos.uncleared.payment.accounting.detector"].upg_check_hold(hold))

    def test_rebank_settles_original_purchase_debt(self):
        hold, source = self._hold()
        sale = self._entry(self.ar, self.revenue, 10000)
        debt = sale.line_ids.filtered(lambda line: line.account_id == self.ar)
        (source | debt).reconcile()
        self._report(hold, source).action_confirm_accounting()
        self.assertEqual(debt.amount_residual, 10000)
        bank_credit = self._statement(35000, self.ar)
        new_source = bank_credit.move_id.line_ids.filtered(lambda line: line.account_id == self.ar)
        self.env["pos.cheque.return.wizard"].create({"hold_id": hold.id, "operation": "rebank", "receipt_credit_line_id": new_source.id, "statement_id": bank_credit.id}).action_apply()
        hold.active_attempt_id.action_confirm_rebank()
        self.assertEqual(debt.amount_residual, 0)
        self.assertEqual(new_source.amount_residual, -25000)

    def test_return_is_visible_in_pos_navbar(self):
        hold, source = self._hold()
        self._report(hold, source, statement=False)
        records = self.env["pos.uncleared.payment.hold"].upg_pos_pending_holds(self.env.company.id)
        visible = next(record for record in records if record["id"] == hold.id)
        self.assertEqual(visible["state"], "returned")
        self.assertEqual(visible["state_label"], "Cheque Returned")

    def test_return_history_cannot_be_edited_to_release_money(self):
        hold, source = self._hold()
        case = self._report(hold, source)
        with self.assertRaises(UserError):
            case.write({"state": "accounted"})
        with self.assertRaises(UserError):
            hold.active_attempt_id.write({"state": "cleared"})
        with self.assertRaises(UserError):
            hold.write({"active_attempt_id": False})

    def test_rebank_credit_reset_to_draft_requires_review_without_extra_debt(self):
        hold, source = self._hold()
        self._report(hold, source).action_confirm_accounting()
        credit = self._statement(35000, self.ar)
        new_source = credit.move_id.line_ids.filtered(lambda line: line.account_id == self.ar)
        self.env["pos.cheque.return.wizard"].create({"hold_id": hold.id, "operation": "rebank", "receipt_credit_line_id": new_source.id, "statement_id": credit.id}).action_apply()
        attempt = hold.active_attempt_id
        attempt.action_confirm_rebank()
        credit.move_id.button_draft()
        self.env["pos.uncleared.payment.hold"].cron_detect_accounting_reconciliation()
        self.assertEqual(hold.state, "rebank_pending")
        pending = hold._upg_pending_amounts_for_partner(self.partner, self.env.company.id)
        self.assertEqual(pending["pending_total"], 0)
        credit.move_id.action_post()
        attempt.action_confirm_rebank()
        self.assertEqual(hold.state, "accounting_cleared")

    def test_rebank_cannot_strand_unused_credit_in_cod_receivable(self):
        hold, source = self._hold()
        self._report(hold, source).action_confirm_accounting()
        credit = self._statement(35000, self.cod_ar)
        new_source = credit.move_id.line_ids.filtered(lambda line: line.account_id == self.cod_ar)
        wizard = self.env["pos.cheque.return.wizard"].create({"hold_id": hold.id, "operation": "rebank", "receipt_credit_line_id": new_source.id, "statement_id": credit.id})
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertEqual(hold.state, "returned")

    def test_unused_candidate_source_can_be_reviewed_without_false_cod_debt(self):
        funded, funded_source = self._hold()
        order, app = self._application(funded, funded_source)
        unused, unused_source = self._hold()
        app.with_context(cdds_allow_audit_write=True).sudo().write({"source_credit_line_ids": [Command.set((funded_source | unused_source).ids)]})
        case = self._report(unused, unused_source)
        with self.assertRaises(UserError):
            case.action_confirm_accounting()
        case.write({"funding_reviewed": True, "funding_review_note": "Candidate credit remained unused; actual application funded by another receipt."})
        case.action_confirm_accounting()
        self.assertFalse(case.correction_move_ids)
        self.assertEqual(order._cod_open_amount(), 0)

    def test_original_application_cannot_be_allocated_again_after_return(self):
        hold, source = self._hold()
        order, app = self._application(hold, source)
        self._report(hold, source).action_confirm_accounting()
        other, other_source = self._hold()
        app.with_context(cdds_allow_audit_write=True).sudo().write({"source_credit_line_ids": [Command.set((source | other_source).ids)]})
        other._cheque_original_attempt(other_source)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env["pos.cheque.cod.funding"].create({"hold_id": other.id, "application_id": app.id, "amount": 1100})

    def test_combined_principal_fee_and_later_fee_refund(self):
        hold, source = self._hold()
        expense = self.company_data["default_account_expense"]
        statement = self.env["account.bank.statement.line"].create({
            "journal_id": self.bank.id, "amount": -35702, "payment_ref": "Principal plus bank fee", "partner_id": self.partner.id,
            "line_ids": [
                Command.create({"account_id": self.bank.default_account_id.id, "credit": 35702}),
                Command.create({"account_id": self.ar.id, "debit": 35000, "partner_id": self.partner.id}),
                Command.create({"account_id": expense.id, "debit": 702}),
            ],
        })
        case = self._report(hold, source, statement=statement)
        case.action_confirm_accounting()
        self.assertEqual(case.inline_bank_fee, 702)
        refund = self._statement(702, expense)
        self.env["pos.cheque.bank.fee"].create({"return_id": case.id, "statement_id": refund.id, "kind": "refund"})
        self.assertEqual(hold.state, "returned")
        self.assertEqual(case.amount, 35000)

    def test_bank_fee_keeps_standard_configured_tax_lines(self):
        hold, source = self._hold()
        case = self._report(hold, source)
        expense = self.company_data["default_account_expense"]
        repartition = self.tax_purchase_a.invoice_repartition_line_ids.filtered(lambda line: line.repartition_type == "tax")[:1]
        statement = self.env["account.bank.statement.line"].create({
            "journal_id": self.bank.id, "amount": -702, "payment_ref": "Fee and configured tax",
            "line_ids": [
                Command.create({"account_id": self.bank.default_account_id.id, "credit": 702}),
                Command.create({"account_id": expense.id, "debit": 600}),
                Command.create({"account_id": repartition.account_id.id, "debit": 102, "tax_repartition_line_id": repartition.id}),
            ],
        })
        before = statement.move_id.line_ids.read(["account_id", "debit", "credit", "tax_repartition_line_id"])
        fee = self.env["pos.cheque.bank.fee"].create({"return_id": case.id, "statement_id": statement.id, "kind": "charge"})
        self.assertEqual(fee.amount, 702)
        self.assertEqual(statement.move_id.line_ids.read(["account_id", "debit", "credit", "tax_repartition_line_id"]), before)
