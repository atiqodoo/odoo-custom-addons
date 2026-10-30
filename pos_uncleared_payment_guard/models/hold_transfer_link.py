import logging

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger("pos_uncleared_payment_guard.transfer_link")


class HoldTransferLink(models.Model):
    _inherit = "pos.uncleared.payment.hold"

    linked_transfer_move_id = fields.Many2one(
        "account.move", string="Selected Cheque Transfer", readonly=True,
        copy=False, index=True, check_company=True, tracking=True, ondelete="set null",
    )
    confirmed_bank_statement_line_ids = fields.Many2many(
        "account.bank.statement.line", string="Confirmed Bank Transactions", readonly=True, copy=False,
    )
    transfer_link_manual_release = fields.Boolean(readonly=True, copy=False)
    previous_transfer_reference = fields.Char(readonly=True, copy=False, tracking=True)

    _sql_constraints = [(
        "linked_cheque_transfer_unique", "unique(linked_transfer_move_id)",
        "This transfer is already linked to another cheque. Use a separate transfer for each cheque.",
    )]

    def action_open_transfer_link_wizard(self):
        self.ensure_one()
        self._upg_check_transfer_link_access()
        return {
            "type": "ir.actions.act_window", "name": _("Link Cheque Transfer"),
            "res_model": "pos.uncleared.payment.link.transfer.wizard",
            "view_mode": "form", "target": "new",
            "context": {"default_hold_id": self.id},
        }

    def _upg_check_transfer_link_access(self):
        if not self.env.user.has_group("pos_uncleared_payment_guard.group_pos_uncleared_payment_manager"):
            raise UserError(_("Only Uncleared POS Payment Managers can link transfers."))
        self.check_access("write")
        if any(hold.company_id not in self.env.companies for hold in self):
            raise UserError(_("Select the cheque's company before linking its transfer."))

    def write(self, vals):
        if "linked_transfer_move_id" in vals:
            self._upg_check_transfer_link_access()
            if self.filtered(lambda hold: hold.state in ("cancelled", "accounting_cleared")):
                raise UserError(_("Transfers can only be linked to pending, transfer-seen or manually cleared holds."))
            if vals["linked_transfer_move_id"] and (len(self) != 1 or self.sudo().search_count([
                ("linked_transfer_move_id", "=", vals["linked_transfer_move_id"]),
                ("id", "not in", self.ids),
            ])):
                raise ValidationError(_("This transfer is already linked to another cheque."))
        return super().write(vals)

    @api.constrains("linked_transfer_move_id", "amount", "company_id", "currency_id", "payment_method_id", "deposit_bank_journal_id")
    def _upg_validate_transfer_link(self):
        for hold in self.filtered("linked_transfer_move_id"):
            hold._upg_transfer_lines()

    def _upg_transfer_lines(self):
        """Validate the deliberately narrow contract: one whole cheque per two-line transfer."""
        self.ensure_one()
        return self._upg_validate_transfer_move(self.linked_transfer_move_id)

    def _upg_validate_transfer_move(self, move, require_posted=True):
        """Shared transfer contract; extensions may validate a draft before posting."""
        self.ensure_one()
        if not move or move.company_id != self.company_id or (
            move.state != "posted" if require_posted else move.state not in ("draft", "posted")
        ):
            raise ValidationError(_("Select a posted transfer from the cheque's company."))
        if move.reversed_entry_id or move.reversal_move_ids.filtered(lambda reversal: reversal.state == "posted"):
            raise ValidationError(_("The selected transfer has been reversed. Review its accounting before confirming clearance."))
        if self.currency_id != self.company_id.currency_id or move.currency_id != self.currency_id:
            raise ValidationError(_("Link Transfer currently supports company-currency cheques only."))
        if not self.deposit_bank_journal_id or self.deposit_bank_journal_id.company_id != self.company_id:
            raise ValidationError(_("A destination bank in the cheque's company is required."))
        lines = move.line_ids.filtered(lambda line: line.display_type not in ("line_section", "line_note"))
        accounts = self.mapped_account_id | self.payment_method_id.outstanding_account_id
        sources = lines.filtered(lambda line: line.account_id in accounts and line.credit > 0)
        targets = lines - sources
        if len(lines) != 2 or len(sources) != 1 or len(targets) != 1:
            raise ValidationError(_("Select a two-line transfer crediting the cheque collection account. Combined transfers require separate entries per cheque."))
        if sources.account_id == targets.account_id:
            raise ValidationError(_("The transfer must move money between different accounts."))
        currency = self.currency_id
        if self.amount <= 0 or currency.compare_amounts(sources.credit, self.amount) or currency.compare_amounts(targets.debit, self.amount):
            raise ValidationError(_("The transfer must move the full cheque amount from collection to bank outstanding receipts."))
        if any(line.currency_id != currency for line in lines):
            raise ValidationError(_("Transfer lines must use the cheque's company currency."))
        bank = self.deposit_bank_journal_id
        outstanding = bank.inbound_payment_method_line_ids.payment_account_id
        direct_statement = targets.statement_line_id
        direct_bank = bool(
            targets.account_id == self.deposit_bank_account_id
            and direct_statement and direct_statement.journal_id == bank
        )
        eligible = outstanding | self.company_id.transfer_account_id
        if not direct_bank and (targets.account_id not in eligible or not targets.account_id.reconcile):
            raise ValidationError(_("The debit must use the selected bank's configured, reconcilable Outstanding Receipts account."))
        return sources, targets

    def _upg_detach_transfer(self, reason, reference=False):
        """Accounting hooks may detach their own deleted entry without requiring a POS role."""
        for hold in self:
            transfer = hold.linked_transfer_move_id
            vals = {
                "previous_transfer_reference": reference or transfer.exists().name or hold.previous_transfer_reference,
                "linked_transfer_move_id": False,
                "accounting_transfer_move_id": False,
                "bank_statement_line_id": False,
                "confirmed_bank_statement_line_ids": [Command.clear()],
                "accounting_detection_note": reason,
            }
            if hold.state == "accounting_cleared":
                vals["state"] = "manual_cleared" if hold.transfer_link_manual_release else "pending"
            super(HoldTransferLink, hold).write(vals)
            _logger.debug("[UPG][DETACH_TRANSFER][END] hold_id=%s move_id=%s", hold.id, transfer.id)

    def _upg_link_transfer(self, move):
        self.ensure_one()
        self._upg_check_transfer_link_access()
        move.check_access("read")
        _logger.debug("[UPG][LINK_TRANSFER][START] hold_id=%s move_id=%s", self.id, move.id)
        try:
            self.write({
                "linked_transfer_move_id": move.id,
                "transfer_link_manual_release": self.state == "manual_cleared" or self.transfer_link_manual_release,
            })
            self.env["pos.uncleared.payment.accounting.detector"].upg_check_hold(self)
        except Exception:
            _logger.exception("[UPG][LINK_TRANSFER][ERROR] hold_id=%s move_id=%s", self.id, move.id)
            raise
        _logger.debug("[UPG][LINK_TRANSFER][END] hold_id=%s state=%s", self.id, self.state)

    def _upg_mark_manual_cleared(self, reason, reference=False):
        result = super()._upg_mark_manual_cleared(reason, reference)
        self.write({"transfer_link_manual_release": True})
        return result
