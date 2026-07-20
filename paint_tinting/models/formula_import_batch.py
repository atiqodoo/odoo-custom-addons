# -*- coding: utf-8 -*-
"""Persistent staging and audit trail for bulk formula imports."""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


_logger = logging.getLogger(__name__)


class TintingFormulaImportBatch(models.Model):
    _name = 'tinting.formula.import.batch'
    _description = 'Tinting Formula Import Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(default=lambda self: _('New Formula Import'), required=True, readonly=True)
    filename = fields.Char(required=True, readonly=True)
    source_attachment_id = fields.Many2one('ir.attachment', readonly=True, ondelete='set null')
    state = fields.Selection([
        ('preview', 'Preview'),
        ('imported', 'Drafts Created'),
        ('partial', 'Partially Imported'),
        ('cancelled', 'Cancelled'),
    ], default='preview', required=True, tracking=True)
    row_ids = fields.One2many('tinting.formula.import.row', 'batch_id', readonly=True)
    row_count = fields.Integer(compute='_compute_counts')
    valid_count = fields.Integer(compute='_compute_counts')
    duplicate_count = fields.Integer(compute='_compute_counts')
    error_count = fields.Integer(compute='_compute_counts')
    imported_count = fields.Integer(compute='_compute_counts')
    imported_version_ids = fields.One2many('tinting.formula.version', 'import_batch_id', readonly=True)
    uploaded_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    uploaded_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    log_summary = fields.Text(readonly=True)

    @api.depends('row_ids.state')
    def _compute_counts(self):
        for batch in self:
            batch.row_count = len(batch.row_ids)
            batch.valid_count = len(batch.row_ids.filtered(lambda row: row.state == 'valid'))
            batch.duplicate_count = len(batch.row_ids.filtered(lambda row: row.state == 'duplicate'))
            batch.error_count = len(batch.row_ids.filtered(lambda row: row.state == 'error'))
            batch.imported_count = len(batch.row_ids.filtered(lambda row: row.state == 'imported'))

    def action_create_drafts(self):
        self.ensure_one()
        if not self.env.user.has_group('paint_tinting.group_tint_formula_manager'):
            raise AccessError(_('Only Tinting Formula Managers can import formula drafts.'))
        if self.state != 'preview':
            raise UserError(_('Only a Preview batch can create formula drafts.'))

        _logger.info(
            "FORMULA_IMPORT_CREATE_DRAFTS_START batch_id=%s rows=%s valid=%s errors=%s duplicates=%s user_id=%s",
            self.id, self.row_count, self.valid_count, self.error_count,
            self.duplicate_count, self.env.user.id,
        )
        service = self.env['tinting.formula.spreadsheet.service']
        imported = 0
        failures = []
        for row in self.row_ids.filtered(lambda item: item.state == 'valid'):
            try:
                with self.env.cr.savepoint():
                    service.create_draft_from_row(row)
                    imported += 1
            except Exception as exc:
                message = str(exc)
                row.write({'state': 'error', 'message': message})
                failures.append(_('Row %(row)s: %(error)s', row=row.row_number, error=message))
                _logger.exception(
                    "FORMULA_IMPORT_ROW_CREATE_FAILED batch_id=%s row_id=%s spreadsheet_row=%s",
                    self.id, row.id, row.row_number,
                )

        remaining_valid = self.row_ids.filtered(lambda item: item.state == 'valid')
        state = 'partial' if failures or remaining_valid else 'imported'
        summary = _(
            'Draft versions created: %(created)s\nDuplicates skipped: %(duplicates)s\nErrors: %(errors)s',
            created=imported,
            duplicates=self.duplicate_count,
            errors=self.error_count,
        )
        if failures:
            summary += '\n' + '\n'.join(failures)
        self.write({'state': state, 'log_summary': summary})
        self.message_post(body=summary.replace('\n', '<br/>'))
        _logger.info(
            "FORMULA_IMPORT_CREATE_DRAFTS_DONE batch_id=%s state=%s imported=%s errors=%s",
            self.id, state, imported, self.error_count,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Imported Draft Formula Versions'),
            'res_model': 'tinting.formula.version',
            'view_mode': 'list,form',
            'domain': [('import_batch_id', '=', self.id)],
        }

    def action_cancel(self):
        for batch in self:
            if batch.state != 'preview':
                raise UserError(_('Only Preview batches can be cancelled.'))
            batch.state = 'cancelled'
            _logger.info("FORMULA_IMPORT_BATCH_CANCELLED batch_id=%s user_id=%s", batch.id, self.env.user.id)


class TintingFormulaImportRow(models.Model):
    _name = 'tinting.formula.import.row'
    _description = 'Tinting Formula Import Staging Row'
    _order = 'batch_id, row_number, id'

    batch_id = fields.Many2one(
        'tinting.formula.import.batch', required=True, ondelete='cascade', index=True,
    )
    row_number = fields.Integer(required=True, readonly=True)
    external_reference = fields.Char(readonly=True)
    fandeck_name = fields.Char(readonly=True)
    colour_code = fields.Char(readonly=True)
    base_category_name = fields.Char(readonly=True)
    base_uom_name = fields.Char(readonly=True)
    base_attribute_name = fields.Char(readonly=True)
    recipe_json = fields.Text(readonly=True)
    recipe_display = fields.Text(compute='_compute_recipe_display')
    change_reason = fields.Text(readonly=True)
    notes = fields.Text(readonly=True)
    state = fields.Selection([
        ('valid', 'Valid'),
        ('duplicate', 'Duplicate'),
        ('error', 'Error'),
        ('imported', 'Draft Created'),
    ], required=True, default='valid', index=True, readonly=True)
    planned_action = fields.Selection([
        ('new_formula', 'New Formula / V1'),
        ('new_version', 'New Version'),
        ('skip', 'Skip'),
        ('none', 'No Action'),
    ], readonly=True)
    message = fields.Text(readonly=True)
    formula_id = fields.Many2one('tinting.formula', readonly=True, ondelete='set null')
    version_id = fields.Many2one('tinting.formula.version', readonly=True, ondelete='set null')

    @api.depends('recipe_json')
    def _compute_recipe_display(self):
        for row in self:
            try:
                recipe = json.loads(row.recipe_json or '{}')
                row.recipe_display = ', '.join('%s=%0.2f' % item for item in sorted(recipe.items()))
            except (TypeError, ValueError):
                row.recipe_display = row.recipe_json or ''
