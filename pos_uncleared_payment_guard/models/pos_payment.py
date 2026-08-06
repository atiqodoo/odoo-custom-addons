# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger("pos_uncleared_payment_guard.pos_payment")


class PosPayment(models.Model):
    _inherit = "pos.payment"

    upg_deposit_bank_journal_id = fields.Many2one(
        "account.journal",
        string="Uncleared Deposit Bank Journal",
        domain="[('type', '=', 'bank')]",
        readonly=True,
        copy=False,
    )
    upg_cheque_bank = fields.Char(string="Cheque Bank", readonly=True, copy=False)
    upg_cheque_account_number = fields.Char(string="Cheque Account Number", readonly=True, copy=False)
    upg_cheque_number = fields.Char(string="Cheque Number", readonly=True, copy=False)
    upg_cheque_date = fields.Date(string="Cheque Date", readonly=True, copy=False)

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if not fields_list:
            _logger.debug("[UPG][PosPayment] POS data fields left as all-fields for config=%s", config_id)
            return fields_list
        for field_name in (
            "upg_deposit_bank_journal_id",
            "upg_cheque_bank",
            "upg_cheque_account_number",
            "upg_cheque_number",
            "upg_cheque_date",
        ):
            if field_name not in fields_list:
                fields_list.append(field_name)
        _logger.debug("[UPG][PosPayment] POS data fields extended for config=%s", config_id)
        return fields_list

    def _upg_is_uncleared_guard_payment(self):
        self.ensure_one()
        config = self.session_id.config_id
        method = self.payment_method_id
        config_mapped = bool(method and method in config.upg_uncleared_payment_method_ids)
        method_mapped = bool(method and method.upg_is_uncleared_guard_method)
        result = bool(
            method
            and (config_mapped or method_mapped)
        )
        _logger.debug(
            "[UPG][PosPayment] payment_id=%s method=%s amount=%.2f guarded=%s "
            "config_mapped=%s method_mapped=%s config=%s",
            self.id,
            method.display_name if method else "N/A",
            self.amount,
            result,
            config_mapped,
            method_mapped,
            config.display_name if config else "N/A",
        )
        return result

    def _upg_prepare_hold_vals(self):
        self.ensure_one()
        order = self.pos_order_id
        partner = order.partner_id
        commercial = partner.commercial_partner_id if partner else self.env["res.partner"]
        return {
            "partner_id": partner.id,
            "commercial_partner_id": commercial.id,
            "pos_order_id": order.id,
            "pos_payment_id": self.id,
            "payment_method_id": self.payment_method_id.id,
            "pos_config_id": order.config_id.id,
            "pos_session_id": order.session_id.id,
            "company_id": order.company_id.id,
            "currency_id": order.currency_id.id,
            "amount": abs(self.amount),
            "state": "pending",
            "deposit_bank_journal_id": self.upg_deposit_bank_journal_id.id or False,
            "cheque_bank": self.upg_cheque_bank or "",
            "cheque_account_number": self.upg_cheque_account_number or "",
            "cheque_number": self.upg_cheque_number or "",
            "cheque_date": self.upg_cheque_date or False,
        }
