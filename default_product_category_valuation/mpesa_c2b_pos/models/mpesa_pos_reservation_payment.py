"""POS payment fields used to correlate browser reservations with server rows."""
from odoo import fields, models


class PosPaymentReservation(models.Model):
    _inherit = "pos.payment"

    mpesa_reservation_id = fields.Many2one(
        "mpesa.pos.reservation", readonly=True, index=True, ondelete="set null"
    )
    mpesa_reservation_token = fields.Char(readonly=True, index=True, copy=False)
    mpesa_reservation_state = fields.Char(readonly=True, copy=False)
