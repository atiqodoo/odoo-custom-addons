from odoo import api, models


class ChequeDepositPolicy(models.AbstractModel):
    _name = "pos.cheque.deposit.policy"
    _description = "Configured cheque deposit scope"

    @api.model
    def _configurations(self, company):
        # Accounting users need configuration, not POS administration access.
        # Never use this elevation to read entries or receipts.
        return self.env["pos.config"].sudo().with_context(active_test=False).search([
            ("company_id", "=", company.id), ("pcd_enabled", "=", True),
        ])

    @api.model
    def _requires_receipt(self, move, configurations=None):
        if move.move_type != "entry":
            return False
        if configurations is None:
            configurations = self._configurations(move.company_id)
        for config in configurations:
            methods = config.payment_method_ids.filtered("pcd_is_cheque")
            sources = methods.journal_id.default_account_id | methods.outstanding_account_id
            banks = config.upg_deposit_bank_journal_ids
            targets = banks.inbound_payment_method_line_ids.payment_account_id | banks.default_account_id
            # Internal-transfer clearing is supported by the existing detector.
            targets |= move.company_id.transfer_account_id
            credit_accounts = move.line_ids.filtered(lambda line: line.credit > 0).account_id
            debit_accounts = move.line_ids.filtered(lambda line: line.debit > 0).account_id
            if sources & credit_accounts and targets & debit_accounts:
                return True
        return False

    @api.model
    def _controlled_hold(self, hold):
        config = hold.pos_config_id.sudo()
        return bool(config.pcd_enabled and hold.payment_method_id.sudo().pcd_is_cheque)
