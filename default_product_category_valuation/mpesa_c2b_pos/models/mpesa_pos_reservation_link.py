"""Marks a durable reservation linked after the existing POS linkage succeeds."""
from odoo import fields, models


class PosOrderReservationLink(models.Model):
    _inherit = "pos.order"

    def _link_mpesa_usages_from_payments(self):
        result = super()._link_mpesa_usages_from_payments()
        Reservation = self.env["mpesa.pos.reservation"].sudo()
        for order in self.sudo():
            for payment in order.payment_ids.filtered(lambda line: line.mpesa_ref):
                domain = [
                    ("order_uuid", "=", order.uuid),
                    ("mpesa_ref", "=", payment.mpesa_ref),
                    ("state", "=", "reserved"),
                ]
                if payment.mpesa_reservation_token:
                    domain.append(("token", "=", payment.mpesa_reservation_token))
                reservation = Reservation.search(domain, limit=1)
                if not reservation:
                    continue
                reservation.write({
                    "state": "linked",
                    "linked_order_id": order.id,
                    "linked_at": fields.Datetime.now(),
                })
                payment.write({
                    "mpesa_reservation_id": reservation.id,
                    "mpesa_reservation_state": "linked",
                })
                reservation._audit(
                    "linked",
                    source="sync_from_ui",
                    pos_order_id=order.id,
                    pos_payment_id=payment.id,
                )
        return result
