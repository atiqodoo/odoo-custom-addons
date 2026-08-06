# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger("pos_uncleared_payment_guard.clear_wizard")


class PosUnclearedPaymentClearWizard(models.TransientModel):
    _name = "pos.uncleared.payment.clear.wizard"
    _description = "Clear POS Uncleared Payment Hold"

    hold_id = fields.Many2one("pos.uncleared.payment.hold", required=True, readonly=True)
    amount = fields.Monetary(related="hold_id.amount", readonly=True)
    currency_id = fields.Many2one(related="hold_id.currency_id", readonly=True)
    partner_id = fields.Many2one(related="hold_id.partner_id", readonly=True)
    payment_method_id = fields.Many2one(related="hold_id.payment_method_id", readonly=True)
    reference = fields.Char(string="Clearance Reference")
    reason = fields.Text(required=True)

    def action_clear(self):
        self.ensure_one()
        _logger.warning(
            "[UPG][Wizard] manual clear requested hold=%s user=%s reference=%s",
            self.hold_id.name,
            self.env.user.login,
            self.reference,
        )
        self.hold_id._upg_mark_manual_cleared(self.reason, self.reference)
        return {"type": "ir.actions.act_window_close"}
