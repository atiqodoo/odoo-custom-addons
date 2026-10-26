from odoo import fields, models


class LinkChequeTransferWizard(models.TransientModel):
    _name = "pos.uncleared.payment.link.transfer.wizard"
    _description = "Link Existing Cheque Transfer"

    hold_id = fields.Many2one("pos.uncleared.payment.hold", required=True, readonly=True)
    company_id = fields.Many2one(related="hold_id.company_id")
    move_id = fields.Many2one(
        "account.move", string="Posted Cheque Transfer", required=True,
        domain="[('state', '=', 'posted'), ('company_id', '=', company_id)]",
    )

    def action_link(self):
        self.ensure_one()
        self.hold_id._upg_link_transfer(self.move_id)
        return {"type": "ir.actions.act_window_close"}
