# -*- coding: utf-8 -*-
"""Manager-facing upload and template download wizard."""

import base64
import logging

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


_logger = logging.getLogger(__name__)


class TintingFormulaImportWizard(models.TransientModel):
    _name = 'tinting.formula.import.wizard'
    _description = 'Import Tinting Formula Drafts'

    upload_file = fields.Binary(string='Formula Spreadsheet', attachment=False)
    upload_filename = fields.Char(string='Filename')

    def _check_manager(self):
        if not self.env.user.has_group('paint_tinting.group_tint_formula_manager'):
            raise AccessError(_('Only Tinting Formula Managers can import formula spreadsheets.'))

    def action_download_template(self):
        self.ensure_one()
        self._check_manager()
        payload = self.env['tinting.formula.spreadsheet.service'].build_template()
        attachment = self.env['ir.attachment'].create({
            'name': 'paint_tinting_formula_import_template.xlsx',
            'datas': base64.b64encode(payload),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        _logger.info(
            "FORMULA_TEMPLATE_DOWNLOAD attachment_id=%s bytes=%s user_id=%s",
            attachment.id, len(payload), self.env.user.id,
        )
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    def action_validate_upload(self):
        self.ensure_one()
        self._check_manager()
        if not self.upload_file:
            raise ValidationError(_('Select an XLSX formula spreadsheet first.'))
        filename = self.upload_filename or 'formula_import.xlsx'
        if not filename.lower().endswith('.xlsx'):
            raise ValidationError(_('Only .xlsx files generated from the template are supported.'))
        payload = base64.b64decode(self.upload_file)
        _logger.info(
            "FORMULA_IMPORT_UPLOAD_RECEIVED filename=%s bytes=%s user_id=%s",
            filename, len(payload), self.env.user.id,
        )
        batch = self.env['tinting.formula.spreadsheet.service'].parse_to_batch(payload, filename)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Formula Import Preview'),
            'res_model': 'tinting.formula.import.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }
