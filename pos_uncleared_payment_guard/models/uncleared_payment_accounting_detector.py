import logging

from odoo import Command, api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger("pos_uncleared_payment_guard.accounting_detector")


class UnclearedPaymentAccountingDetector(models.AbstractModel):
    _name = "pos.uncleared.payment.accounting.detector"
    _description = "Read-only Uncleared POS Payment Accounting Detector"

    @api.model
    def upg_check_hold(self, hold):
        """Read exact linked accounting evidence; write only the guard's audit records."""
        hold.ensure_one()
        if hold.state == "cancelled":
            return False
        if hold.state == "accounting_cleared" and not hold.linked_transfer_move_id:
            # Preserve historic confirmations; never infer new links during upgrade.
            return False
        _logger.debug("[UPG][DETECT_CLEARANCE][START] hold_id=%s", hold.id)
        if not hold.linked_transfer_move_id:
            return self._not_confirmed(hold, _("Link Transfer is required. References and equal amounts are not clearance evidence."))
        if hold.cheque_date and hold.cheque_date > fields.Date.context_today(hold):
            return self._not_confirmed(hold, _("The cheque date has not arrived."))
        try:
            _source, target = hold._upg_transfer_lines()
        except ValidationError as exc:
            return self._not_confirmed(hold, str(exc))

        transfer = hold.linked_transfer_move_id
        if hold.accounting_transfer_move_id != transfer:
            hold._upg_mark_transfer_seen(transfer, note=_("Explicit cheque transfer selected."))
        statements, confirmed = self._confirmed_bank_evidence(hold, target)
        if hold.currency_id.compare_amounts(confirmed, hold.amount) < 0:
            return self._not_confirmed(
                hold, _("Linked bank confirmation is incomplete: %(confirmed)s of %(amount)s.",
                        confirmed=confirmed, amount=hold.amount),
            )
        hold.write({
            "accounting_transfer_move_id": transfer.id,
            "bank_statement_line_id": statements[:1].id,
            "confirmed_bank_statement_line_ids": [Command.set(statements.ids)],
            "accounting_detection_note": _("Confirmed through the selected transfer and its bank reconciliation links."),
        })
        if hold.state != "accounting_cleared":
            hold._upg_mark_accounting_cleared()
        _logger.debug("[UPG][DETECT_CLEARANCE][END] hold_id=%s outcome=confirmed statement_ids=%s",
                      hold.id, statements.ids)
        return True

    @api.model
    def _confirmed_bank_evidence(self, hold, target):
        statements = self.env["account.bank.statement.line"]
        direct = target.statement_line_id
        if direct:
            if self._valid_statement(hold, direct):
                return direct, min(target.debit, hold.amount)
            return statements, 0.0
        confirmed = 0.0
        # target is the transfer's debit to outstanding receipts. Only partials
        # pointing FROM that exact line TO a bank statement credit are evidence.
        for partial in target.matched_credit_ids:
            credit = partial.credit_move_id
            statement = credit.statement_line_id
            if (partial.debit_move_id != target or credit.account_id != target.account_id
                    or partial.company_id != hold.company_id or credit.move_id.state != "posted"
                    or not statement or not self._valid_statement(hold, statement)):
                continue
            confirmed += partial.amount
            statements |= statement
        return statements, confirmed

    @api.model
    def _valid_statement(self, hold, statement):
        return bool(
            statement.company_id == hold.company_id
            and statement.journal_id == hold.deposit_bank_journal_id
            and statement.move_id.state == "posted"
            and statement.is_reconciled and statement.amount > 0
            and (statement.currency_id or statement.company_id.currency_id) == hold.currency_id
        )

    @api.model
    def _not_confirmed(self, hold, message):
        vals = {
            "bank_statement_line_id": False,
            "confirmed_bank_statement_line_ids": [Command.clear()],
            "accounting_detection_note": message,
        }
        if hold.state == "accounting_cleared":
            vals["state"] = "manual_cleared" if hold.transfer_link_manual_release else "accounting_transfer_seen"
        hold.write(vals)
        if "state" in vals and hold.cod_collection_id:
            # A fully paid COD order must become visible again when bank evidence is undone.
            hold.cod_collection_id.order_id.write({"cod_state": "partial"})
        _logger.debug("[UPG][DETECT_CLEARANCE][END] hold_id=%s outcome=unconfirmed reason=%s", hold.id, message)
        return False
