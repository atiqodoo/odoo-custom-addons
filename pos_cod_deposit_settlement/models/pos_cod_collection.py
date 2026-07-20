# -*- coding: utf-8 -*-
import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger("pos_cod_deposit_settlement.audit")


class PosCodCollection(models.Model):
    _inherit = "pos.cod.collection"

    kind = fields.Selection(
        selection_add=[("deposit", "Customer Deposit")],
        ondelete={"deposit": "cascade"},
    )
    cod_deposit_application_id = fields.Many2one(
        "pos.cod.deposit.application",
        string="Deposit Application",
        readonly=True,
        copy=False,
        index=True,
        ondelete="restrict",
    )

    _sql_constraints = [
        (
            "cod_deposit_application_unique",
            "unique(cod_deposit_application_id)",
            "A COD deposit application can have only one COD transaction log.",
        ),
    ]

    def write(self, vals):
        if self.filtered(lambda record: record.kind == "deposit"):
            raise UserError(_("Finalized COD deposit transaction logs are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda record: record.kind == "deposit"):
            raise UserError(_("Finalized COD deposit transaction logs cannot be deleted."))
        return super().unlink()
