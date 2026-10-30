import logging

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .attempt import _TOKEN

_logger = logging.getLogger("pos_cheque_return_management.hold")


class ChequeHold(models.Model):
    _inherit = "pos.uncleared.payment.hold"

    state = fields.Selection(selection_add=[("returned", "Cheque Returned"), ("rebank_pending", "Re-banking Pending"), ("replaced", "Replaced Cheque")], ondelete={"returned": "set default", "rebank_pending": "set default", "replaced": "set default"})
    bank_attempt_ids = fields.One2many("pos.cheque.bank.attempt", "hold_id", readonly=True)
    active_attempt_id = fields.Many2one("pos.cheque.bank.attempt", readonly=True, copy=False)
    cheque_return_ids = fields.One2many("pos.cheque.bank.return", "hold_id", readonly=True)
    cheque_funding_ids = fields.One2many("pos.cheque.cod.funding", "hold_id", readonly=True)
    replacement_for_id = fields.Many2one("pos.uncleared.payment.hold", string="Replaces Cheque", readonly=True, copy=False, check_company=True, ondelete="restrict")

    @api.model_create_multi
    def create(self, values):
        if self.env.context.get("cheque_workflow") is not _TOKEN and any(vals.get("state") in ("returned", "rebank_pending", "replaced") for vals in values):
            raise UserError(_("Create a normal receipt hold, then use the bank return workflow."))
        return super().create(values)

    def write(self, vals):
        trusted = self.env.context.get("cheque_workflow") is _TOKEN
        protected = {"active_attempt_id", "replacement_for_id"}
        transition = "state" in vals and (
            vals["state"] in ("returned", "rebank_pending", "replaced")
            or self.filtered(lambda hold: hold.state in ("returned", "rebank_pending", "replaced"))
        )
        if not trusted and (protected.intersection(vals) or transition):
            raise UserError(_("Use the bank return/recovery workflow to change a returned cheque."))
        return super().write(vals)

    def _cheque_lock(self):
        self.ensure_one()
        # Serialize financial operations for this instrument; ORM has no row-lock API.
        self.env.cr.execute("SELECT id FROM pos_uncleared_payment_hold WHERE id=%s FOR UPDATE", [self.id])
        self.invalidate_recordset()

    def _cheque_receipt_candidates(self):
        self.ensure_one()
        moves = self.account_move_id | self.cod_account_move_id | self.pos_session_id.move_id
        return moves.line_ids.filtered(
            lambda line: line.move_id.state == "posted" and line.account_id.account_type == "asset_receivable"
            and line.partner_id.commercial_partner_id == self.commercial_partner_id
            and not self.currency_id.compare_amounts(line.credit, self.amount)
        )

    def _cheque_original_attempt(self, receipt=False):
        self.ensure_one()
        if self.active_attempt_id:
            if receipt and self.active_attempt_id.receipt_credit_line_id != receipt:
                self.active_attempt_id.write({"receipt_credit_line_id": receipt.id})
            return self.active_attempt_id
        candidates = receipt or self._cheque_receipt_candidates()
        attempt = self.env["pos.cheque.bank.attempt"].with_context(cheque_workflow=_TOKEN).create({
            "hold_id": self.id, "number": 1,
            "receipt_credit_line_id": candidates.id if len(candidates) == 1 else False,
            "transfer_move_id": self.linked_transfer_move_id.id,
            "state": "cleared" if self.state == "accounting_cleared" else "deposited",
        })
        self.with_context(cheque_workflow=_TOKEN).write({"active_attempt_id": attempt.id})
        return attempt.with_env(self.env)

    def action_open_cheque_return(self):
        self.ensure_one()
        self._upg_check_transfer_link_access()
        return {
            "type": "ir.actions.act_window", "res_model": "pos.cheque.return.wizard",
            "view_mode": "form", "target": "new", "name": _("Record Bank Return"),
            "context": {"default_hold_id": self.id},
        }

    def action_open_cheque_recovery(self):
        action = self.action_open_cheque_return()
        action["name"] = _("Re-bank / Replace Returned Cheque")
        action["context"]["default_operation"] = "rebank"
        return action

    def action_open_cheque_funding(self):
        self.ensure_one()
        self._upg_check_transfer_link_access()
        return {
            "type": "ir.actions.act_window", "name": _("Link COD Funding"),
            "res_model": "pos.cheque.funding.wizard", "view_mode": "form", "target": "new",
            "context": {"default_hold_id": self.id},
        }

    def _cheque_report_return(self, reason, note, receipt=False, statement=False):
        self.ensure_one()
        self._upg_check_transfer_link_access()
        self._cheque_lock()
        attempt = self._cheque_original_attempt(receipt)
        if attempt.return_ids:
            raise UserError(_("This banking attempt has already been reported returned."))
        if self.state in ("cancelled", "replaced"):
            raise UserError(_("A cancelled or replaced cheque cannot be returned again."))
        if not note.strip():
            raise ValidationError(_("Record the bank's explanation."))
        if statement and (statement.company_id != self.company_id or statement.journal_id != self.deposit_bank_journal_id
                          or statement.amount >= 0 or self.currency_id.compare_amounts(-statement.amount, self.amount) < 0):
            raise ValidationError(_("Select a Money Out transaction in this cheque's receiving bank covering the returned principal. A refund credit for your own outgoing cheque is not a customer-cheque return."))
        _logger.debug("[CHEQUE][REPORT_RETURN][START] hold_id=%s attempt_id=%s", self.id, attempt.id)
        case = self.env["pos.cheque.bank.return"].with_context(cheque_workflow=_TOKEN).create({
            "attempt_id": attempt.id, "reason_id": reason.id, "reason_note": note,
            "return_statement_id": statement.id if statement else False,
        })
        self.env["pos.cheque.cod.funding"]._capture_receipt_funding(self, attempt.receipt_credit_line_id)
        attempt._set_state("returned")
        self.with_context(cheque_workflow=_TOKEN).write({
            "state": "returned", "transfer_link_manual_release": False,
            "bank_statement_line_id": False, "confirmed_bank_statement_line_ids": [Command.clear()],
            "accounting_detection_note": _("Bank return reported; previous manual authorization no longer releases this cheque."),
        })
        self._cheque_cancel_reservations()
        _logger.debug("[CHEQUE][REPORT_RETURN][END] hold_id=%s return_id=%s", self.id, case.id)
        return case.with_env(self.env)

    def _cheque_cancel_reservations(self):
        reservations = self.env["pos.cod.session.deposit.reservation"].search([
            ("source_payment_ids", "in", self.pos_payment_id.ids),
            ("company_id", "=", self.company_id.id),
            ("state", "in", ("reserved", "error")),
        ])
        # This immutable/read-only audit model is normally transitioned by its
        # owning workflows. A confirmed return report owns cancellation here.
        reservations.sudo().write({"state": "cancelled", "error_message": _("Source cheque returned. Reserve again using valid funds.")})
        return reservations

    def _upg_mark_manual_cleared(self, reason, reference=False):
        if self.filtered(lambda hold: hold.state in ("returned", "rebank_pending", "replaced")):
            raise UserError(_("A returned cheque cannot be manually released. Confirm a new banking attempt or replacement instead."))
        return super()._upg_mark_manual_cleared(reason, reference)

    @api.model
    def _upg_pending_amounts_for_partner(self, commercial_partner, company_id=False):
        result = super()._upg_pending_amounts_for_partner(commercial_partner, company_id)
        domain = [("commercial_partner_id", "=", commercial_partner.id), ("state", "in", ("returned", "rebank_pending")), ("cod_collection_id", "=", False)]
        if company_id:
            domain.append(("company_id", "=", company_id))
        holds = self.sudo().search(domain)
        blocked = self.browse()
        for hold in holds:
            attempt = hold.active_attempt_id
            if hold.state == "rebank_pending":
                if attempt.receipt_credit_line_id.move_id.state == "posted":
                    blocked |= hold
            elif (attempt.return_ids.state == "reported" or attempt.receipt_credit_line_id.move_id.state == "posted") and not attempt.return_ids._principal_line(strict=False):
                blocked |= hold
        opened = blocked.filtered(lambda hold: hold.pos_session_id.state == "opened")
        result["pending_total"] += sum(blocked.mapped("amount"))
        result["pending_open_session"] += sum(opened.mapped("amount"))
        result["pending_accounting_effect"] += sum((blocked - opened).mapped("amount"))
        result["hold_count"] += len(blocked)
        result["hold_ids"] += blocked.ids
        return result

    def _cheque_recover_cod(self, receipt_credit, funding_hold=False):
        return self.env["account.move"]

    @api.model
    def _upg_pos_visible_domain(self):
        return ["|", ("state", "in", ("returned", "rebank_pending"))] + super()._upg_pos_visible_domain()

    @api.model
    def cron_detect_accounting_reconciliation(self):
        result = super().cron_detect_accounting_reconciliation()
        recovered = self.sudo().search([("state", "=", "accounting_cleared"), ("active_attempt_id.number", ">", 1)])
        for hold in recovered:
            try:
                with self.env.cr.savepoint():
                    self.env["pos.uncleared.payment.accounting.detector"].sudo().upg_check_hold(hold)
            except Exception:
                _logger.exception("[CHEQUE][RECHECK_RECOVERY][ERROR] hold_id=%s", hold.id)
        return result


class ChequeDetector(models.AbstractModel):
    _inherit = "pos.uncleared.payment.accounting.detector"

    @api.model
    def upg_check_hold(self, hold):
        if hold.state == "accounting_cleared" and hold.active_attempt_id.number > 1:
            try:
                valid = hold.active_attempt_id._bank_evidence_is_valid()
            except ValidationError:
                valid = False
            if not valid:
                hold.with_context(cheque_workflow=_TOKEN).write({
                    "state": "rebank_pending", "bank_statement_line_id": False,
                    "accounting_detection_note": _("Re-banked receipt accounting changed. Accountant review is required; a bank return must still be recorded separately."),
                })
            return valid
        if hold.state in ("returned", "rebank_pending", "replaced"):
            return False
        return super().upg_check_hold(hold)
