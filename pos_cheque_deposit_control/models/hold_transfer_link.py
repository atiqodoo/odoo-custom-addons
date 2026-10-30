from odoo import api, models


class HoldTransferLink(models.Model):
    _inherit = "pos.uncleared.payment.hold"

    @api.constrains("linked_transfer_move_id", "amount", "company_id", "currency_id", "payment_method_id", "deposit_bank_journal_id")
    def _upg_validate_transfer_link(self):
        super()._upg_validate_transfer_link()
        policy = self.env["pos.cheque.deposit.policy"]
        for hold in self.filtered("linked_transfer_move_id"):
            if policy._controlled_hold(hold):
                self.env["pos.cheque.deposit.validation"]._validate(
                    hold.linked_transfer_move_id, hold=hold, require_posted=True,
                )

    def _upg_link_transfer(self, move):
        self.ensure_one()
        self._upg_check_transfer_link_access()
        move.check_access("read")
        if self.env["pos.cheque.deposit.policy"]._controlled_hold(self):
            self.env["pos.cheque.deposit.validation"]._validate(move, hold=self, require_posted=True)
        return super()._upg_link_transfer(move)
