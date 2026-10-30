import logging

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .attempt import _TOKEN

_logger = logging.getLogger("pos_cheque_return_management.bank_return")


class ChequeReturnReason(models.Model):
    _name = "pos.cheque.return.reason"
    _description = "Bank Cheque Return Reason"
    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    allow_rebank = fields.Boolean(string="Re-banking Permitted", default=False)
    investigation_required = fields.Boolean(default=False)


class ChequeBankReturn(models.Model):
    _name = "pos.cheque.bank.return"
    _description = "Bank Returned Customer Cheque"
    _inherit = ["mail.thread"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(related="attempt_id.name")
    attempt_id = fields.Many2one("pos.cheque.bank.attempt", required=True, ondelete="restrict", check_company=True)
    hold_id = fields.Many2one(related="attempt_id.hold_id", store=True, index=True)
    company_id = fields.Many2one(related="attempt_id.company_id", store=True)
    currency_id = fields.Many2one(related="attempt_id.currency_id", store=True)
    amount = fields.Monetary(related="hold_id.amount", store=True)
    reason_id = fields.Many2one("pos.cheque.return.reason", required=True, ondelete="restrict")
    reason_note = fields.Text(required=True)
    state = fields.Selection([("reported", "Returned — Accounting Pending"), ("accounted", "Accounting Corrected"), ("recovered", "Replacement / Re-banking Received")], default="reported", readonly=True, tracking=True)
    return_statement_id = fields.Many2one("account.bank.statement.line", string="Bank Return Debit", check_company=True, ondelete="set null")
    correction_journal_id = fields.Many2one("account.journal", string="COD Correction Journal", check_company=True, domain="[('type','=','general'),('company_id','=',company_id)]")
    correction_date = fields.Date(default=fields.Date.context_today, required=True)
    confirmed_by_id = fields.Many2one("res.users", readonly=True)
    confirmed_date = fields.Datetime(readonly=True)
    fee_ids = fields.One2many("pos.cheque.bank.fee", "return_id")
    funding_ids = fields.Many2many("pos.cheque.cod.funding", string="Affected COD Funding", readonly=True)
    funding_reviewed = fields.Boolean(string="Unallocated COD Sources Reviewed")
    funding_review_note = fields.Text(string="Why Listed Sources Need No Further COD Correction")
    correction_move_ids = fields.Many2many("account.move", string="COD Correction Entries", readonly=True)
    original_settlement_line_ids = fields.Many2many("account.move.line", string="Original Settled Debts", readonly=True)
    inline_bank_fee = fields.Monetary(compute="_compute_inline_bank_fee")

    _sql_constraints = [
        ("attempt_return_unique", "unique(attempt_id)", "This banking attempt already has a return report."),
        ("bank_return_unique", "unique(return_statement_id)", "This bank debit is already assigned to a cheque return."),
    ]

    @api.depends("return_statement_id.amount")
    def _compute_inline_bank_fee(self):
        for record in self:
            record.inline_bank_fee = max(0, -record.return_statement_id.amount - record.amount) if record.return_statement_id else 0

    @api.model
    def _check_accountant(self, company):
        if not self.env.user.has_group("pos_cheque_return_management.group_cheque_return_accountant"):
            raise UserError(_("A Cheque Return Accountant must confirm this operation."))
        if company not in self.env.companies:
            raise UserError(_("Select the cheque's company first."))

    @api.model_create_multi
    def create(self, values):
        if self.env.context.get("cheque_workflow") is not _TOKEN:
            raise UserError(_("Report a bank return from its cheque hold."))
        return super().create(values)

    def write(self, vals):
        if vals.get("funding_reviewed"):
            self._check_accountant(self.company_id)
        if self.env.context.get("cheque_workflow") is not _TOKEN:
            if {"state", "attempt_id"}.intersection(vals) or (self.filtered(lambda record: record.state != "reported") and set(vals) != {"fee_ids"}):
                raise UserError(_("Confirmed cheque returns are immutable."))
        return super().write(vals)

    def unlink(self):
        raise UserError(_("Returned cheque history cannot be deleted."))

    def _principal_line(self, strict=True):
        self.ensure_one()
        source = self.attempt_id.receipt_credit_line_id
        statement = self.return_statement_id
        if not source or not statement:
            if strict:
                raise UserError(_("Select the original customer receipt credit and bank return debit first."))
            return self.env["account.move.line"]
        valid = (statement.company_id == self.company_id
                 and statement.journal_id == self.hold_id.deposit_bank_journal_id
                 and statement.move_id.state == "posted" and statement.is_reconciled
                 and statement.amount < 0
                 and not statement.move_id.reversal_move_ids.filtered(lambda move: move.state == "posted"))
        lines = statement.move_id.line_ids.filtered(
            lambda line: line.account_id == source.account_id
            and line.partner_id.commercial_partner_id == self.hold_id.commercial_partner_id
            and line.currency_id == self.currency_id and line.debit > 0
        )
        valid = valid and len(lines) == 1 and not self.currency_id.compare_amounts(lines.debit, self.amount)
        if not valid:
            if strict:
                raise ValidationError(_("Reconcile the bank's negative return transaction to the original customer's receivable account for the full cheque principal. Incoming credits and suspense entries are not a return correction."))
            return self.env["account.move.line"]
        # Additional deductions must be explicit bank expenses, never extra customer principal.
        other = statement.move_id.line_ids - lines - statement.move_id.line_ids.filtered(lambda line: line.account_id == statement.journal_id.default_account_id)
        if other.filtered(lambda line: line.account_id.internal_group != "expense" and not line.tax_repartition_line_id):
            if strict:
                raise ValidationError(_("Separate unrelated transactions from the principal return. Extra deductions on this transaction must be bank-expense lines."))
            return self.env["account.move.line"]
        return lines

    def action_confirm_accounting(self):
        self.ensure_one()
        self._check_accountant(self.company_id)
        if self.state != "reported":
            return True
        _logger.debug("[CHEQUE][RETURN_ACCOUNTING][START] return_id=%s", self.id)
        try:
            with self.env.cr.savepoint():
                self.hold_id._cheque_lock()
                self.invalidate_recordset()
                if self.state != "reported":
                    return True
                self.attempt_id._validate_receipt_credit()
                principal = self._principal_line()
                source = self.attempt_id.receipt_credit_line_id
                settlements = source.matched_debit_ids.debit_move_id
                # Undo only matches involving the failed receipt. Other payments
                # against those invoices keep their own partial reconciliations.
                source.remove_move_reconcile()
                (source | principal).reconcile()
                moves = self._correct_cod_funding()
                self.with_context(cheque_workflow=_TOKEN).write({
                    "state": "accounted", "confirmed_by_id": self.env.uid,
                    "confirmed_date": fields.Datetime.now(),
                    "correction_move_ids": [Command.set(moves.ids)],
                    "original_settlement_line_ids": [Command.set(settlements.ids)],
                })
        except Exception:
            _logger.exception("[CHEQUE][RETURN_ACCOUNTING][ERROR] return_id=%s", self.id)
            raise
        self.hold_id.commercial_partner_id.invalidate_recordset(["credit", "debit"])
        _logger.debug("[CHEQUE][RETURN_ACCOUNTING][END] return_id=%s", self.id)
        return True

    def _correct_cod_funding(self):
        return self.env["account.move"]

    def _settle_original_debts(self, receipt_credit):
        """Recover the exact remaining debts opened by this return, not unrelated invoices."""
        self.ensure_one()
        debts = self.original_settlement_line_ids.filtered(
            lambda line: line.move_id.state == "posted" and line.company_id == self.company_id
            and line.account_id == receipt_credit.account_id
            and line.partner_id.commercial_partner_id == self.hold_id.commercial_partner_id
            and line.amount_residual > 0 and not line.reconciled
        )
        if debts and receipt_credit.amount_residual < 0 and not receipt_credit.reconciled:
            (debts | receipt_credit).reconcile()
