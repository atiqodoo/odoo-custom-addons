import logging
from contextlib import nullcontext

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)

DEPOSIT_FIELDS = {"pcd_hold_id", "pcd_deposit_date", "pcd_receipt_ids"}


class AccountMove(models.Model):
    _inherit = "account.move"

    pcd_hold_id = fields.Many2one(
        "pos.uncleared.payment.hold", string="Cheque Being Deposited",
        check_company=True, copy=False, index=True, ondelete="restrict", tracking=True,
    )
    pcd_deposit_date = fields.Date(string="Actual Cheque Deposit Date", copy=False, tracking=True)
    pcd_receipt_ids = fields.Many2many(
        "ir.attachment", "pcd_move_receipt_rel", "move_id", "attachment_id",
        string="Bank Deposit Receipts", copy=False,
    )
    pcd_requires_receipt = fields.Boolean(compute="_compute_pcd_requires_receipt")

    _sql_constraints = [(
        "pcd_cheque_unique", "unique(pcd_hold_id)",
        "This cheque is already selected on another deposit entry.",
    )]

    @api.depends("line_ids.account_id", "line_ids.debit", "line_ids.credit", "company_id", "pcd_hold_id")
    def _compute_pcd_requires_receipt(self):
        policy = self.env["pos.cheque.deposit.policy"]
        configurations = {company.id: policy._configurations(company) for company in self.company_id}
        for move in self:
            move.pcd_requires_receipt = bool(move.pcd_hold_id) or policy._requires_receipt(
                move, configurations=configurations[move.company_id.id],
            )

    def _pcd_check_posting(self):
        validator = self.env["pos.cheque.deposit.validation"]
        policy = self.env["pos.cheque.deposit.policy"]
        configurations = {company.id: policy._configurations(company) for company in self.company_id}
        for move in self:
            if move.pcd_hold_id or policy._requires_receipt(move, configurations=configurations[move.company_id.id]):
                if not self.env.su and not self.env.user.has_group("account.group_account_invoice"):
                    raise AccessError(_("Accounting posting permissions are required."))
                if move.pcd_hold_id:
                    move.pcd_hold_id._upg_check_transfer_link_access()
                validator._validate(move)

    @api.model_create_multi
    def create(self, vals_list):
        with self.env.cr.savepoint() if any(vals.get("state") == "posted" for vals in vals_list) else nullcontext():
            moves = super().create(vals_list)
            # Direct ORM/import creation in posted state must obey the same rule.
            posted = moves.filtered(lambda move: move.state == "posted")
            posted._pcd_check_posting()
            posted._pcd_link_posted_cheques()
        return moves

    def write(self, vals):
        if DEPOSIT_FIELDS.intersection(vals) and self.filtered(lambda move: move.state == "posted"):
            raise ValidationError(_("Reset the cheque deposit entry to draft before changing its cheque or receipt evidence."))
        posting = self.filtered(lambda move: move.state != "posted") if vals.get("state") == "posted" else self.browse()
        resetting = self.filtered(lambda move: move.state == "posted" and move.pcd_hold_id) if vals.get("state") in ("draft", "cancel") else self.browse()
        if posting:
            _logger.debug("[PCD][POST_DEPOSIT][START] move_ids=%s", posting.ids)
        try:
            with self.env.cr.savepoint() if posting or resetting else nullcontext():
                result = super().write(vals)
                if posting:
                    # Validate after all values/lines in this write have been applied.
                    # Every posting path, including _post(), imports and direct RPC, writes state.
                    posting._pcd_check_posting()
                    posting._pcd_link_posted_cheques()
                if resetting:
                    holds = resetting.pcd_hold_id.sudo()
                    holds._upg_detach_transfer(_("Cheque deposit entry was reset or cancelled through accounting."))
                    holds.filtered(lambda hold: hold.state == "accounting_transfer_seen").write({"state": "pending"})
        except Exception:
            if posting:
                _logger.debug("[PCD][POST_DEPOSIT][ERROR] move_ids=%s", posting.ids)
            raise
        if posting:
            _logger.debug("[PCD][POST_DEPOSIT][END] move_ids=%s", posting.ids)
        return result

    def _pcd_link_posted_cheques(self):
        for move in self.filtered("pcd_hold_id"):
            hold = move.pcd_hold_id
            if hold.linked_transfer_move_id != move:
                hold._upg_link_transfer(move)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _pcd_check_posted_lines(self):
        if self.move_id.filtered(lambda move: move.state == "posted" and move.pcd_hold_id):
            raise ValidationError(_("Reset the cheque deposit entry to draft before changing its accounting lines."))

    @api.model_create_multi
    def create(self, vals_list):
        moves = self.env["account.move"].browse([vals["move_id"] for vals in vals_list if vals.get("move_id")])
        if moves.filtered(lambda move: move.state == "posted" and move.pcd_hold_id):
            raise ValidationError(_("Reset the cheque deposit entry to draft before adding accounting lines."))
        with self.env.cr.savepoint() if moves.filtered(lambda move: move.state == "posted") else nullcontext():
            lines = super().create(vals_list)
            lines.move_id.filtered(lambda move: move.state == "posted")._pcd_check_posting()
        return lines

    def write(self, vals):
        changes_accounting = {"account_id", "debit", "credit", "balance", "amount_currency", "currency_id", "move_id", "company_id"}.intersection(vals)
        if changes_accounting:
            self._pcd_check_posted_lines()
            if vals.get("move_id"):
                destination = self.env["account.move"].browse(vals["move_id"])
                if destination.state == "posted" and destination.pcd_hold_id:
                    raise ValidationError(_("Reset the cheque deposit entry to draft before moving accounting lines into it."))
        posted = self.move_id.filtered(lambda move: move.state == "posted") if changes_accounting else self.env["account.move"]
        with self.env.cr.savepoint() if posted else nullcontext():
            result = super().write(vals)
            if changes_accounting:
                (posted | self.move_id.filtered(lambda move: move.state == "posted"))._pcd_check_posting()
        return result

    def unlink(self):
        self._pcd_check_posted_lines()
        return super().unlink()
