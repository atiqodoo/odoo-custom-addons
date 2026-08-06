# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.tools import float_compare

_logger = logging.getLogger("pos_uncleared_payment_guard.accounting_detector")


class UnclearedPaymentAccountingDetector(models.AbstractModel):
    _name = "pos.uncleared.payment.accounting.detector"
    _description = "Read-only Uncleared POS Payment Accounting Detector"

    @api.model
    def upg_check_hold(self, hold):
        """Read accounting state only; never create, post, reconcile, or edit moves."""
        hold.ensure_one()
        if not self._is_cheque_matured(hold):
            return False
        if not hold.deposit_bank_journal_id:
            self._note(hold, "No POS-selected deposit bank journal; skipping bank-chain detection.")
            return False
        if not hold.mapped_account_id or not hold.deposit_bank_account_id:
            self._note(
                hold,
                "Missing mapped/deposit ledger account. mapped=%s deposit=%s"
                % (hold.mapped_account_id.display_name, hold.deposit_bank_account_id.display_name),
            )
            return False

        transfer = hold.accounting_transfer_move_id or self._find_internal_transfer_move(hold)
        if not transfer:
            return False

        if hold.state == "pending":
            hold._upg_mark_transfer_seen(
                transfer,
                note="Read-only detector matched mapped ledger to selected deposit bank ledger.",
            )

        statement_line = self._find_reconciled_statement_line(hold, transfer)
        if not statement_line:
            self._note(hold, "Internal transfer seen, but deposit bank statement line is not reconciled yet.")
            return False

        hold.write({
            "bank_statement_line_id": statement_line.id,
            "accounting_detection_note": (
                "Internal transfer %s and reconciled statement line %s detected."
                % (transfer.name, statement_line.display_name)
            ),
        })
        hold._upg_mark_accounting_cleared()
        return True

    @api.model
    def _find_internal_transfer_move(self, hold):
        amount = abs(hold.amount or 0.0)
        currency = hold.currency_id or hold.company_id.currency_id
        mapped_accounts = self._mapped_candidate_accounts(hold)
        domain = [
            ("move_id.state", "=", "posted"),
            ("move_id.company_id", "=", hold.company_id.id),
            ("account_id", "in", (mapped_accounts | hold.deposit_bank_account_id).ids),
        ]
        lines = self.env["account.move.line"].search(domain, order="date desc, id desc", limit=400)
        candidate_moves = lines.mapped("move_id")
        _logger.warning(
            "[UPG][Detector] hold=%s direct transfer search amount=%.2f mapped_accounts=%s deposit_account=%s candidates=%s",
            hold.name,
            amount,
            mapped_accounts.mapped("code"),
            hold.deposit_bank_account_id.code,
            candidate_moves.mapped("name"),
        )
        for move in candidate_moves:
            mapped_lines = move.line_ids.filtered(lambda line: line.account_id in mapped_accounts)
            deposit_lines = move.line_ids.filtered(lambda line: line.account_id == hold.deposit_bank_account_id)
            if not mapped_lines or not deposit_lines:
                continue
            mapped_ok = any(self._line_amount_matches(line, amount, currency) for line in mapped_lines)
            deposit_ok = any(self._line_amount_matches(line, amount, currency) for line in deposit_lines)
            if mapped_ok and deposit_ok:
                _logger.warning("[UPG][Detector] hold=%s matched internal transfer move=%s", hold.name, move.name)
                return move

        chained_move = self._find_liquidity_transfer_chain(hold, mapped_accounts, amount, currency)
        if chained_move:
            return chained_move

        mapped_transfer_move = self._find_mapped_ledger_transfer_move(hold, mapped_accounts, amount, currency)
        if mapped_transfer_move:
            return mapped_transfer_move

        self._note(
            hold,
            "No posted internal-transfer move found between mapped ledger, liquidity transfer, and selected deposit bank ledger.",
        )
        return self.env["account.move"]

    @api.model
    def _find_mapped_ledger_transfer_move(self, hold, mapped_accounts, amount, currency):
        mapped_lines = self.env["account.move.line"].search([
            ("move_id.state", "=", "posted"),
            ("move_id.company_id", "=", hold.company_id.id),
            ("account_id", "in", mapped_accounts.ids),
            ("balance", "in", [amount, -amount]),
        ], order="date desc, id desc", limit=400)
        incoming_lines = mapped_lines.filtered(lambda line: self._amount_matches(line.debit, amount, currency))
        outgoing_lines = mapped_lines.filtered(lambda line: self._amount_matches(line.credit, amount, currency))
        _logger.warning(
            "[UPG][Detector] hold=%s mapped-ledger transfer candidates incoming=%s outgoing=%s",
            hold.name,
            incoming_lines.mapped("move_id.name"),
            outgoing_lines.mapped("move_id.name"),
        )
        for outgoing_line in outgoing_lines:
            outgoing_move = outgoing_line.move_id
            if not self._move_reference_matches_hold(outgoing_move, hold):
                continue
            matching_incoming = incoming_lines.filtered(
                lambda line: line.account_id == outgoing_line.account_id
                and self._move_reference_matches_hold(line.move_id, hold)
            )
            if matching_incoming:
                _logger.warning(
                    "[UPG][Detector] hold=%s matched mapped-ledger transfer incoming=%s outgoing=%s account=%s",
                    hold.name,
                    matching_incoming.mapped("move_id.name"),
                    outgoing_move.name,
                    outgoing_line.account_id.display_name,
                )
                return outgoing_move
        return self.env["account.move"]

    @api.model
    def _find_liquidity_transfer_chain(self, hold, mapped_accounts, amount, currency):
        mapped_lines = self.env["account.move.line"].search([
            ("move_id.state", "=", "posted"),
            ("move_id.company_id", "=", hold.company_id.id),
            ("account_id", "in", mapped_accounts.ids),
            ("balance", "in", [amount, -amount]),
        ], order="date desc, id desc", limit=400)
        mapped_moves = mapped_lines.mapped("move_id")
        _logger.warning(
            "[UPG][Detector] hold=%s liquidity-chain mapped-side candidates=%s",
            hold.name,
            mapped_moves.mapped("name"),
        )
        for mapped_move in mapped_moves:
            if not self._move_reference_matches_hold(mapped_move, hold):
                _logger.debug("[UPG][Detector] hold=%s skip mapped move=%s reference mismatch", hold.name, mapped_move.name)
                continue
            liquidity_lines = mapped_move.line_ids.filtered(
                lambda line: line.account_id not in mapped_accounts
                and self._line_amount_matches(line, amount, currency)
            )
            for liquidity_line in liquidity_lines:
                deposit_move = self._find_deposit_side_move(
                    hold,
                    liquidity_line.account_id,
                    amount,
                    currency,
                )
                if deposit_move:
                    _logger.warning(
                        "[UPG][Detector] hold=%s matched liquidity chain mapped_move=%s liquidity_account=%s deposit_move=%s",
                        hold.name,
                        mapped_move.name,
                        liquidity_line.account_id.display_name,
                        deposit_move.name,
                    )
                    return deposit_move
        return self.env["account.move"]

    @api.model
    def _find_deposit_side_move(self, hold, liquidity_account, amount, currency):
        deposit_lines = self.env["account.move.line"].search([
            ("move_id.state", "=", "posted"),
            ("move_id.company_id", "=", hold.company_id.id),
            ("journal_id", "=", hold.deposit_bank_journal_id.id),
            ("account_id", "=", hold.deposit_bank_account_id.id),
            ("balance", "in", [amount, -amount]),
        ], order="date desc, id desc", limit=300)
        for deposit_line in deposit_lines:
            move = deposit_line.move_id
            if not self._move_reference_matches_hold(move, hold):
                _logger.debug("[UPG][Detector] hold=%s skip deposit move=%s reference mismatch", hold.name, move.name)
                continue
            liquidity_ok = any(
                line.account_id == liquidity_account and self._line_amount_matches(line, amount, currency)
                for line in move.line_ids
            )
            if liquidity_ok:
                return move
        return self.env["account.move"]

    @api.model
    def _find_reconciled_statement_line(self, hold, transfer):
        amount = abs(hold.amount or 0.0)
        domain = [
            ("journal_id", "=", hold.deposit_bank_journal_id.id),
            ("company_id", "=", hold.company_id.id),
            ("is_reconciled", "=", True),
        ]
        statement_lines = self.env["account.bank.statement.line"].search(domain, order="date desc, id desc", limit=300)
        _logger.warning(
            "[UPG][Detector] hold=%s statement search deposit_journal=%s candidates=%s",
            hold.name,
            hold.deposit_bank_journal_id.display_name,
            statement_lines.mapped("display_name"),
        )
        transfer_line_ids = set(transfer.line_ids.ids)
        for statement_line in statement_lines:
            amount_match = self._amount_matches(statement_line.amount, amount, hold.currency_id)
            linked = bool(transfer_line_ids & set(statement_line.move_id.line_ids.ids))
            reconciled_linked = any(
                line.reconciled or line.matched_debit_ids or line.matched_credit_ids
                for line in statement_line.move_id.line_ids
            )
            reference_match = self._statement_reference_matches_hold(statement_line, hold)
            if amount_match and (linked or reconciled_linked or reference_match):
                _logger.warning(
                    "[UPG][Detector] hold=%s matched reconciled statement line=%s linked=%s ref_match=%s",
                    hold.name,
                    statement_line.display_name,
                    linked,
                    reference_match,
                )
                return statement_line
        return self.env["account.bank.statement.line"]

    @api.model
    def _line_amount_matches(self, line, amount, currency):
        return self._amount_matches(abs(line.balance), amount, currency)

    @api.model
    def _amount_matches(self, candidate, expected, currency):
        return float_compare(abs(candidate or 0.0), abs(expected or 0.0), precision_rounding=currency.rounding) == 0

    @api.model
    def _is_cheque_matured(self, hold):
        if not hold.cheque_date:
            return True
        today = fields.Date.context_today(hold)
        if hold.cheque_date > today:
            self._note(
                hold,
                "Post-dated cheque is not eligible for clearance before %s. Today is %s."
                % (hold.cheque_date, today),
            )
            return False
        return True

    @api.model
    def _mapped_candidate_accounts(self, hold):
        return (
            hold.mapped_account_id
            | hold.payment_method_id.outstanding_account_id
            | hold.payment_method_id.journal_id.default_account_id
        ).filtered(lambda account: account)

    @api.model
    def _move_reference_matches_hold(self, move, hold):
        haystack = self._reference_haystack([
            move.name,
            move.ref,
            *move.line_ids.mapped("name"),
            *move.line_ids.mapped("ref"),
            *move.line_ids.mapped("statement_line_id.payment_ref"),
        ])
        return self._haystack_matches_hold(haystack, hold)

    @api.model
    def _statement_reference_matches_hold(self, statement_line, hold):
        haystack = self._reference_haystack([
            getattr(statement_line, "name", False),
            getattr(statement_line, "payment_ref", False),
            getattr(statement_line, "ref", False),
            getattr(statement_line.move_id, "ref", False),
            getattr(statement_line.move_id, "name", False),
            *statement_line.move_id.line_ids.mapped("name"),
            *statement_line.move_id.line_ids.mapped("ref"),
        ])
        return self._haystack_matches_hold(haystack, hold)

    @api.model
    def _reference_haystack(self, values):
        return " ".join(str(value) for value in values if value).lower()

    @api.model
    def _haystack_matches_hold(self, haystack, hold):
        needles = [
            hold.name,
            hold.cheque_number,
            hold.pos_order_id.name,
            hold.pos_order_id.pos_reference,
            hold.pos_session_id.name,
        ]
        return any(needle and str(needle).lower() in haystack for needle in needles)

    @api.model
    def _note(self, hold, message):
        hold.accounting_detection_note = message
        _logger.warning("[UPG][Detector] hold=%s %s", hold.name, message)
