# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger("pos_cod_deposit_settlement.res_partner_credit")


class ResPartnerCredit(models.Model):
    _inherit = "res.partner"

    @api.model
    def get_credit_info(self, partner_id, company_id=False):
        """Remove active COD reservations from normal POS usable deposits.

        `pos_credit_limit` represents validated, unposted deposits through
        `session_incoming_payments`. A COD reservation consumes that same value,
        so reducing this field makes the existing frontend True Balance formula
        immediately expose only the unreserved remainder.
        """
        result = super().get_credit_info(partner_id, company_id)
        if result.get("error"):
            return result

        partner = self.browse(partner_id).exists()
        if not partner:
            return result
        commercial = partner.commercial_partner_id
        domain = [
            ("commercial_partner_id", "=", commercial.id),
            ("state", "in", ("reserved", "error")),
            ("source_session_id.state", "in", ("opened", "closing_control")),
        ]
        if company_id:
            domain.append(("company_id", "=", company_id))
        reservations = self.env["pos.cod.session.deposit.reservation"].sudo().search(domain)
        reserved_total = round(sum(reservations.mapped("amount")), 2)
        original_session_incoming = float(result.get("session_incoming_payments") or 0.0)
        adjusted_session_incoming = round(original_session_incoming - reserved_total, 2)

        result.update({
            "session_incoming_payments": adjusted_session_incoming,
            "cdds_session_incoming_before_reservation": original_session_incoming,
            "cdds_session_reserved_amount": reserved_total,
            "cdds_session_reservation_ids": reservations.ids,
        })

        # Recompute overdue availability with only the unreserved incoming value.
        overdue_info = self._pcl_get_overdue_info(
            commercial,
            company_id,
            max(adjusted_session_incoming, 0.0),
        )
        result.update({
            "has_overdue": overdue_info["has_overdue"],
            "overdue_amount": overdue_info["overdue_amount"],
            "overdue_invoice_count": overdue_info["overdue_invoice_count"],
            "oldest_overdue_date": overdue_info["oldest_overdue_date"],
        })

        _logger.warning(
            "[COD-DEPOSIT][CREDIT-OVERLAY] partner=%s company=%s "
            "session_incoming_before=%.2f active_reserved=%.2f "
            "session_incoming_after=%.2f reservations=%s overdue_after=%s overdue_amount_after=%.2f",
            commercial.display_name,
            company_id,
            original_session_incoming,
            reserved_total,
            adjusted_session_incoming,
            [(r.name, r.order_id.name, r.amount, r.state, r.source_session_id.name) for r in reservations],
            overdue_info["has_overdue"],
            overdue_info["overdue_amount"],
        )
        return result
