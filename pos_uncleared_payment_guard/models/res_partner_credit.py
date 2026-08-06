# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger("pos_uncleared_payment_guard.res_partner_credit")


class ResPartnerCredit(models.Model):
    _inherit = "res.partner"

    @api.model
    def get_credit_info(self, partner_id, company_id=False):
        result = super().get_credit_info(partner_id, company_id)
        if result.get("error"):
            return result

        partner = self.browse(partner_id).exists()
        if not partner:
            return result

        commercial = partner.commercial_partner_id
        pending = self.env["pos.uncleared.payment.hold"]._upg_pending_amounts_for_partner(
            commercial,
            company_id,
        )
        session_credit_charges = self._upg_get_open_session_credit_charges(
            commercial,
            company_id,
        )
        if not pending["pending_total"] and not session_credit_charges:
            _logger.warning(
                "[UPG][CreditInfo] partner=%s company=%s no pending holds or open-session "
                "credit charges; returning PCL result unchanged",
                commercial.display_name,
                company_id,
            )
            return result

        original_total_due = float(result.get("total_due") or 0.0)
        original_deposit = float(result.get("deposit_balance") or 0.0)
        original_session_incoming = float(result.get("session_incoming_payments") or 0.0)
        pending_accounting_effect = float(pending["pending_accounting_effect"] or 0.0)

        adjusted_total_due = round(
            original_total_due + pending_accounting_effect,
            2,
        )
        adjusted_deposit = max(0.0, round(-adjusted_total_due, 2))
        adjusted_session_incoming = round(
            original_session_incoming - session_credit_charges,
            2,
        )

        result.update({
            "total_due": adjusted_total_due,
            "deposit_balance": adjusted_deposit,
            "session_incoming_payments": adjusted_session_incoming,
            "upg_uncleared_pending_amount": pending["pending_total"],
            "upg_uncleared_pending_open_session": pending["pending_open_session"],
            "upg_uncleared_pending_accounting_effect": pending["pending_accounting_effect"],
            "upg_uncleared_hold_count": pending["hold_count"],
            "upg_uncleared_hold_ids": pending["hold_ids"],
            "upg_open_session_credit_charges": session_credit_charges,
        })

        _logger.warning(
            "[UPG][CreditInfo] partner=%s company=%s original_total_due=%.2f "
            "pending_open=%.2f pending_accounting_effect=%.2f open_session_credit_charges=%.2f "
            "adjusted_total_due=%.2f original_deposit=%.2f adjusted_deposit=%.2f "
            "original_session_incoming=%.2f adjusted_session_incoming=%.2f holds=%s",
            commercial.display_name,
            company_id,
            original_total_due,
            pending["pending_open_session"],
            pending["pending_accounting_effect"],
            session_credit_charges,
            adjusted_total_due,
            original_deposit,
            adjusted_deposit,
            original_session_incoming,
            adjusted_session_incoming,
            pending["hold_ids"],
        )
        return result

    @api.model
    def _upg_get_open_session_credit_charges(self, commercial_partner, company_id=False):
        """Count synced Customer Account sales in open sessions.

        The POS frontend already counts browser-local unsynced Customer Account
        usage. Once such an order reaches the backend, it has a server id and
        drops out of that browser-side counter, while accounting has still not
        posted the open POS session. This read-only balance overlay closes that
        timing gap without touching standard POS/accounting moves.
        """
        if not commercial_partner:
            return 0.0

        PosSession = self.env["pos.session"].sudo()
        PosOrder = self.env["pos.order"].sudo()

        session_domain = [("state", "=", "opened")]
        if company_id:
            session_domain.append(("company_id", "=", company_id))
        open_sessions = PosSession.search(session_domain)
        if not open_sessions:
            _logger.warning(
                "[UPG][OpenSessionCreditCharges] partner=%s company=%s no open sessions",
                commercial_partner.display_name,
                company_id,
            )
            return 0.0

        order_domain = [
            ("session_id", "in", open_sessions.ids),
            ("partner_id", "child_of", commercial_partner.id),
            ("state", "in", ("paid", "done", "invoiced")),
        ]
        orders = PosOrder.search(order_domain)
        total = 0.0
        tracked_orders = []
        skipped_orders = []

        for order in orders:
            if not order.lines:
                continue
            if order.state == "invoiced" or order.account_move:
                skipped_orders.append("%s:%s" % (order.name, order.state))
                continue

            order_credit_total = 0.0
            for payment in order.payment_ids:
                method = payment.payment_method_id
                is_credit_method = (
                    getattr(method, "pcl_is_credit_method", False)
                    or method.type == "pay_later"
                )
                if is_credit_method and payment.amount > 0:
                    order_credit_total += float(payment.amount or 0.0)

            if order_credit_total:
                total += order_credit_total
                tracked_orders.append("%s:%s" % (order.name, round(order_credit_total, 2)))

        rounded_total = max(0.0, round(total, 2))
        _logger.warning(
            "[UPG][OpenSessionCreditCharges] partner=%s company=%s sessions=%s "
            "orders=%s skipped_accounted=%s total=%.2f",
            commercial_partner.display_name,
            company_id,
            open_sessions.ids,
            tracked_orders,
            skipped_orders,
            rounded_total,
        )
        return rounded_total

    def _pcl_get_session_incoming_payments(self, commercial_partner, company_id=False):
        raw_total = super()._pcl_get_session_incoming_payments(commercial_partner, company_id)
        pending = self.env["pos.uncleared.payment.hold"]._upg_pending_amounts_for_partner(
            commercial_partner,
            company_id,
        )
        if not pending["pending_open_session"]:
            _logger.warning(
                "[UPG][SessionIncoming] partner=%s company=%s no pending open-session holds; raw unchanged=%.2f",
                commercial_partner.display_name,
                company_id,
                float(raw_total or 0.0),
            )
            return raw_total
        adjusted = max(0.0, round(float(raw_total or 0.0) - float(pending["pending_open_session"] or 0.0), 2))
        _logger.warning(
            "[UPG][SessionIncoming] partner=%s company=%s raw=%.2f pending_open=%.2f adjusted=%.2f",
            commercial_partner.display_name,
            company_id,
            float(raw_total or 0.0),
            pending["pending_open_session"],
            adjusted,
        )
        return adjusted
