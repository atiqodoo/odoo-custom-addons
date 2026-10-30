import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    _inherit = "pos.config"

    pcd_enabled = fields.Boolean(string="Cheque Banking Reminders and Receipts")
    pcd_refresh_seconds = fields.Integer(string="Cheque Reminder Refresh (seconds)", default=60)
    pcd_popup_interval_seconds = fields.Integer(
        string="Repeat Banking Popup After (seconds)", default=300,
        help="After the cashier dismisses the banking reminder with X, show it again after this interval if cheques are still due. The first reminder opens automatically on POS startup.",
    )

    def _pcd_check_configuration_access(self):
        if not self.env.su and not self.env.user.has_group("point_of_sale.group_pos_manager"):
            raise AccessError(_("Only POS managers can change cheque deposit controls."))

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get("pcd_enabled") or {"pcd_refresh_seconds", "pcd_popup_interval_seconds"}.intersection(vals) for vals in vals_list):
            self._pcd_check_configuration_access()
        return super().create(vals_list)

    def write(self, vals):
        controlled = {"pcd_enabled", "pcd_refresh_seconds", "pcd_popup_interval_seconds", "upg_deposit_bank_journal_ids",
                      "upg_uncleared_payment_method_ids", "payment_method_ids", "company_id"}
        if {"pcd_enabled", "pcd_refresh_seconds", "pcd_popup_interval_seconds"}.intersection(vals) or (
            controlled.intersection(vals) and any(self.mapped("pcd_enabled"))
        ):
            self._pcd_check_configuration_access()
            _logger.debug("[PCD][CONFIGURE][START] config_ids=%s fields=%s", self.ids, sorted(controlled.intersection(vals)))
            try:
                result = super().write(vals)
            except Exception:
                _logger.debug("[PCD][CONFIGURE][ERROR] config_ids=%s", self.ids)
                raise
            _logger.debug("[PCD][CONFIGURE][END] config_ids=%s", self.ids)
            return result
        return super().write(vals)

    @api.constrains("pcd_enabled", "pcd_refresh_seconds", "pcd_popup_interval_seconds", "payment_method_ids",
                    "upg_deposit_bank_journal_ids", "upg_uncleared_payment_method_ids")
    def _pcd_validate_configuration(self):
        for config in self.sudo().filtered("pcd_enabled"):
            if config.pcd_refresh_seconds <= 0:
                raise ValidationError(_("The cheque reminder refresh interval must be positive."))
            if config.pcd_popup_interval_seconds <= 0:
                raise ValidationError(_("The banking popup repeat interval must be positive."))
            methods = config.payment_method_ids.filtered("pcd_is_cheque")
            if not methods:
                raise ValidationError(_("Mark at least one POS payment method for Cheque Deposit Control."))
            if any(not method.upg_is_uncleared_guard_method and method not in config.upg_uncleared_payment_method_ids for method in methods):
                raise ValidationError(_("Map each cheque method in the existing uncleared payment guard."))
            banks = config.upg_deposit_bank_journal_ids
            if not banks or any(bank.company_id != config.company_id or bank.type != "bank" for bank in banks):
                raise ValidationError(_("Select one or more destination bank journals belonging to this POS company."))
            for method in methods:
                if method.company_id != config.company_id or not (method.journal_id.default_account_id or method.outstanding_account_id):
                    raise ValidationError(_("Each cheque method needs a collection account in the POS company."))
            for bank in banks:
                accounts = bank.inbound_payment_method_line_ids.payment_account_id
                if not accounts or any(not account.reconcile for account in accounts):
                    raise ValidationError(_("Each destination bank needs a reconcilable Outstanding Receipts account."))
