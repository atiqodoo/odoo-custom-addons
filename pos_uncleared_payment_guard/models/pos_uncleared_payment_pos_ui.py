# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger("pos_uncleared_payment_guard.pos_ui")


class PosUnclearedPaymentHoldPosUi(models.Model):
    _inherit = "pos.uncleared.payment.hold"

    @api.model
    def upg_pos_pending_holds(self, company_id=False, limit=100):
        domain = [
            "|",
            ("state", "in", ("pending", "accounting_transfer_seen")),
            "&",
            ("state", "=", "manual_cleared"),
            ("bank_statement_line_id", "=", False),
        ]
        if company_id:
            domain.append(("company_id", "=", company_id))

        holds = self.sudo().search(domain, order="create_date desc, id desc", limit=limit)
        _logger.warning(
            "[UPG][POSUI] visible uncleared holds requested company=%s limit=%s count=%s",
            company_id,
            limit,
            len(holds),
        )

        result = []
        for hold in holds:
            currency = hold.currency_id or hold.company_id.currency_id
            result.append({
                "id": hold.id,
                "name": hold.name,
                "partner": hold.partner_id.display_name,
                "commercial_partner": hold.commercial_partner_id.display_name,
                "payment_method": hold.payment_method_id.display_name,
                "order": hold.pos_order_id.name or hold.pos_order_id.pos_reference,
                "session": hold.pos_session_id.name,
                "amount": float(hold.amount or 0.0),
                "currency_symbol": currency.symbol or currency.name or "",
                "currency_position": currency.position or "before",
                "state": hold.state,
                "deposit_bank_journal": hold.deposit_bank_journal_id.display_name,
                "cheque_bank": hold.cheque_bank or "",
                "cheque_account_number": hold.cheque_account_number or "",
                "cheque_number": hold.cheque_number or "",
                "cheque_date": fields.Date.to_string(hold.cheque_date) if hold.cheque_date else "",
                "transfer": hold.accounting_transfer_move_id.name or "",
                "statement_line": hold.bank_statement_line_id.display_name or "",
                "date": fields.Datetime.to_string(hold.create_date) if hold.create_date else "",
            })
        return result
