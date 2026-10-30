import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger("pos_cheque_return_management.fees")


class ChequeBankFee(models.Model):
    _name = "pos.cheque.bank.fee"
    _description = "Actual Bank Cheque Fee or Fee Refund"
    _check_company_auto = True

    return_id = fields.Many2one("pos.cheque.bank.return", required=True, ondelete="restrict", check_company=True)
    company_id = fields.Many2one(related="return_id.company_id", store=True)
    currency_id = fields.Many2one(related="return_id.currency_id", store=True)
    statement_id = fields.Many2one("account.bank.statement.line", check_company=True, ondelete="set null")
    kind = fields.Selection([("charge", "Business Bank Charge"), ("refund", "Bank Refund of Charge")], required=True)
    refund_of_id = fields.Many2one("pos.cheque.bank.fee", check_company=True, ondelete="restrict", help="Select the separate charge being refunded. Leave empty only for a fee included in the principal return transaction.")
    amount = fields.Monetary(compute="_compute_amount", store=True)

    _sql_constraints = [("fee_bank_transaction_unique", "unique(statement_id)", "This bank fee transaction is already recorded.")]

    @api.depends("statement_id.amount")
    def _compute_amount(self):
        for record in self:
            record.amount = abs(record.statement_id.amount)

    @api.constrains("statement_id", "return_id", "kind", "refund_of_id")
    def _validate_fee(self):
        for record in self:
            record.return_id._check_accountant(record.company_id)
            statement = record.statement_id
            lines = statement.move_id.line_ids.filtered(lambda line: line.account_id != statement.journal_id.default_account_id)
            if (statement == record.return_id.return_statement_id
                    or statement.journal_id != record.return_id.hold_id.deposit_bank_journal_id
                    or statement.company_id != record.company_id
                    or not statement.is_reconciled or statement.move_id.state != "posted"
                    or not lines.filtered(lambda line: line.account_id.internal_group == "expense")
                    or lines.filtered(lambda line: line.account_id.internal_group != "expense" and not line.tax_repartition_line_id)
                    or (record.kind == "charge" and statement.amount >= 0)
                    or (record.kind == "refund" and statement.amount <= 0)):
                raise ValidationError(_("Select a separate, reconciled bank-expense transaction with the correct debit/credit direction. Principal and fees cannot use the same fee record."))
            if record.kind == "refund":
                charge = record.refund_of_id
                if charge:
                    if charge.kind != "charge" or charge.return_id != record.return_id:
                        raise ValidationError(_("Select the original business bank charge being refunded."))
                    refunds = self.search([("refund_of_id", "=", charge.id)])
                    budget = charge.amount
                else:
                    if not record.return_id._principal_line(strict=False) or not record.return_id.inline_bank_fee:
                        raise ValidationError(_("Select the separate charge, or identify a verified fee included in the principal return."))
                    refunds = self.search([("return_id", "=", record.return_id.id), ("kind", "=", "refund"), ("refund_of_id", "=", False)])
                    budget = record.return_id.inline_bank_fee
                if record.currency_id.compare_amounts(sum(refunds.mapped("amount")), budget) > 0:
                    raise ValidationError(_("Recorded fee refunds exceed the original charge."))
            elif record.refund_of_id:
                raise ValidationError(_("Only fee refunds can identify an original charge."))

    @api.model_create_multi
    def create(self, values):
        _logger.debug("[CHEQUE][BANK_FEE][START] count=%s", len(values))
        records = super().create(values)
        _logger.debug("[CHEQUE][BANK_FEE][END] fee_ids=%s", records.ids)
        return records

    def write(self, vals):
        raise UserError(_("Fee evidence is immutable. Correct the accounting and record a separate refund."))

    def unlink(self):
        raise UserError(_("Bank fee evidence cannot be deleted."))
