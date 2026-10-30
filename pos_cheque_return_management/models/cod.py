import logging

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .attempt import _TOKEN

_logger = logging.getLogger("pos_cheque_return_management.cod")


class ChequeCodCollection(models.Model):
    _inherit = "pos.cod.collection"
    kind = fields.Selection(selection_add=[("cheque_return", "Cheque Returned"), ("cheque_recovery", "Returned Cheque Recovered")], ondelete={"cheque_return": "cascade", "cheque_recovery": "cascade"})
    cheque_funding_id = fields.Many2one("pos.cheque.cod.funding", readonly=True, copy=False, ondelete="restrict")
    cheque_return_id = fields.Many2one("pos.cheque.bank.return", readonly=True, copy=False, ondelete="restrict")

    @api.model_create_multi
    def create(self, values):
        if any(vals.get("kind") in ("cheque_return", "cheque_recovery") for vals in values) and self.env.context.get("cheque_workflow") is not _TOKEN:
            raise UserError(_("Cheque adjustments can only be created by the bank return workflow."))
        return super().create(values)

    def write(self, vals):
        if self.filtered(lambda record: record.kind in ("cheque_return", "cheque_recovery")):
            raise UserError(_("Cheque adjustment logs are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda record: record.kind in ("cheque_return", "cheque_recovery")):
            raise UserError(_("Cheque adjustment logs cannot be deleted."))
        return super().unlink()


class ChequeCodOrder(models.Model):
    _inherit = "pos.order"
    # POS users may see the order's totals without gaining access to the
    # immutable deposit-audit models used internally to derive those totals.
    cod_deposit_applied_amount = fields.Monetary(compute_sudo=True)
    cod_session_deposit_reserved_amount = fields.Monetary(compute_sudo=True)
    upg_cod_uncleared_state = fields.Selection(selection_add=[("returned", "Cheque Returned"), ("rebank_pending", "Re-banking Pending"), ("replaced", "Replaced")])

    def _cheque_payment_adjustment(self):
        self.ensure_one()
        records = self.cod_collection_ids
        return sum(records.filtered(lambda record: record.kind == "cheque_recovery").mapped("amount")) - sum(records.filtered(lambda record: record.kind == "cheque_return").mapped("amount"))

    @api.depends("amount_total", "cod_collection_ids.amount", "cod_collection_ids.kind", "cod_deposit_application_ids.amount", "cod_deposit_application_ids.state", "cod_session_deposit_reservation_ids.amount", "cod_session_deposit_reservation_ids.state")
    def _compute_cod_amounts(self):
        super()._compute_cod_amounts()
        for order in self:
            adjustment = order._cheque_payment_adjustment()
            order.cod_amount_paid = max(0, order.cod_amount_paid + adjustment)
            order.cod_amount_open = max(0, order.amount_total - order.cod_amount_paid - order.cod_amount_returned - order.cod_session_deposit_reserved_amount)

    def _cod_paid_total(self):
        return super()._cod_paid_total() + self._cheque_payment_adjustment()

    def _compute_upg_cod_uncleared_status(self):
        super()._compute_upg_cod_uncleared_status()
        for order in self:
            returned = order.cod_collection_ids.filtered(lambda record: record.kind == "cheque_return")
            if returned and order._cod_open_amount() > order.currency_id.rounding:
                order.upg_cod_uncleared_state = "returned"
                order.upg_cod_uncleared_label = _("Cheque Returned — Amount Outstanding")


class ChequeReturnCodEffects(models.Model):
    _inherit = "pos.cheque.bank.return"

    def _correct_cod_funding(self):
        moves = super()._correct_cod_funding()
        Funding = self.env["pos.cheque.cod.funding"]
        source = self.attempt_id.receipt_credit_line_id
        fundings = Funding.search([("hold_id", "=", self.hold_id.id), ("returned_by_id", "=", False)])
        # Existing applications can identify the receipt but lack per-cheque allocation
        # after somebody manually unreconciles it. Require explicit reviewed allocation.
        applications = self.env["pos.cod.deposit.application"].search([
            ("state", "=", "posted"), ("source_credit_line_ids", "in", source.ids),
        ])
        if applications - fundings.application_id and self.attempt_id.number == 1:
            if not self.funding_reviewed or not (self.funding_review_note or "").strip():
                raise UserError(_("Some COD applications list this receipt without a proven cheque allocation. Link the affected funding, or have an accountant document why these candidate sources were unused/already replaced by valid funds."))
        for funding in fundings:
            move = self.env["account.move"]
            order = funding.order_id
            order._cdds_lock_order()
            if funding.debit_line_id:
                journal = self.correction_journal_id
                if not journal or journal.type != "general" or journal.company_id != self.company_id:
                    raise UserError(_("Choose a general journal for the COD correction entries."))
                move = self.env["account.move"].create({
                    "journal_id": journal.id, "date": self.correction_date,
                    "ref": _("Cheque return %(case)s — COD %(order)s", case=self.id, order=order.id),
                    "line_ids": [
                        Command.create({"account_id": funding.credit_line_id.account_id.id, "partner_id": self.hold_id.commercial_partner_id.id, "debit": funding.amount}),
                        Command.create({"account_id": funding.debit_line_id.account_id.id, "partner_id": self.hold_id.commercial_partner_id.id, "credit": funding.amount}),
                    ],
                })
                move.action_post()
                default_credit = move.line_ids.filtered(lambda line: line.credit > 0)
                cod_debit = move.line_ids - default_credit
                # Restore only this application's share of the COD receivable.
                original_debits = funding.credit_line_id.matched_debit_ids.debit_move_id
                funding.credit_line_id.remove_move_reconcile()
                (funding.credit_line_id | cod_debit).reconcile()
                remaining = (original_debits | funding.credit_line_id).filtered(lambda line: not line.reconciled)
                if remaining.filtered(lambda line: line.amount_residual > 0) and remaining.filtered(lambda line: line.amount_residual < 0):
                    remaining.reconcile()
                (funding.debit_line_id | default_credit).reconcile()
                moves |= move
            funding.with_context(cheque_workflow=_TOKEN).write({"returned_by_id": self.id})
            self.env["pos.cod.collection"].with_context(cheque_workflow=_TOKEN).create({
                "order_id": order.id, "session_id": self.hold_id.pos_session_id.id,
                "kind": "cheque_return", "amount": funding.amount,
                "cheque_funding_id": funding.id, "cheque_return_id": self.id,
                "move_id": move.id or self.return_statement_id.move_id.id,
                "note": _("Bank-returned cheque; original receipt and application retained."),
            })
            order.invalidate_recordset()
            order.write({"cod_state": "paid" if order._cod_open_amount() <= order.currency_id.rounding else "partial"})
        self.with_context(cheque_workflow=_TOKEN).write({"funding_ids": [Command.set(fundings.ids)]})
        return moves


class ChequeRecoveryCodEffects(models.Model):
    _inherit = "pos.uncleared.payment.hold"

    def _cheque_recover_cod(self, receipt_credit, funding_hold=False):
        moves = super()._cheque_recover_cod(receipt_credit, funding_hold)
        self.ensure_one()
        cases = self.cheque_return_ids.filtered(lambda case: case.state == "accounted").sorted("id")
        if not cases:
            return moves
        case = cases[-1]
        for previous in case.funding_ids:
            order = previous.order_id
            order._cdds_lock_order()
            amount = min(previous.amount, order._cod_open_amount())
            if self.currency_id.is_zero(amount):
                continue
            cod_account = previous.credit_line_id.account_id
            already_matched = sum(receipt_credit.matched_debit_ids.filtered(
                lambda partial: partial.debit_move_id.move_id == order.cod_ar_move_id
            ).mapped("amount")) if receipt_credit.account_id == cod_account else 0
            if self.currency_id.compare_amounts(-receipt_credit.amount_residual + already_matched, amount) < 0:
                raise UserError(_("The replacement/re-banked receipt has insufficient unallocated credit to restore these COD payments."))
            move = self.env["account.move"]
            debit = self.env["account.move.line"]
            credit = receipt_credit
            if receipt_credit.account_id != cod_account:
                if not case.correction_journal_id:
                    raise UserError(_("Choose a COD correction journal on the return record first."))
                move = self.env["account.move"].create({
                    "journal_id": case.correction_journal_id.id, "date": fields.Date.context_today(self),
                    "ref": _("Recovered cheque %(hold)s — COD %(order)s", hold=self.id, order=order.id),
                    "line_ids": [
                        Command.create({"account_id": receipt_credit.account_id.id, "partner_id": self.commercial_partner_id.id, "debit": amount}),
                        Command.create({"account_id": cod_account.id, "partner_id": self.commercial_partner_id.id, "credit": amount}),
                    ],
                })
                move.action_post()
                debit = move.line_ids.filtered(lambda line: line.debit > 0)
                credit = move.line_ids - debit
                (receipt_credit | debit).reconcile()
                moves |= move
            invoice_lines = order.cod_ar_move_id.line_ids.filtered(
                lambda line: line.account_id == cod_account and line.amount_residual > 0
            )
            if not invoice_lines and self.currency_id.compare_amounts(already_matched, amount) < 0:
                raise UserError(_("The COD order has no outstanding posted receivable to settle. Review its accounting first."))
            if invoice_lines and self.currency_id.compare_amounts(already_matched, amount) < 0:
                (invoice_lines | credit).reconcile()
            funding = self.env["pos.cheque.cod.funding"].with_context(cheque_workflow=_TOKEN).create({
                "hold_id": (funding_hold or self).id, "order_id": order.id, "amount": amount,
                "debit_line_id": debit.id, "credit_line_id": credit.id,
                "recovery_of_id": previous.id,
            })
            self.env["pos.cod.collection"].with_context(cheque_workflow=_TOKEN).create({
                "order_id": order.id, "session_id": self.pos_session_id.id,
                "kind": "cheque_recovery", "amount": amount, "move_id": move.id or receipt_credit.move_id.id,
                "cheque_funding_id": funding.id, "cheque_return_id": case.id,
            })
            order.invalidate_recordset()
            order.write({"cod_state": "paid" if order._cod_open_amount() <= order.currency_id.rounding else "partial"})
        case._settle_original_debts(receipt_credit)
        case.with_context(cheque_workflow=_TOKEN).write({"state": "recovered"})
        return moves
