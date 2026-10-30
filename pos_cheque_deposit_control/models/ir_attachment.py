import logging

from odoo import models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _pcd_check_receipt_protection(self):
        # Read only the protection relationship; never elevate attachment mutation.
        if self.env["account.move"].sudo().search_count([
            ("state", "=", "posted"), ("pcd_receipt_ids", "in", self.ids),
        ], limit=1):
            _logger.debug("[PCD][PROTECT_RECEIPT][ERROR] attachment_ids=%s", self.ids)
            raise ValidationError(_("This is a posted cheque deposit receipt. Reset its journal entry to draft before changing or deleting the receipt."))

    def write(self, vals):
        if {"datas", "raw", "db_datas", "store_fname", "res_model", "res_id", "res_field",
            "company_id", "type", "url", "public", "mimetype", "name", "access_token"}.intersection(vals):
            self._pcd_check_receipt_protection()
        return super().write(vals)

    def unlink(self):
        self._pcd_check_receipt_protection()
        return super().unlink()
