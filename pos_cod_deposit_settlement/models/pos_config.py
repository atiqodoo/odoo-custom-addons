# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger("pos_cod_deposit_settlement.config")


class PosConfig(models.Model):
    _inherit = "pos.config"

    cdds_enable_cod_deposit_settlement = fields.Boolean(
        string="Enable COD Deposit Settlement",
        default=False,
        help="Allow posted, cleared customer receivable credits to settle open COD receivables.",
    )
    cdds_transfer_journal_id = fields.Many2one(
        "account.journal",
        string="COD Deposit Transfer Journal",
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        help="General journal used for DR Customer Receivable / CR COD Receivable transfers.",
    )
    cdds_debug_logging = fields.Boolean(
        string="Enhanced COD Deposit Debug Logging",
        default=True,
    )

    @api.constrains("cdds_enable_cod_deposit_settlement", "cdds_transfer_journal_id")
    def _check_cdds_transfer_journal(self):
        for config in self:
            if config.cdds_enable_cod_deposit_settlement and not config.cdds_transfer_journal_id:
                raise ValidationError("A general COD Deposit Transfer Journal is required when deposit settlement is enabled.")
            journal = config.cdds_transfer_journal_id
            if journal and journal.type != "general":
                raise ValidationError("The COD Deposit Transfer Journal must be a General journal, not Cash or Bank.")
            if journal and journal.company_id != config.company_id:
                raise ValidationError("The COD Deposit Transfer Journal must belong to the POS company.")

    @api.model
    def _load_pos_data_fields(self, config_id):
        result = super()._load_pos_data_fields(config_id)
        if not result:
            return result
        for field_name in (
            "cdds_enable_cod_deposit_settlement",
            "cdds_transfer_journal_id",
            "cdds_debug_logging",
        ):
            if field_name not in result:
                result.append(field_name)
        _logger.debug("[COD-DEPOSIT][CONFIG] exposed POS fields config_id=%s", config_id)
        return result
