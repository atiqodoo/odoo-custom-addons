# -*- coding: utf-8 -*-
import logging

from odoo import models, _
from odoo.exceptions import UserError

_logger = logging.getLogger("pos_cod_deposit_settlement.pos_session")


class CodDepositFinalizationError(UserError):
    pass


class PosSession(models.Model):
    _inherit = "pos.session"

    def _validate_session(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        """Finalize reservations after standard accounting, before RPC commit.

        Any failure propagates and rolls back the complete session-close RPC,
        including the standard POS move, reconciliation, COD bridge and state.
        """
        self.ensure_one()
        reservations = self.env["pos.cod.session.deposit.reservation"].sudo().search([
            ("source_session_id", "=", self.id),
            ("state", "in", ("reserved", "error")),
        ], order="id asc")
        _logger.warning(
            "[COD-DEPOSIT][SESSION-CLOSE][START] session=%s state=%s reservations=%s",
            self.name, self.state, [(r.name, r.order_id.name, r.amount, r.state) for r in reservations],
        )
        result = super()._validate_session(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs,
        )
        if not reservations:
            _logger.warning("[COD-DEPOSIT][SESSION-CLOSE][NO-RESERVATIONS] session=%s", self.name)
            return result
        try:
            for reservation in reservations:
                reservation._cdds_finalize()
        except Exception as exc:
            _logger.exception(
                "[COD-DEPOSIT][SESSION-CLOSE][ROLLBACK] session=%s failed_reservation=%s order=%s error=%s; entire close must roll back",
                self.name, reservation.name, reservation.order_id.name, str(exc),
            )
            raise CodDepositFinalizationError(_(
                "COD Deposit Finalization Failed\n"
                "Session: %(session)s\nReservation: %(reservation)s\nCOD Order: %(order)s\n"
                "Reason: %(reason)s\nNo session-closing accounting changes were committed.",
                session=self.name,
                reservation=reservation.name,
                order=reservation.order_id.name,
                reason=str(exc),
            )) from exc
        _logger.warning(
            "[COD-DEPOSIT][SESSION-CLOSE][SUCCESS] session=%s finalized=%s",
            self.name, reservations.mapped("name"),
        )
        return result

    def close_session_from_ui(self, bank_payment_method_diff_pairs=None):
        """Return a cashier-friendly alert while rolling back the close savepoint."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                return super().close_session_from_ui(bank_payment_method_diff_pairs)
        except CodDepositFinalizationError as exc:
            message = exc.args[0] if exc.args else _("COD deposit finalization failed.")
            failed_reservations = self.env["pos.cod.session.deposit.reservation"].sudo().search([
                ("source_session_id", "=", self.id),
                ("state", "in", ("reserved", "error")),
            ])
            failed_reservations.with_context(cdds_allow_reservation_write=True).write({
                "state": "error",
                "error_message": message,
            })
            _logger.error(
                "[COD-DEPOSIT][SESSION-CLOSE][ALERT] session=%s reservations_marked_error=%s returning structured POS error=%s",
                self.name, failed_reservations.mapped("name"), message,
            )
            return {
                "successful": False,
                "title": _("COD Deposit Finalization Failed"),
                "message": message,
                "open_order_ids": [],
                "redirect": False,
            }
