# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger("pos_uncleared_payment_guard.pos_config")


class PosConfig(models.Model):
    _inherit = "pos.config"

    upg_uncleared_payment_method_ids = fields.Many2many(
        "pos.payment.method",
        "pos_config_upg_uncleared_payment_method_rel",
        "config_id",
        "payment_method_id",
        string="Uncleared Deposit/Due Payment Methods",
        help=(
            "Payments received through these methods are accepted normally, "
            "but Customer Deposit / Settle Due amounts remain unavailable in "
            "future POS credit/deposit calculations until reconciled or manually cleared."
        ),
    )
    upg_debug_logging = fields.Boolean(
        string="Uncleared Payment Debug Logging",
        default=True,
        help="Enable detailed [UPG] browser console traces for uncleared payment guard logic.",
    )
    upg_deposit_bank_journal_ids = fields.Many2many(
        "account.journal",
        "pos_config_upg_deposit_bank_journal_rel",
        "config_id",
        "journal_id",
        string="Allowed Deposit Bank Journals",
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
        help=(
            "Bank journals shown in the POS cheque capture wizard. "
            "Leave empty to show all active bank journals for the POS company."
        ),
    )

    # Do not override _load_pos_data_fields here.
    #
    # Odoo 18 pos.config uses the pos.load.mixin default [] to mean
    # "load every field". Returning an explicit partial list would make the
    # POS boot payload miss standard fields such as company_id/payment_method_ids
    # and can crash PosData.initData before the POS UI starts.
