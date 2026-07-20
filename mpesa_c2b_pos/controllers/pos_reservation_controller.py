"""Authenticated JSON API for durable POS reservation leases."""
import logging

from odoo.http import Controller, request, route

_logger = logging.getLogger("mpesa_c2b_pos.reservation_api")


class MpesaPosReservationController(Controller):

    @route("/pos/mpesa/reservation/confirm", type="json", auth="user", methods=["POST"])
    def confirm_reservation(
        self,
        transaction_id,
        lock_token,
        order_uuid,
        applied_amount=0.0,
        expiry_authorization=None,
        **kwargs,
    ):
        _logger.info(
            "MPESA_RESERVATION_API action=confirm transaction_id=%s order_uuid=%s "
            "amount=%s session_uid=%s",
            transaction_id, order_uuid, applied_amount, request.env.uid,
        )
        return request.env["mpesa.pos.reservation"].reserve_from_pos(
            transaction_id,
            lock_token,
            order_uuid,
            applied_amount,
            expiry_authorization or {},
            request.session.get("sbl_mpesa_expiry_authorizations") or {},
        )

    @route("/pos/mpesa/reservation/heartbeat", type="json", auth="user", methods=["POST"])
    def heartbeat(self, token, order_uuid, **kwargs):
        return request.env["mpesa.pos.reservation"].heartbeat(token, order_uuid)

    @route("/pos/mpesa/reservation/status", type="json", auth="user", methods=["POST"])
    def status(self, order_uuids=None, **kwargs):
        return request.env["mpesa.pos.reservation"].status_for_orders(order_uuids or [])

    @route("/pos/mpesa/reservation/legacy-status", type="json", auth="user", methods=["POST"])
    def legacy_status(self, orders=None, **kwargs):
        return request.env["mpesa.pos.reservation"].classify_legacy_orders(orders or [])

    @route("/pos/mpesa/reservation/abandon", type="json", auth="user", methods=["POST"])
    def abandon(self, token, order_uuid, reason="pos_abandoned", **kwargs):
        reservation = request.env["mpesa.pos.reservation"].sudo().search([
            ("token", "=", token),
            ("order_uuid", "=", order_uuid),
        ], limit=1)
        if not reservation:
            return {"success": False, "state": "missing"}
        reservation.release(reason=reason, source="pos")
        return {"success": True, "state": reservation.state}

    @route("/pos/mpesa/reservation/client-log", type="json", auth="user", methods=["POST"])
    def client_log(self, event, order_uuid="", detail=None, **kwargs):
        _logger.info(
            "MPESA_RESERVATION_CLIENT event=%s order_uuid=%s uid=%s detail=%s",
            event, order_uuid, request.env.uid, detail or {},
        )
        return {"success": True}
