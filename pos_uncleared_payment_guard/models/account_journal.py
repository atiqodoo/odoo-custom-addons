# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger("pos_uncleared_payment_guard.account_journal")


class AccountJournal(models.Model):
    _inherit = "account.journal"

    @api.model
    def _load_pos_data_domain(self, data):
        config = self.env["pos.config"].browse(data["pos.config"]["data"][0]["id"]).exists()
        company = config.company_id or self.env.company
        allowed = config.upg_deposit_bank_journal_ids
        domain = [
            ("type", "=", "bank"),
            ("company_id", "=", company.id),
            ("active", "=", True),
        ]
        if allowed:
            domain.append(("id", "in", allowed.ids))
        _logger.warning(
            "[UPG][JournalLoad] config=%s company=%s allowed_only=%s domain=%s",
            config.display_name,
            company.display_name,
            bool(allowed),
            domain,
        )
        return domain

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ["id", "name", "code", "type", "company_id"]

    def _load_pos_data(self, data):
        domain = self._load_pos_data_domain(data)
        fields_list = self._load_pos_data_fields(data["pos.config"]["data"][0]["id"])
        journals = self.search_read(domain, fields_list, load=False)
        _logger.warning(
            "[UPG][JournalLoad] loaded bank journals count=%s ids=%s",
            len(journals),
            [journal["id"] for journal in journals],
        )
        return {"data": journals, "fields": fields_list}
