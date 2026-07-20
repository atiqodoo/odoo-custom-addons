# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger("pos_cod_deposit_settlement.pos_order")
_LOG = "[COD-DEPOSIT]"


class PosOrder(models.Model):
    _inherit = "pos.order"

    cod_deposit_application_ids = fields.One2many(
        "pos.cod.deposit.application", "order_id", string="Deposit Applications", readonly=True
    )
    cod_session_deposit_reservation_ids = fields.One2many(
        "pos.cod.session.deposit.reservation", "order_id", string="Same-Session Deposit Reservations", readonly=True
    )
    cod_deposit_applied_amount = fields.Monetary(
        string="Deposit Applied", currency_field="currency_id", compute="_compute_cod_deposit_applied_amount"
    )
    cod_session_deposit_reserved_amount = fields.Monetary(
        string="Same-Session Deposit Reserved",
        currency_field="currency_id",
        compute="_compute_cod_session_deposit_reserved_amount",
    )

    @api.depends("cod_deposit_application_ids.state", "cod_deposit_application_ids.amount")
    def _compute_cod_deposit_applied_amount(self):
        for order in self:
            order.cod_deposit_applied_amount = sum(
                order.cod_deposit_application_ids.filtered(lambda application: application.state == "posted").mapped("amount")
            )

    @api.depends("cod_session_deposit_reservation_ids.state", "cod_session_deposit_reservation_ids.amount")
    def _compute_cod_session_deposit_reserved_amount(self):
        for order in self:
            order.cod_session_deposit_reserved_amount = sum(
                order.cod_session_deposit_reservation_ids.filtered(
                    lambda reservation: reservation.state in ("reserved", "error")
                ).mapped("amount")
            )

    @api.depends(
        "amount_total",
        "cod_collection_ids.amount",
        "cod_collection_ids.kind",
        "cod_deposit_application_ids.state",
        "cod_deposit_application_ids.amount",
        "cod_session_deposit_reservation_ids.state",
        "cod_session_deposit_reservation_ids.amount",
    )
    def _compute_cod_amounts(self):
        super()._compute_cod_amounts()
        for order in self:
            applied = order.cod_deposit_applied_amount
            order.cod_amount_paid = round((order.cod_amount_paid or 0.0) + applied, 2)
            order.cod_amount_open = max(
                round((order.cod_amount_open or 0.0) - applied - order.cod_session_deposit_reserved_amount, 2),
                0.0,
            )

    def _cod_open_amount(self):
        self.ensure_one()
        return max(
            round(
                super()._cod_open_amount()
                - self.cod_deposit_applied_amount
                - self.cod_session_deposit_reserved_amount,
                2,
            ),
            0.0,
        )

    def _cdds_log(self, level, marker, message, *args):
        logger = getattr(_logger, level, _logger.info)
        logger("%s[%s] " + message, _LOG, marker, *args)

    def _cdds_lock_order(self):
        self.ensure_one()
        self.env.cr.execute("SELECT id FROM pos_order WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()
        self._cdds_log("warning", "LOCK", "locked order=%s id=%s", self.name, self.id)

    def _cdds_validate_context(self, session):
        self.ensure_one()
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise UserError(_("Only authorized Point of Sale users can apply customer deposits to COD."))
        config = session.config_id
        if not config.cdds_enable_cod_deposit_settlement:
            raise UserError(_("COD customer-deposit settlement is not enabled on this POS."))
        if not config.cdds_transfer_journal_id:
            raise UserError(_("No COD Deposit Transfer Journal is configured on this POS."))
        if config.cdds_transfer_journal_id.type != "general":
            raise UserError(_("The COD Deposit Transfer Journal must be a General journal."))
        allowed_session_states = ("opened", "closing_control", "closed") if self.env.context.get(
            "cdds_allow_closed_source_session"
        ) else ("opened", "closing_control")
        if session.state not in allowed_session_states:
            raise UserError(_("The selected POS session is not open."))
        if session.company_id != self.company_id:
            raise UserError(_("The POS session and COD order belong to different companies."))
        if not self.is_cod or self.cod_state not in ("pending", "partial"):
            raise UserError(_("This COD order is not open for deposit settlement."))
        if not self.partner_id:
            raise UserError(_("The COD order has no customer."))
        if self.currency_id != self.company_id.currency_id:
            raise UserError(_("Foreign-currency COD deposit settlement is deferred and currently blocked."))

    def _cdds_accounts(self):
        self.ensure_one()
        company = self.company_id
        commercial = self.partner_id.commercial_partner_id
        default_receivable = commercial.with_company(company).property_account_receivable_id
        cod_receivable = self._cod_get_ar_account()
        if not default_receivable or not cod_receivable:
            raise UserError(_("Both the default customer receivable and COD receivable accounts are required."))
        if default_receivable == cod_receivable:
            raise UserError(_("Default customer receivable and COD receivable must be separate accounts."))
        for account in default_receivable | cod_receivable:
            if account.account_type != "asset_receivable" or not account.reconcile:
                raise UserError(_("Account %s must be a reconcilable Receivable account.") % account.display_name)
        return commercial, default_receivable, cod_receivable

    def _cdds_open_default_receivable_lines(self, commercial, account, lock=False):
        domain = [
            ("partner_id", "child_of", commercial.id),
            ("company_id", "=", self.company_id.id),
            ("account_id", "=", account.id),
            ("move_id.state", "=", "posted"),
            ("reconciled", "=", False),
            ("amount_residual", "!=", 0.0),
        ]
        lines = self.env["account.move.line"].sudo().search(domain, order="date asc, id asc")
        if lock and lines:
            self.env.cr.execute(
                "SELECT id FROM account_move_line WHERE id IN %s ORDER BY id FOR UPDATE",
                [tuple(lines.ids)],
            )
            lines.invalidate_recordset(["amount_residual", "reconciled"])
            lines = self.env["account.move.line"].sudo().search(domain, order="date asc, id asc")
            self._cdds_log("warning", "LOCK", "locked default AR lines=%s", lines.ids)
        return lines

    def _cdds_classify_default_debits(self, debit_lines):
        """Separate deposit-funded POS invoice debits from unrelated AR debt.

        A normal invoiced POS sale paid through Customer Account creates a posted
        invoice debit on the default receivable account.  That debit is deposit
        consumption, not new credit exposure, when a cleared credit still leaves
        the partner with a net deposit.  It must join the deposit credit and the
        new bridge debit in the same reconciliation group.
        """
        self.ensure_one()
        if not debit_lines:
            return debit_lines, debit_lines, []

        pos_orders = self.env["pos.order"].sudo().search([
            ("account_move", "in", debit_lines.move_id.ids),
            ("is_cod", "=", False),
            ("partner_id", "child_of", self.partner_id.commercial_partner_id.id),
            ("company_id", "=", self.company_id.id),
            ("state", "=", "invoiced"),
        ])
        eligible_orders = pos_orders.filtered(lambda order: any(
            payment.amount > 0
            and (
                payment.payment_method_id.type == "pay_later"
                or getattr(payment.payment_method_id, "pcl_is_credit_method", False)
            )
            for payment in order.payment_ids
        ))
        order_by_move = {order.account_move.id: order for order in eligible_orders if order.account_move}
        eligible = debit_lines.filtered(lambda line: line.move_id.id in order_by_move)
        blocked = debit_lines - eligible
        details = [
            {
                "line_id": line.id,
                "move_id": line.move_id.id,
                "move": line.move_id.name,
                "invoice_ref": line.move_id.ref or "",
                "pos_order_id": order_by_move[line.move_id.id].id,
                "pos_order": order_by_move[line.move_id.id].name,
                "residual": float(line.amount_residual),
            }
            for line in eligible
        ]
        self._cdds_log(
            "warning", "DEBIT-CLASSIFY",
            "order=%s eligible_pos_invoice_debits=%s blocked_default_debits=%s details=%s",
            self.name, eligible.ids, blocked.ids, details,
        )
        return eligible, blocked, details

    def _cdds_credit_snapshot(self, lock=False):
        self.ensure_one()
        commercial, default_receivable, cod_receivable = self._cdds_accounts()
        lines = self._cdds_open_default_receivable_lines(commercial, default_receivable, lock=lock)
        rounding = self.currency_id.rounding
        debit_lines = lines.filtered(lambda line: float_compare(line.amount_residual, 0.0, precision_rounding=rounding) > 0)
        credit_lines = lines.filtered(lambda line: float_compare(line.amount_residual, 0.0, precision_rounding=rounding) < 0)
        foreign_credit_lines = credit_lines.filtered(lambda line: line.currency_id != self.company_id.currency_id)
        credit_lines -= foreign_credit_lines
        eligible_pos_debits, blocked_debit_lines, eligible_debit_details = self._cdds_classify_default_debits(debit_lines)
        posted_credit = round(sum(-line.amount_residual for line in credit_lines), 2)
        open_debit = round(sum(line.amount_residual for line in debit_lines), 2)
        eligible_pos_debit = round(sum(eligible_pos_debits.mapped("amount_residual")), 2)
        blocked_debit = round(sum(blocked_debit_lines.mapped("amount_residual")), 2)

        credit_info = commercial.get_credit_info(commercial.id, self.company_id.id)
        guarded_deposit = round(float(credit_info.get("deposit_balance") or 0.0), 2)
        net_posted_credit = max(round(posted_credit - open_debit, 2), 0.0)
        available = min(net_posted_credit, guarded_deposit)
        reason = ""
        if foreign_credit_lines:
            reason = _("Foreign-currency customer credits are present. Foreign-currency deposit settlement is deferred.")
            available = 0.0
        elif credit_info.get("has_overdue"):
            reason = _("Overdue customer invoices exist. Reconcile them before applying a deposit to COD.")
            available = 0.0
        elif blocked_debit > rounding:
            reason = _("Unrelated default-receivable debits exist. Only normal POS invoices paid from Customer Account can be netted automatically.")
            available = 0.0
        elif posted_credit <= rounding:
            reason = _("No posted, unreconciled customer deposit credit is available. Same-session deposits are not supported yet.")
        elif guarded_deposit <= rounding:
            reason = _("The customer credit is unavailable under the credit/uncleared-payment guards.")

        snapshot = {
            "commercial": commercial,
            "default_receivable": default_receivable,
            "cod_receivable": cod_receivable,
            "credit_lines": credit_lines,
            "debit_lines": debit_lines,
            "eligible_pos_debit_lines": eligible_pos_debits,
            "blocked_debit_lines": blocked_debit_lines,
            "eligible_debit_details": eligible_debit_details,
            "foreign_credit_lines": foreign_credit_lines,
            "posted_credit": posted_credit,
            "open_debit": open_debit,
            "eligible_pos_debit": eligible_pos_debit,
            "blocked_debit": blocked_debit,
            "net_posted_credit": net_posted_credit,
            "guarded_deposit": guarded_deposit,
            "available": round(max(available, 0.0), 2),
            "reason": reason,
            "credit_info": credit_info,
        }
        self._cdds_log(
            "warning", "BALANCE",
            "order=%s partner=%s default_ar=%s cod_ar=%s credit_lines=%s foreign_credit_lines=%s eligible_pos_debits=%s blocked_debits=%s posted_credit=%.2f open_debit=%.2f net_posted_credit=%.2f guarded_deposit=%.2f available=%.2f reason=%s",
            self.name, commercial.display_name, default_receivable.code, cod_receivable.code,
            credit_lines.ids, foreign_credit_lines.ids, eligible_pos_debits.ids, blocked_debit_lines.ids,
            posted_credit, open_debit, net_posted_credit, guarded_deposit, snapshot["available"], reason or "OK",
        )
        return snapshot

    def _cdds_same_session_snapshot(self, session, credit_snapshot):
        """Return usable validated deposits from this exact open POS session."""
        self.ensure_one()
        commercial = credit_snapshot["commercial"]
        settlement_orders = self.env["pos.order"].sudo().search([
            ("session_id", "=", session.id),
            ("partner_id", "child_of", commercial.id),
            ("state", "in", ("paid", "done", "invoiced")),
        ]).filtered(lambda order: not order.lines)
        payments = settlement_orders.payment_ids.filtered(
            lambda payment: payment.amount > 0
            and not payment.is_change
            and not (
                payment.payment_method_id.type == "pay_later"
                or getattr(payment.payment_method_id, "pcl_is_credit_method", False)
            )
        )
        pending_holds = self.env["pos.uncleared.payment.hold"].sudo().search([
            ("pos_payment_id", "in", payments.ids),
            ("state", "in", ("pending", "accounting_transfer_seen")),
        ]) if payments else self.env["pos.uncleared.payment.hold"]
        guarded_payment_ids = set(pending_holds.mapped("pos_payment_id").ids)
        usable_payments = payments.filtered(lambda payment: payment.id not in guarded_payment_ids)
        gross_usable = round(sum(usable_payments.mapped("amount")), 2)

        reservations = self.env["pos.cod.session.deposit.reservation"].sudo().search([
            ("source_session_id", "=", session.id),
            ("commercial_partner_id", "=", commercial.id),
            ("state", "in", ("reserved", "error")),
        ])
        reserved_total = round(sum(reservations.mapped("amount")), 2)
        credit_info = credit_snapshot["credit_info"]
        effective_total_deposit = max(
            round(
                -(
                    float(credit_info.get("total_due") or 0.0)
                    - float(credit_info.get("session_incoming_payments") or 0.0)
                ),
                2,
            ),
            0.0,
        )
        source_capacity = max(round(gross_usable - reserved_total, 2), 0.0)
        effective_session_capacity = max(
            # get_credit_info already subtracts active reservations from
            # session_incoming_payments; do not subtract them a second time.
            round(effective_total_deposit - credit_snapshot["available"], 2),
            0.0,
        )
        available = min(source_capacity, effective_session_capacity)

        allocated_by_payment = {}
        for reservation in reservations:
            try:
                allocation = json.loads(reservation.source_allocation_json or "[]")
            except (TypeError, ValueError):
                allocation = []
            for item in allocation:
                payment_id = int(item.get("payment_id") or 0)
                allocated_by_payment[payment_id] = round(
                    allocated_by_payment.get(payment_id, 0.0) + float(item.get("amount") or 0.0), 2
                )

        payment_capacities = []
        for payment in usable_payments.sorted(lambda record: (record.payment_date, record.id)):
            remaining = max(round(payment.amount - allocated_by_payment.get(payment.id, 0.0), 2), 0.0)
            if remaining:
                payment_capacities.append({
                    "payment": payment,
                    "remaining": remaining,
                    "order": payment.pos_order_id,
                    "method": payment.payment_method_id,
                })

        result = {
            "settlement_orders": settlement_orders,
            "usable_payments": usable_payments,
            "pending_holds": pending_holds,
            "gross_usable": gross_usable,
            "reserved_total": reserved_total,
            "effective_total_deposit": effective_total_deposit,
            "source_capacity": source_capacity,
            "effective_session_capacity": effective_session_capacity,
            "available": round(max(available, 0.0), 2),
            "payment_capacities": payment_capacities,
        }
        self._cdds_log(
            "warning", "SESSION-BALANCE",
            "order=%s session=%s settlement_orders=%s usable_payments=%s guarded_payments=%s gross=%.2f reserved=%.2f effective_total=%.2f posted_available=%.2f source_capacity=%.2f effective_session_capacity=%.2f available=%.2f",
            self.name, session.name, settlement_orders.mapped("name"), usable_payments.ids,
            sorted(guarded_payment_ids), gross_usable, reserved_total, effective_total_deposit,
            credit_snapshot["available"], source_capacity, effective_session_capacity, result["available"],
        )
        return result

    def _cdds_reserve_same_session_deposit(self, session, amount, operation_uuid, session_snapshot, cod_open_before):
        self.ensure_one()
        allocations = []
        payment_ids = []
        remaining = amount
        for item in session_snapshot["payment_capacities"]:
            allocated = min(item["remaining"], remaining)
            if allocated <= 0:
                continue
            allocations.append({
                "payment_id": item["payment"].id,
                "pos_order_id": item["order"].id,
                "pos_order": item["order"].name,
                "payment_method_id": item["method"].id,
                "payment_method": item["method"].name,
                "amount": round(allocated, 2),
            })
            payment_ids.append(item["payment"].id)
            remaining = round(remaining - allocated, 2)
            if remaining <= self.currency_id.rounding:
                break
        if remaining > self.currency_id.rounding:
            raise UserError(_("Same-session deposit sources changed during reservation. Refresh and try again."))

        reservation = self.env["pos.cod.session.deposit.reservation"].sudo().create({
            "operation_uuid": operation_uuid,
            "order_id": self.id,
            "partner_id": self.partner_id.id,
            "commercial_partner_id": self.partner_id.commercial_partner_id.id,
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "source_session_id": session.id,
            "pos_config_id": session.config_id.id,
            "cashier_id": self.env.user.id,
            "amount": amount,
            "source_payment_ids": [(6, 0, payment_ids)],
            "source_allocation_json": json.dumps(allocations, default=str, sort_keys=True),
        })
        cod_after = max(round(cod_open_before - amount, 2), 0.0)
        self.write({"cod_state": "partial"})
        self.invalidate_recordset([
            "cod_session_deposit_reserved_amount", "cod_amount_paid", "cod_amount_open"
        ])
        self._cdds_log(
            "warning", "RESERVE",
            "reservation=%s operation=%s order=%s session=%s amount=%.2f cod_before=%.2f cod_after=%.2f allocations=%s; COD remains visible until finalization",
            reservation.name, operation_uuid, self.name, session.name, amount, cod_open_before, cod_after, allocations,
        )
        return {
            "success": True,
            "reservation_pending": True,
            "reservation_id": reservation.id,
            "reservation_name": reservation.name,
            "application_id": False,
            "application_name": False,
            "order_id": self.id,
            "order_name": self.name,
            "amount": amount,
            "deposit_remaining": max(round(session_snapshot["available"] - amount, 2), 0.0),
            "remaining": cod_after,
            "cod_state": "partial",
            "move_id": False,
            "move_name": False,
        }

    def _cdds_cod_lines(self, cod_account, amount, lock=False):
        self.ensure_one()
        lines = self.cod_ar_move_id.line_ids.filtered(
            lambda line: line.account_id == cod_account and line.amount_residual > 0 and not line.reconciled
        ).sorted(lambda line: (line.date, line.id))
        if lock and lines:
            self.env.cr.execute(
                "SELECT id FROM account_move_line WHERE id IN %s ORDER BY id FOR UPDATE",
                [tuple(lines.ids)],
            )
            lines.invalidate_recordset(["amount_residual", "reconciled"])
            lines = self.cod_ar_move_id.line_ids.filtered(
                lambda line: line.account_id == cod_account and line.amount_residual > 0 and not line.reconciled
            ).sorted(lambda line: (line.date, line.id))
            self._cdds_log("warning", "LOCK", "locked COD AR lines=%s", lines.ids)
        selected = self.env["account.move.line"]
        accumulated = 0.0
        for line in lines:
            selected |= line
            accumulated += line.amount_residual
            if accumulated + self.currency_id.rounding >= amount:
                break
        return selected, round(accumulated, 2)

    def _cdds_select_credit_lines(self, credit_lines, amount):
        selected = self.env["account.move.line"]
        accumulated = 0.0
        for line in credit_lines:
            selected |= line
            accumulated += -line.amount_residual
            if accumulated + self.currency_id.rounding >= amount:
                break
        return selected, round(accumulated, 2)

    @api.model
    def cod_deposit_quote(self, order_id, session_id=False):
        order = self.browse(int(order_id)).exists()
        session = self.env["pos.session"].browse(int(session_id)).exists() if session_id else self.env["pos.session"]
        if not order or not session:
            raise UserError(_("COD order or POS session was not found."))
        order._cdds_validate_context(session)
        snapshot = order._cdds_credit_snapshot(lock=False)
        session_snapshot = order._cdds_same_session_snapshot(session, snapshot)
        cod_open = round(order._cod_open_amount(), 2)
        hard_reason = ""
        if snapshot["foreign_credit_lines"] or snapshot["credit_info"].get("has_overdue") or snapshot["blocked_debit"]:
            hard_reason = snapshot["reason"]
        source_mode = "posted" if snapshot["available"] > order.currency_id.rounding else "same_session"
        source_available = snapshot["available"] if source_mode == "posted" else session_snapshot["available"]
        if hard_reason:
            source_available = 0.0
        maximum = round(min(cod_open, source_available), 2)
        order._cdds_log(
            "warning", "QUOTE", "order=%s session=%s cod_open=%.2f source_mode=%s posted_available=%.2f same_session_available=%.2f maximum=%.2f hard_reason=%s",
            order.name, session.name, cod_open, source_mode, snapshot["available"],
            session_snapshot["available"], maximum, hard_reason or "OK",
        )
        return {
            "success": float_compare(maximum, 0.0, precision_rounding=order.currency_id.rounding) > 0,
            "order_id": order.id,
            "order_name": order.name,
            "partner_name": order.partner_id.display_name,
            "currency_symbol": order.currency_id.symbol or "",
            "cod_open": cod_open,
            "posted_credit": snapshot["posted_credit"],
            "open_default_receivable": snapshot["open_debit"],
            "eligible_pos_invoice_debit": snapshot["eligible_pos_debit"],
            "blocked_default_receivable": snapshot["blocked_debit"],
            "guarded_deposit": snapshot["guarded_deposit"],
            "posted_deposit_available": snapshot["available"],
            "same_session_deposit_received": session_snapshot["gross_usable"],
            "same_session_deposit_reserved": session_snapshot["reserved_total"],
            "same_session_deposit_available": session_snapshot["available"],
            "source_mode": source_mode,
            "available_deposit": source_available,
            "maximum_amount": maximum,
            "reason": hard_reason or (
                _("No posted or usable validated same-session customer deposit is available.")
                if maximum <= 0 and session_snapshot["available"] <= 0 and cod_open > 0
                else ""
            ) or (_("The COD order has no open balance.") if cod_open <= 0 else ""),
        }

    @api.model
    def cod_apply_deposit(self, order_id, amount, session_id, operation_uuid):
        order = self.browse(int(order_id)).exists()
        session = self.env["pos.session"].browse(int(session_id)).exists()
        if not order or not session:
            raise UserError(_("COD order or POS session was not found."))
        requested = round(float(amount or 0.0), 2)
        if requested <= 0:
            raise ValidationError(_("The deposit amount must be greater than zero."))
        if not operation_uuid:
            raise ValidationError(_("A unique operation reference is required."))

        order._cdds_log(
            "warning", "START", "operation=%s order=%s requested=%.2f session=%s user=%s",
            operation_uuid, order.name, requested, session.name, self.env.user.login,
        )
        try:
            with self.env.cr.savepoint():
                order._cdds_lock_order()
                order._cdds_validate_context(session)
                existing = self.env["pos.cod.deposit.application"].sudo().search([
                    ("company_id", "=", order.company_id.id),
                    ("operation_uuid", "=", operation_uuid),
                ], limit=1)
                if existing:
                    if existing.order_id != order:
                        raise UserError(_("This operation reference already belongs to another COD order."))
                    order._cdds_log("warning", "IDEMPOTENCY", "returning existing application=%s", existing.name)
                    return order._cdds_application_result(existing, idempotent=True)

                finalizing_reservation_id = int(self.env.context.get("cdds_finalize_reservation_id") or 0)
                existing_reservation = self.env["pos.cod.session.deposit.reservation"].sudo().search([
                    ("company_id", "=", order.company_id.id),
                    ("operation_uuid", "=", operation_uuid),
                ], limit=1)
                if existing_reservation and existing_reservation.id != finalizing_reservation_id:
                    if existing_reservation.order_id != order:
                        raise UserError(_("This operation reference already belongs to another COD order."))
                    order._cdds_log(
                        "warning", "IDEMPOTENCY",
                        "returning existing same-session reservation=%s state=%s",
                        existing_reservation.name, existing_reservation.state,
                    )
                    return {
                        "success": True,
                        "idempotent": True,
                        "reservation_pending": existing_reservation.state != "finalized",
                        "reservation_id": existing_reservation.id,
                        "reservation_name": existing_reservation.name,
                        "application_id": existing_reservation.application_id.id,
                        "order_id": order.id,
                        "order_name": order.name,
                        "amount": existing_reservation.amount,
                        "deposit_remaining": 0.0,
                        "remaining": order._cod_open_amount(),
                        "cod_state": order.cod_state,
                        "move_id": existing_reservation.application_id.move_id.id,
                        "move_name": existing_reservation.application_id.move_id.name or False,
                    }

                cod_open_before = round(order._cod_open_amount(), 2)
                snapshot = order._cdds_credit_snapshot(lock=True)
                available = snapshot["available"]
                hard_reason = ""
                if snapshot["foreign_credit_lines"] or snapshot["credit_info"].get("has_overdue") or snapshot["blocked_debit"]:
                    hard_reason = snapshot["reason"]
                if hard_reason:
                    raise UserError(hard_reason)

                if not finalizing_reservation_id and available <= order.currency_id.rounding:
                    session_snapshot = order._cdds_same_session_snapshot(session, snapshot)
                    if float_compare(requested, session_snapshot["available"], precision_rounding=order.currency_id.rounding) <= 0:
                        if float_compare(requested, cod_open_before, precision_rounding=order.currency_id.rounding) > 0:
                            raise UserError(_("Requested amount %.2f exceeds the COD open balance %.2f.") % (requested, cod_open_before))
                        return order._cdds_reserve_same_session_deposit(
                            session, requested, operation_uuid, session_snapshot, cod_open_before
                        )

                if snapshot["reason"] and available <= order.currency_id.rounding:
                    raise UserError(snapshot["reason"])
                if float_compare(requested, available, precision_rounding=order.currency_id.rounding) > 0:
                    raise UserError(_("Requested amount %.2f exceeds the cleared available deposit %.2f.") % (requested, available))
                if float_compare(requested, cod_open_before, precision_rounding=order.currency_id.rounding) > 0:
                    raise UserError(_("Requested amount %.2f exceeds the COD open balance %.2f.") % (requested, cod_open_before))

                eligible_pos_debits = snapshot["eligible_pos_debit_lines"]
                default_reconcile_target = round(requested + snapshot["eligible_pos_debit"], 2)
                source_credits, source_total = order._cdds_select_credit_lines(
                    snapshot["credit_lines"], default_reconcile_target
                )
                cod_lines, cod_total = order._cdds_cod_lines(snapshot["cod_receivable"], requested, lock=True)
                if source_total + order.currency_id.rounding < default_reconcile_target:
                    raise UserError(_("Posted customer credit lines changed during settlement. Refresh and try again."))
                if cod_total + order.currency_id.rounding < requested:
                    raise UserError(_("COD receivable residual changed during settlement. Refresh and try again."))

                move_date = fields.Date.context_today(order)
                move = self.env["account.move"].sudo().create({
                    "move_type": "entry",
                    "journal_id": session.config_id.cdds_transfer_journal_id.id,
                    "date": move_date,
                    "ref": "COD-DEPOSIT-%s" % order.name,
                    "narration": "Customer deposit applied to COD %s | Customer: %s | Operation: %s" % (
                        order.name, snapshot["commercial"].display_name, operation_uuid,
                    ),
                    "company_id": order.company_id.id,
                    "line_ids": [
                        (0, 0, {
                            "account_id": snapshot["default_receivable"].id,
                            "partner_id": snapshot["commercial"].id,
                            "name": "Customer deposit consumed - %s" % order.name,
                            "date_maturity": move_date,
                            "debit": requested,
                            "credit": 0.0,
                        }),
                        (0, 0, {
                            "account_id": snapshot["cod_receivable"].id,
                            "partner_id": snapshot["commercial"].id,
                            "name": "COD receivable settled from deposit - %s" % order.name,
                            "date_maturity": move_date,
                            "debit": 0.0,
                            "credit": requested,
                        }),
                    ],
                })
                move.action_post()
                bridge_default = move.line_ids.filtered(lambda line: line.account_id == snapshot["default_receivable"])
                bridge_cod = move.line_ids.filtered(lambda line: line.account_id == snapshot["cod_receivable"])
                order._cdds_log(
                    "warning", "MOVE", "posted move=%s id=%s DR_default=%.2f account=%s CR_cod=%.2f account=%s",
                    move.name, move.id, requested, snapshot["default_receivable"].code,
                    requested, snapshot["cod_receivable"].code,
                )

                (source_credits | eligible_pos_debits | bridge_default).reconcile()
                source_credits.invalidate_recordset(["amount_residual", "reconciled"])
                eligible_pos_debits.invalidate_recordset(["amount_residual", "reconciled"])
                bridge_default.invalidate_recordset(["amount_residual", "reconciled"])
                order._cdds_log(
                    "warning", "RECONCILE-DEFAULT", "move=%s credit_sources=%s eligible_pos_invoice_debits=%s bridge=%s target=%.2f bridge_residual=%.2f credit_residuals=%s pos_debit_residuals=%s",
                    move.name, source_credits.ids, eligible_pos_debits.ids, bridge_default.ids, default_reconcile_target,
                    sum(bridge_default.mapped("amount_residual")),
                    [(line.id, line.amount_residual) for line in source_credits],
                    [(line.id, line.amount_residual) for line in eligible_pos_debits],
                )
                (cod_lines | bridge_cod).reconcile()
                cod_lines.invalidate_recordset(["amount_residual", "reconciled"])
                bridge_cod.invalidate_recordset(["amount_residual", "reconciled"])
                order._cdds_log(
                    "warning", "RECONCILE-COD", "move=%s sources=%s bridge=%s bridge_residual=%.2f cod_residuals=%s",
                    move.name, cod_lines.ids, bridge_cod.ids,
                    sum(bridge_cod.mapped("amount_residual")),
                    [(line.id, line.amount_residual) for line in cod_lines],
                )
                if not float_is_zero(sum(bridge_default.mapped("amount_residual")), precision_rounding=order.currency_id.rounding):
                    raise UserError(_("Default receivable reconciliation did not fully consume the requested amount."))
                if not float_is_zero(sum(bridge_cod.mapped("amount_residual")), precision_rounding=order.currency_id.rounding):
                    raise UserError(_("COD receivable reconciliation did not fully clear the requested amount."))

                cod_open_after = max(round(cod_open_before - requested, 2), 0.0)
                deposit_after = max(round(available - requested, 2), 0.0)
                debug_snapshot = json.dumps({
                    "credit_info": {key: value for key, value in snapshot["credit_info"].items() if not key.startswith("upg_uncleared_hold_ids")},
                    "source_credit_line_ids": source_credits.ids,
                    "source_pos_invoice_debit_line_ids": eligible_pos_debits.ids,
                    "eligible_pos_invoice_details": snapshot["eligible_debit_details"],
                    "cod_source_line_ids": cod_lines.ids,
                    "source_credit_total": source_total,
                    "eligible_pos_invoice_debit_total": snapshot["eligible_pos_debit"],
                    "default_reconcile_target": default_reconcile_target,
                    "cod_source_total": cod_total,
                }, default=str, sort_keys=True)
                application = self.env["pos.cod.deposit.application"].sudo().create({
                    "operation_uuid": operation_uuid,
                    "reservation_id": finalizing_reservation_id or False,
                    "order_id": order.id,
                    "partner_id": order.partner_id.id,
                    "commercial_partner_id": snapshot["commercial"].id,
                    "company_id": order.company_id.id,
                    "currency_id": order.currency_id.id,
                    "pos_config_id": session.config_id.id,
                    "pos_session_id": session.id,
                    "cashier_id": self.env.user.id,
                    "requested_amount": requested,
                    "amount": requested,
                    "deposit_before": available,
                    "deposit_after": deposit_after,
                    "cod_open_before": cod_open_before,
                    "cod_open_after": cod_open_after,
                    "default_receivable_account_id": snapshot["default_receivable"].id,
                    "cod_receivable_account_id": snapshot["cod_receivable"].id,
                    "transfer_journal_id": session.config_id.cdds_transfer_journal_id.id,
                    "move_id": move.id,
                    "source_credit_line_ids": [(6, 0, source_credits.ids)],
                    "source_pos_invoice_debit_line_ids": [(6, 0, eligible_pos_debits.ids)],
                    "cod_source_line_ids": [(6, 0, cod_lines.ids)],
                    "bridge_receivable_line_id": bridge_default.id,
                    "bridge_cod_line_id": bridge_cod.id,
                    "debug_snapshot": debug_snapshot,
                })
                application.with_context(cdds_allow_audit_write=True).write({"state": "posted"})
                target_state = "paid" if cod_open_after <= order.currency_id.rounding else "partial"
                order.write({"cod_state": target_state})
                order.invalidate_recordset(["cod_deposit_applied_amount", "cod_amount_paid", "cod_amount_open"])
                application._cdds_create_transaction_log()
                order._cdds_log(
                    "warning", "SUCCESS", "application=%s operation=%s order=%s move=%s amount=%.2f deposit_before=%.2f deposit_after=%.2f cod_before=%.2f cod_after=%.2f state=%s",
                    application.name, operation_uuid, order.name, move.name, requested,
                    available, deposit_after, cod_open_before, cod_open_after, target_state,
                )
                return order._cdds_application_result(application)
        except Exception as exc:
            order._cdds_log(
                "exception", "ERROR", "operation=%s order=%s requested=%.2f failed=%s",
                operation_uuid, order.name, requested, str(exc),
            )
            raise

    def _cdds_application_result(self, application, idempotent=False):
        self.ensure_one()
        return {
            "success": True,
            "idempotent": idempotent,
            "application_id": application.id,
            "application_name": application.name,
            "order_id": self.id,
            "order_name": self.name,
            "amount": application.amount,
            "deposit_remaining": application.deposit_after,
            "remaining": application.cod_open_after,
            "cod_state": "paid" if application.cod_open_after <= self.currency_id.rounding else "partial",
            "move_id": application.move_id.id,
            "move_name": application.move_id.name,
        }

    @api.model
    def cod_deposit_reservation_status(self, order_ids):
        orders = self.browse([int(order_id) for order_id in (order_ids or [])]).exists()
        result = {}
        for order in orders:
            reservation = order.cod_session_deposit_reservation_ids.filtered(
                lambda record: record.state in ("reserved", "finalizing", "error")
            ).sorted(lambda record: record.id, reverse=True)[:1]
            result[order.id] = {
                "cdds_reservation_id": reservation.id,
                "cdds_reservation_name": reservation.name or "",
                "cdds_reservation_state": reservation.state or "",
                "cdds_reserved_amount": order.cod_session_deposit_reserved_amount,
                "cdds_reservation_label": (
                    _("Deposit Reserved - Pending Session Posting") if reservation.state == "reserved"
                    else _("Deposit Finalization Error") if reservation.state == "error"
                    else _("Deposit Finalizing") if reservation else ""
                ),
            }
        self._cdds_log(
            "warning", "RESERVATION-STATUS", "orders=%s result=%s", orders.ids, result
        ) if len(orders) == 1 else _logger.warning(
            "%s[RESERVATION-STATUS] orders=%s result=%s", _LOG, orders.ids, result
        )
        return result
