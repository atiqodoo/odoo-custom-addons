import logging

from odoo import fields, models, _
from odoo.exceptions import UserError
from ..models.attempt import _TOKEN

_logger = logging.getLogger("pos_cheque_return_management.workflow")


class ChequeReturnWizard(models.TransientModel):
    _name = "pos.cheque.return.wizard"
    _description = "Report, Re-bank or Replace a Customer Cheque"

    hold_id = fields.Many2one("pos.uncleared.payment.hold", required=True, readonly=True)
    company_id = fields.Many2one(related="hold_id.company_id")
    operation = fields.Selection([("report", "Record Bank Return"), ("rebank", "Re-bank Same Cheque"), ("replace", "Receive Replacement Cheque")], default="report", required=True)
    reason_id = fields.Many2one("pos.cheque.return.reason")
    note = fields.Text()
    receipt_credit_line_id = fields.Many2one("account.move.line", string="Customer Receipt Credit", domain="[('company_id','=',company_id),('parent_state','=','posted'),('credit','>',0),('account_id.account_type','=','asset_receivable')]")
    statement_id = fields.Many2one("account.bank.statement.line", string="Bank Transaction", domain="[('company_id','=',company_id)]")
    replacement_hold_id = fields.Many2one("pos.uncleared.payment.hold", domain="[('company_id','=',company_id),('id','!=',hold_id)]")

    def action_apply(self):
        self.ensure_one()
        _logger.debug("[CHEQUE][WORKFLOW][START] hold_id=%s operation=%s", self.hold_id.id, self.operation)
        try:
            result = self._apply_workflow()
        except Exception:
            _logger.exception("[CHEQUE][WORKFLOW][ERROR] hold_id=%s operation=%s", self.hold_id.id, self.operation)
            raise
        _logger.debug("[CHEQUE][WORKFLOW][END] hold_id=%s operation=%s", self.hold_id.id, self.operation)
        return result

    def _apply_workflow(self):
        self.ensure_one()
        hold = self.hold_id
        hold._upg_check_transfer_link_access()
        if self.operation == "report":
            if not self.reason_id or not (self.note or "").strip():
                raise UserError(_("Select the bank's return reason and record its explanation."))
            case = hold._cheque_report_return(self.reason_id, self.note, self.receipt_credit_line_id, self.statement_id)
            return {"type": "ir.actions.act_window", "res_model": "pos.cheque.bank.return", "res_id": case.id, "view_mode": "form", "target": "current"}
        self.env["pos.cheque.bank.return"]._check_accountant(hold.company_id)
        with self.env.cr.savepoint():
            hold._cheque_lock()
            if hold.state != "returned" or not hold.cheque_return_ids.filtered(lambda case: case.state == "accounted"):
                raise UserError(_("Complete the bank-return accounting before re-banking or replacing the cheque."))
            hold.active_attempt_id.return_ids._principal_line()
            source = self.receipt_credit_line_id
            if not source:
                raise UserError(_("Select the new posted receipt credit. Never reuse the failed receipt."))
            if self.operation == "rebank":
                case = hold.active_attempt_id.return_ids
                if not case.reason_id.allow_rebank:
                    raise UserError(_("This return reason does not permit re-banking. Obtain a valid replacement payment."))
                if source.account_id != hold.active_attempt_id.receipt_credit_line_id.account_id:
                    raise UserError(_("Re-bank this instrument against its original customer receivable account. Do not strand an ordinary deposit credit in a different receivable ledger."))
                attempt = self.env["pos.cheque.bank.attempt"].with_context(cheque_workflow=_TOKEN).create({
                    "hold_id": hold.id, "number": max(hold.bank_attempt_ids.mapped("number")) + 1,
                    "receipt_credit_line_id": source.id, "bank_credit_statement_id": self.statement_id.id,
                })
                hold._upg_detach_transfer(_("New banking attempt started; previous attempt remains in history."))
                hold.with_context(cheque_workflow=_TOKEN).write({"active_attempt_id": attempt.id, "state": "rebank_pending", "transfer_link_manual_release": False})
                return {"type": "ir.actions.act_window", "res_model": "pos.cheque.bank.attempt", "res_id": attempt.id, "view_mode": "form", "target": "current"}
            replacement = self.replacement_hold_id
            if (not replacement or replacement == hold or replacement.company_id != hold.company_id
                    or replacement.commercial_partner_id != hold.commercial_partner_id
                    or replacement.currency_id != hold.currency_id
                    or hold.currency_id.compare_amounts(replacement.amount, hold.amount)
                    or replacement.replacement_for_id):
                raise UserError(_("Select an unused replacement cheque for the same customer, company, currency and principal."))
            detector = self.env["pos.uncleared.payment.accounting.detector"]
            if not detector.upg_check_hold(replacement) or replacement.state != "accounting_cleared":
                raise UserError(_("The replacement must have independently confirmed bank clearance first."))
            case = hold.active_attempt_id.return_ids
            if (source.account_id != hold.active_attempt_id.receipt_credit_line_id.account_id
                    and hold.currency_id.compare_amounts(sum(case.funding_ids.mapped("amount")), hold.amount)):
                raise UserError(_("Use the original receivable ledger for replacement funds that include unused deposits or ordinary purchases."))
            replacement._cheque_original_attempt(source)._validate_receipt_credit()
            hold._cheque_recover_cod(source, funding_hold=replacement)
            replacement.with_context(cheque_workflow=_TOKEN).write({"replacement_for_id": hold.id})
            hold.with_context(cheque_workflow=_TOKEN).write({"state": "replaced"})
        return {"type": "ir.actions.act_window_close"}


class ChequeFundingWizard(models.TransientModel):
    _name = "pos.cheque.funding.wizard"
    _description = "Identify Cheque Funding in a COD Deposit Application"
    hold_id = fields.Many2one("pos.uncleared.payment.hold", required=True, readonly=True)
    company_id = fields.Many2one(related="hold_id.company_id")
    currency_id = fields.Many2one(related="hold_id.currency_id")
    application_id = fields.Many2one("pos.cod.deposit.application", required=True, domain="[('company_id','=',company_id),('state','=','posted')]")
    amount = fields.Monetary(required=True)

    def action_apply(self):
        self.ensure_one()
        self.env["pos.cheque.cod.funding"].create({"hold_id": self.hold_id.id, "application_id": self.application_id.id, "amount": self.amount})
        return {"type": "ir.actions.act_window_close"}
