import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)


class ChequeDepositReminder(models.Model):
    _inherit = "pos.uncleared.payment.hold"

    def _pcd_has_deposit_evidence(self):
        self.ensure_one()
        move = self.linked_transfer_move_id
        if not move or move.state != "posted":
            return False
        try:
            self.env["pos.cheque.deposit.validation"]._validate(move, hold=self, require_posted=True)
        except ValidationError:
            return False
        return True

    @api.model
    def pcd_pos_reminders(self, config_id, offset=0, limit=40):
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("POS access is required to view cheque banking reminders."))
        config = self.env["pos.config"].browse(config_id).exists()
        config.check_access("read")
        if not config or config.company_id not in self.env.companies:
            raise AccessError(_("Select a POS in an allowed company."))
        offset, limit = max(int(offset), 0), min(max(int(limit), 1), 100)
        _logger.debug("[PCD][REMINDERS][START] config_id=%s company_id=%s", config.id, config.company_id.id)
        try:
            # Cashiers receive a deliberately small, company-bound projection, not ledger/receipt access.
            # Include old sessions and manually cleared holds: release is not deposit evidence.
            domain = [
                ("company_id", "=", config.company_id.id), ("pos_config_id", "=", config.id),
                ("state", "!=", "cancelled"), ("amount", ">", 0),
                ("payment_method_id.pcd_is_cheque", "=", True),
                ("cheque_date", "!=", False), ("cheque_date", "<=", fields.Date.context_today(config)),
            ]
            holds = self.sudo().search(domain, order="cheque_date, id") if config.pcd_enabled else self.browse()
            pending = holds.filtered(lambda hold: not hold._pcd_has_deposit_evidence())
            rows = [{
                "id": hold.id, "name": hold.name, "cheque_number": hold.cheque_number or "",
                "cheque_date": fields.Date.to_string(hold.cheque_date),
                "amount": hold.amount, "currency": hold.currency_id.name,
                "bank": hold.deposit_bank_journal_id.display_name,
            } for hold in pending[offset:offset + limit]]
            result = {"count": len(pending), "rows": rows, "offset": offset, "limit": limit,
                      "checked_at": fields.Datetime.to_string(fields.Datetime.now())}
        except Exception:
            _logger.debug("[PCD][REMINDERS][ERROR] config_id=%s", config.id)
            raise
        _logger.debug("[PCD][REMINDERS][END] config_id=%s count=%s", config.id, len(pending))
        return result
