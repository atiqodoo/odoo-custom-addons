import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ChequeDepositValidation(models.AbstractModel):
    _name = "pos.cheque.deposit.validation"
    _description = "Cheque deposit evidence validation"

    @api.model
    def _validate(self, move, hold=None, require_posted=False):
        move.ensure_one()
        hold = hold or move.pcd_hold_id
        _logger.debug("[PCD][VALIDATE_DEPOSIT][START] move_id=%s hold_id=%s company_id=%s", move.id, hold.id, move.company_id.id)
        try:
            if not hold:
                raise ValidationError(_("Select the cheque being deposited before posting this transfer."))
            hold.check_access("read")
            if hold.company_id != move.company_id or move.company_id not in self.env.companies:
                raise ValidationError(_("Select a cheque in the entry's allowed company."))
            if hold.state == "cancelled":
                raise ValidationError(_("A cancelled cheque cannot be deposited."))
            if hold.linked_transfer_move_id and hold.linked_transfer_move_id != move:
                raise ValidationError(_("This cheque already has a selected transfer."))
            if move.pcd_hold_id != hold:
                raise ValidationError(_("Select this cheque on the journal entry before linking its transfer."))
            config = hold.pos_config_id.sudo()
            if not self.env["pos.cheque.deposit.policy"]._controlled_hold(hold):
                raise ValidationError(_("Select a cheque from a POS configured for Cheque Deposit Control."))
            if hold.deposit_bank_journal_id not in config.upg_deposit_bank_journal_ids:
                raise ValidationError(_("The cheque's destination bank is not allowed in its POS configuration."))
            hold._upg_validate_transfer_move(move, require_posted=require_posted)
            today = fields.Date.context_today(hold)
            if not hold.cheque_date:
                raise ValidationError(_("The cheque date is required before deposit."))
            if not move.pcd_deposit_date or move.pcd_deposit_date < hold.cheque_date or move.pcd_deposit_date > today:
                raise ValidationError(_("Enter an actual deposit date on or after the cheque date and no later than today."))
            receipts = move.pcd_receipt_ids
            if not receipts:
                raise ValidationError(_("Attach the bank deposit receipt before posting this cheque deposit transfer."))
            receipts.check("read")
            if any(receipt.type != "binary" or not receipt.file_size or not receipt.raw
                   or receipt.res_model != "account.move" or receipt.res_id != move.id
                   or receipt.company_id != move.company_id or receipt.public for receipt in receipts):
                raise ValidationError(_("Upload a nonempty, private bank deposit receipt attached to this journal entry in the same company."))
        except Exception:
            _logger.debug("[PCD][VALIDATE_DEPOSIT][ERROR] move_id=%s hold_id=%s", move.id, hold.id)
            raise
        _logger.debug("[PCD][VALIDATE_DEPOSIT][END] move_id=%s hold_id=%s", move.id, hold.id)
        return True
