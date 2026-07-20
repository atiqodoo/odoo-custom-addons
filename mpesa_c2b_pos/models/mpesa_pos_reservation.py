"""Durable, auditable leases between a POS browser order and an M-Pesa SMS."""
import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

_logger = logging.getLogger("mpesa_c2b_pos.reservation")


class MpesaPosReservationEvent(models.Model):
    _name = "mpesa.pos.reservation.event"
    _description = "M-Pesa POS Reservation Audit Event"
    _order = "create_date desc, id desc"

    reservation_id = fields.Many2one(
        "mpesa.pos.reservation", required=True, index=True, ondelete="cascade"
    )
    transaction_id = fields.Many2one(
        "mpesa.transaction", required=True, index=True, ondelete="cascade"
    )
    order_uuid = fields.Char(required=True, index=True)
    event = fields.Char(required=True, index=True)
    source = fields.Char(required=True, default="server", index=True)
    detail = fields.Json(default=dict)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user)


class MpesaPosReservation(models.Model):
    _name = "mpesa.pos.reservation"
    _description = "M-Pesa POS Order Reservation"
    _order = "create_date desc, id desc"
    _rec_name = "order_uuid"

    token = fields.Char(required=True, index=True, readonly=True, copy=False)
    order_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    transaction_id = fields.Many2one(
        "mpesa.transaction", required=True, index=True, ondelete="cascade", readonly=True
    )
    mpesa_ref = fields.Char(related="transaction_id.mpesa_ref", store=True, index=True)
    amount = fields.Monetary(required=True, currency_field="currency_id", readonly=True)
    currency_id = fields.Many2one(related="transaction_id.currency_id", store=True)
    session_id = fields.Many2one("pos.session", index=True, ondelete="set null", readonly=True)
    cashier_id = fields.Many2one("res.users", index=True, ondelete="set null", readonly=True)
    linked_order_id = fields.Many2one("pos.order", index=True, ondelete="set null", readonly=True)
    state = fields.Selection(
        [
            ("reserved", "Reserved - Awaiting POS Sync"),
            ("linked", "Linked to POS Order"),
            ("released", "Released by POS"),
            ("expired", "Expired Without POS Order"),
            ("conflict", "Needs Attention"),
        ],
        required=True,
        default="reserved",
        index=True,
        readonly=True,
    )
    expires_at = fields.Datetime(required=True, index=True, readonly=True)
    last_heartbeat_at = fields.Datetime(index=True, readonly=True)
    linked_at = fields.Datetime(readonly=True)
    released_at = fields.Datetime(readonly=True)
    release_reason = fields.Char(readonly=True)
    event_ids = fields.One2many("mpesa.pos.reservation.event", "reservation_id")

    _sql_constraints = [
        ("token_unique", "UNIQUE(token)", "M-Pesa reservation token must be unique."),
        (
            "transaction_order_unique",
            "UNIQUE(transaction_id, order_uuid)",
            "This M-Pesa transaction is already reserved for this POS order.",
        ),
    ]

    @api.model
    def _lease_minutes(self):
        value = self.env["ir.config_parameter"].sudo().get_param(
            "mpesa_c2b_pos.reservation_lease_minutes", "10"
        )
        try:
            return max(2, min(int(value), 120))
        except (TypeError, ValueError):
            return 10

    def _audit(self, event, source="server", **detail):
        self.ensure_one()
        clean_detail = {key: value for key, value in detail.items() if value is not None}
        self.env["mpesa.pos.reservation.event"].sudo().create({
            "reservation_id": self.id,
            "transaction_id": self.transaction_id.id,
            "order_uuid": self.order_uuid,
            "event": event,
            "source": source,
            "detail": clean_detail,
        })
        _logger.info(
            "MPESA_RESERVATION event=%s reservation_id=%s order_uuid=%s ref=%s "
            "state=%s amount=%.2f session=%s source=%s detail=%s",
            event,
            self.id,
            self.order_uuid,
            self.mpesa_ref,
            self.state,
            self.amount,
            self.session_id.id,
            source,
            clean_detail,
        )

    @api.model
    def reserve_from_pos(
        self,
        transaction_id,
        lock_token,
        order_uuid,
        applied_amount,
        expiry_authorization=None,
        session_authorizations=None,
    ):
        if not order_uuid:
            raise ValidationError("POS order UUID is required for an M-Pesa reservation.")

        self.env.cr.execute(
            "SELECT id FROM mpesa_transaction WHERE id = %s FOR UPDATE",
            (int(transaction_id),),
        )
        txn = self.env["mpesa.transaction"].sudo().browse(int(transaction_id)).exists()
        if not txn:
            raise UserError("M-Pesa transaction was not found.")

        existing = self.sudo().search([
            ("transaction_id", "=", txn.id),
            ("order_uuid", "=", order_uuid),
        ], limit=1)
        if existing and existing.state == "reserved":
            existing._audit("reserve_idempotent", source="pos")
            return existing._pos_payload()

        if txn.state != "pending_pos" or txn.lock_token != lock_token:
            raise UserError(
                "M-Pesa transaction is no longer locked by this POS order. Search it again."
            )
        if txn.pos_lock_expires and fields.Datetime.now() > txn.pos_lock_expires:
            raise UserError("M-Pesa lock expired. Search the SMS again.")

        expiry_validator = getattr(
            self.env["hr.employee"].sudo(),
            "sbl_validate_expired_mpesa_sms_confirmation",
            None,
        )
        if expiry_validator:
            expiry_result = expiry_validator(
                txn.id,
                txn.pos_session_id.id,
                expiry_authorization or {},
                session_authorizations or {},
            )
            if not expiry_result.get("approved"):
                raise UserError(
                    expiry_result.get("message")
                    or "Expired M-Pesa SMS requires authorization."
                )

        available = txn.amount_remaining or 0.0
        amount = min(float(applied_amount or available), available)
        if float_compare(amount, 0.0, precision_digits=2) <= 0:
            raise UserError("No M-Pesa balance remains to reserve.")

        now = fields.Datetime.now()
        reservation_values = {
            "token": secrets.token_urlsafe(32),
            "amount": amount,
            "session_id": txn.pos_session_id.id,
            "cashier_id": self.env.user.id,
            "state": "reserved",
            "expires_at": now + timedelta(minutes=self._lease_minutes()),
            "last_heartbeat_at": now,
            "linked_order_id": False,
            "linked_at": False,
            "released_at": False,
            "release_reason": False,
        }
        if existing:
            existing.sudo().write(reservation_values)
            reservation = existing
        else:
            reservation = self.sudo().create({
                **reservation_values,
                "order_uuid": order_uuid,
                "transaction_id": txn.id,
            })
        txn.write({
            "pos_reserved_amount": (txn.pos_reserved_amount or 0.0) + amount,
            "state": "pending_pos",
            "pos_lock_expires": False,
            "lock_token": False,
        })
        reservation._audit(
            "reserved",
            source="pos",
            transaction_id=txn.id,
            expires_at=fields.Datetime.to_string(reservation.expires_at),
        )
        return reservation._pos_payload()

    def _pos_payload(self):
        self.ensure_one()
        return {
            "success": True,
            "reservation_id": self.id,
            "reservation_token": self.token,
            "reservation_state": self.state,
            "transaction_id": self.transaction_id.id,
            "mpesa_ref": self.mpesa_ref,
            "applied_amount": self.amount,
            "order_uuid": self.order_uuid,
            "expires_at": fields.Datetime.to_string(self.expires_at),
            "linked_order_id": self.linked_order_id.id or False,
        }

    @api.model
    def heartbeat(self, token, order_uuid):
        reservation = self.sudo().search([
            ("token", "=", token),
            ("order_uuid", "=", order_uuid),
        ], limit=1)
        if not reservation or reservation.state != "reserved":
            return {"success": False, "state": reservation.state if reservation else "missing"}
        now = fields.Datetime.now()
        reservation.write({
            "last_heartbeat_at": now,
            "expires_at": now + timedelta(minutes=self._lease_minutes()),
        })
        reservation._audit("heartbeat", source="pos")
        return reservation._pos_payload()

    @api.model
    def status_for_orders(self, order_uuids):
        reservations = self.sudo().search([("order_uuid", "in", list(set(order_uuids or [])))])
        result = {}
        for reservation in reservations:
            result.setdefault(reservation.order_uuid, []).append(reservation._pos_payload())
        return result

    @api.model
    def classify_legacy_orders(self, orders):
        """Classify pre-upgrade IndexedDB M-Pesa lines without mutating live data."""
        result = {}
        for item in (orders or [])[:100]:
            order_uuid = str(item.get("order_uuid") or "").strip()
            if not order_uuid:
                continue
            server_order = self.env["pos.order"].sudo().search([
                ("uuid", "=", order_uuid),
            ], limit=1)
            classifications = []
            for payment in (item.get("payments") or [])[:20]:
                mpesa_ref = str(payment.get("mpesa_ref") or "").strip()
                amount = float(payment.get("amount") or 0.0)
                txn = self.env["mpesa.transaction"].sudo().search([
                    ("mpesa_ref", "=", mpesa_ref),
                ], limit=1)
                usage = self.env["mpesa.transaction.usage"].sudo().search([
                    ("transaction_id", "=", txn.id if txn else 0),
                    ("pos_order_id.uuid", "=", order_uuid),
                ], limit=1)
                if usage:
                    disposition = "linked"
                    reason = "usage_already_exists"
                elif server_order:
                    disposition = "conflict"
                    reason = "server_order_exists_without_matching_usage"
                elif not txn:
                    disposition = "revalidate"
                    reason = "mpesa_transaction_missing"
                elif float_compare(
                    amount,
                    txn.pos_reserved_amount or 0.0,
                    precision_rounding=txn.currency_id.rounding or 0.01,
                ) <= 0:
                    disposition = "reserved"
                    reason = "legacy_server_reservation_available"
                else:
                    disposition = "revalidate"
                    reason = "no_reservation_for_legacy_payment"
                payload = {
                    "mpesa_ref": mpesa_ref,
                    "amount": amount,
                    "disposition": disposition,
                    "reason": reason,
                    "transaction_id": txn.id if txn else False,
                    "transaction_state": txn.state if txn else "missing",
                    "reserved_amount": txn.pos_reserved_amount if txn else 0.0,
                    "remaining_amount": txn.amount_remaining if txn else 0.0,
                    "server_order_id": server_order.id or False,
                }
                classifications.append(payload)
                _logger.info(
                    "MPESA_LEGACY_RECOVERY order_uuid=%s ref=%s amount=%.2f "
                    "disposition=%s reason=%s txn_state=%s reserved=%.2f server_order=%s",
                    order_uuid,
                    mpesa_ref,
                    amount,
                    disposition,
                    reason,
                    payload["transaction_state"],
                    payload["reserved_amount"],
                    payload["server_order_id"],
                )
            result[order_uuid] = classifications
        return result

    def release(self, reason="pos_abandoned", source="pos"):
        for reservation in self.filtered(lambda record: record.state == "reserved"):
            self.env.cr.execute(
                "SELECT id FROM mpesa_transaction WHERE id = %s FOR UPDATE",
                (reservation.transaction_id.id,),
            )
            txn = reservation.transaction_id.sudo()
            reserved_after = max((txn.pos_reserved_amount or 0.0) - reservation.amount, 0.0)
            other_active = self.sudo().search_count([
                ("transaction_id", "=", txn.id),
                ("state", "=", "reserved"),
                ("id", "!=", reservation.id),
            ])
            values = {"pos_reserved_amount": reserved_after}
            if not other_active:
                values.update({
                    "state": txn._available_state(),
                    "pos_session_id": False,
                    "pos_lock_expires": False,
                    "lock_token": False,
                })
            txn.write(values)
            reservation.write({
                "state": "released" if source == "pos" else "expired",
                "released_at": fields.Datetime.now(),
                "release_reason": reason,
            })
            reservation._audit("released", source=source, reason=reason)
        return True

    @api.model
    def _cron_release_expired_reservations(self):
        expired = self.sudo().search([
            ("state", "=", "reserved"),
            ("expires_at", "<", fields.Datetime.now()),
        ])
        released = linked = conflicts = 0
        for reservation in expired:
            order = self.env["pos.order"].sudo().search([
                ("uuid", "=", reservation.order_uuid),
            ], limit=1)
            usage = self.env["mpesa.transaction.usage"].sudo().search([
                ("transaction_id", "=", reservation.transaction_id.id),
                ("pos_order_id", "=", order.id if order else 0),
            ], limit=1)
            if order and usage:
                reservation.write({
                    "state": "linked",
                    "linked_order_id": order.id,
                    "linked_at": fields.Datetime.now(),
                })
                reservation._audit("linked_during_expiry_scan", source="cron")
                linked += 1
            elif order:
                reservation.write({"state": "conflict", "linked_order_id": order.id})
                reservation._audit("order_without_usage_conflict", source="cron")
                conflicts += 1
            else:
                reservation.release("lease_expired_without_order", source="cron")
                released += 1
        _logger.info(
            "MPESA_RESERVATION_CRON scanned=%d released=%d linked=%d conflicts=%d",
            len(expired), released, linked, conflicts,
        )
        return {"scanned": len(expired), "released": released, "linked": linked, "conflicts": conflicts}
