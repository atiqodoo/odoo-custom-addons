import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger("pos_cheque_return_management.attempt")
_TOKEN = object()


class ChequeBankAttempt(models.Model):
    _name = "pos.cheque.bank.attempt"
    _description = "Cheque Banking Attempt"
    _inherit = ["mail.thread"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(compute="_compute_name", store=True)
    hold_id = fields.Many2one("pos.uncleared.payment.hold", required=True, ondelete="restrict", index=True, check_company=True)
    company_id = fields.Many2one(related="hold_id.company_id", store=True)
    hold_state = fields.Selection(related="hold_id.state")
    currency_id = fields.Many2one(related="hold_id.currency_id", store=True)
    number = fields.Integer(required=True, default=1)
    state = fields.Selection([("deposited", "Awaiting Bank Confirmation"), ("cleared", "Received"), ("returned", "Returned")], default="deposited", readonly=True, tracking=True)
    receipt_credit_line_id = fields.Many2one("account.move.line", string="Customer Receipt Credit", check_company=True, ondelete="set null")
    transfer_move_id = fields.Many2one("account.move", check_company=True, ondelete="set null")
    bank_credit_statement_id = fields.Many2one("account.bank.statement.line", string="Re-banked Credit", check_company=True, ondelete="set null")
    return_ids = fields.One2many("pos.cheque.bank.return", "attempt_id")

    _sql_constraints = [
        ("attempt_number_unique", "unique(hold_id,number)", "This banking attempt already exists."),
        ("receipt_attempt_unique", "unique(receipt_credit_line_id)", "A receipt credit can fund only one cheque banking attempt. Do not reuse the failed receipt or another cheque's receipt."),
    ]

    @api.depends("hold_id.name", "number")
    def _compute_name(self):
        for record in self:
            record.name = "%s / %s" % (record.hold_id.name, record.number)

    @api.model_create_multi
    def create(self, values):
        if self.env.context.get("cheque_workflow") is not _TOKEN:
            raise UserError(_("Create banking attempts from the cheque workflow."))
        _logger.debug("[CHEQUE][BANK_ATTEMPT][START] count=%s", len(values))
        for vals in values:
            receipt = vals.get("receipt_credit_line_id")
            if receipt and self.sudo().search_count([("receipt_credit_line_id", "=", receipt)]):
                raise ValidationError(_("This receipt credit already belongs to a banking attempt. Re-banking or replacement must use its own new receipt."))
        records = super().create(values)
        _logger.debug("[CHEQUE][BANK_ATTEMPT][END] attempt_ids=%s", records.ids)
        return records

    def write(self, vals):
        filling_source = set(vals) == {"receipt_credit_line_id"} and not self.receipt_credit_line_id and not self.return_ids.filtered(lambda case: case.state != "reported")
        if self.env.context.get("cheque_workflow") is not _TOKEN and ({"state", "hold_id", "number"}.intersection(vals) or (self.filtered(lambda record: record.state != "deposited") and not filling_source)):
            raise UserError(_("Completed banking attempts are immutable. Use the return workflow."))
        return super().write(vals)

    def unlink(self):
        raise UserError(_("Banking attempts are audit records and cannot be deleted."))

    @api.constrains("receipt_credit_line_id", "hold_id")
    def _validate_receipt_credit(self):
        for record in self.filtered("receipt_credit_line_id"):
            line = record.receipt_credit_line_id
            hold = record.hold_id
            if (line.move_id.state != "posted" or line.company_id != hold.company_id
                    or line.move_id.reversal_move_ids.filtered(lambda move: move.state == "posted")
                    or line.account_id.account_type != "asset_receivable"
                    or line.partner_id.commercial_partner_id != hold.commercial_partner_id
                    or line.currency_id != hold.currency_id
                    or hold.currency_id != hold.company_id.currency_id
                    or hold.currency_id.compare_amounts(line.credit, hold.amount)):
                raise ValidationError(_("Select the exact posted company-currency customer receivable credit for this cheque. Aggregated receipt credits must be separated by an accountant first."))

    def _set_state(self, state):
        self.with_context(cheque_workflow=_TOKEN).write({"state": state})

    def _bank_evidence_is_valid(self):
        self.ensure_one()
        self._validate_receipt_credit()
        statement = self.bank_credit_statement_id
        return bool(
            statement and statement.move_id == self.receipt_credit_line_id.move_id
            and statement.journal_id == self.hold_id.deposit_bank_journal_id
            and statement.move_id.state == "posted" and statement.is_reconciled
            and not statement.move_id.reversal_move_ids.filtered(lambda move: move.state == "posted")
            and not self.currency_id.compare_amounts(statement.amount, self.hold_id.amount)
        )

    def action_confirm_rebank(self):
        self.ensure_one()
        self.env["pos.cheque.bank.return"]._check_accountant(self.company_id)
        review_only = self.state == "cleared" and self.hold_id.state == "rebank_pending"
        if (self.state != "deposited" and not review_only) or self.number <= 1:
            raise UserError(_("Only an awaiting re-banking attempt can be finalized here."))
        _logger.debug("[CHEQUE][REBANK][START] attempt_id=%s", self.id)
        with self.env.cr.savepoint():
            self.hold_id._cheque_lock()
            self._validate_receipt_credit()
            statement = self.bank_credit_statement_id
            line = self.receipt_credit_line_id
            if not self._bank_evidence_is_valid():
                raise UserError(_("Select a reconciled positive bank credit whose posted customer receivable credit is the new receipt. Do not create another POS deposit."))
            if not review_only:
                self.hold_id._cheque_recover_cod(line)
            self._set_state("cleared")
            self.hold_id.with_context(cheque_workflow=_TOKEN).write({"state": "pending", "transfer_link_manual_release": False})
            self.hold_id._upg_mark_accounting_cleared()
            self.hold_id.write({"bank_statement_line_id": statement.id})
        _logger.debug("[CHEQUE][REBANK][END] attempt_id=%s", self.id)
        self.hold_id.commercial_partner_id.invalidate_recordset(["credit", "debit"])
        return True
