# -*- coding: utf-8 -*-

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class LocalDocumentWatchPath(models.Model):
    _name = 'local.document.watch.path'
    _description = 'Local Document Watch Path'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    source_path = fields.Char(required=True, help='Local Windows folder watched by this rule.')
    target_folder_id = fields.Many2one(
        'documents.document',
        string='Target Documents Folder',
        required=True,
        domain="[('type', '=', 'folder'), ('shortcut_document_id', '=', False)]",
    )
    recursive = fields.Boolean(default=True)
    auto_create_folders = fields.Boolean(default=True)
    allowed_extensions = fields.Char(
        default='pdf,jpg,jpeg,png,doc,docx,xls,xlsx,csv,txt',
        help='Comma-separated list without dots. Leave empty to allow all files.',
    )
    duplicate_policy = fields.Selection(
        [
            ('skip', 'Skip same checksum'),
            ('import', 'Import duplicate checksum'),
        ],
        default='skip',
        required=True,
    )
    post_import_action = fields.Selection(
        [
            ('keep', 'Keep Source File'),
            ('archive', 'Move to Archive'),
            ('delete', 'Delete Source File'),
        ],
        default='archive',
        required=True,
    )
    archive_path = fields.Char(help='Required when post-import action is Move to Archive.')
    batch_limit = fields.Integer(default=30, required=True)
    min_age_seconds = fields.Integer(default=20, required=True)
    max_file_size_mb = fields.Integer(default=100, required=True)
    owner_id = fields.Many2one('res.users', default=lambda self: self.env.user, required=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    last_scan_date = fields.Datetime(readonly=True)
    log_ids = fields.One2many('local.document.import.log', 'watch_path_id')
    log_count = fields.Integer(compute='_compute_log_count')
    imported_count = fields.Integer(compute='_compute_log_count')
    error_count = fields.Integer(compute='_compute_log_count')
    pending_count = fields.Integer(compute='_compute_log_count')

    @api.depends('log_ids.state')
    def _compute_log_count(self):
        grouped = self.env['local.document.import.log'].read_group(
            [('watch_path_id', 'in', self.ids)],
            ['watch_path_id', 'state'],
            ['watch_path_id', 'state'],
            lazy=False,
        )
        counts = {}
        for row in grouped:
            watch_id = row['watch_path_id'][0]
            state = row['state']
            counts.setdefault(watch_id, {}).setdefault(state, 0)
            counts[watch_id][state] += row['__count']
        for watch_path in self:
            state_counts = counts.get(watch_path.id, {})
            watch_path.imported_count = state_counts.get('imported', 0)
            watch_path.error_count = state_counts.get('error', 0)
            watch_path.pending_count = state_counts.get('pending', 0)
            watch_path.log_count = sum(state_counts.values())

    @api.constrains('source_path', 'archive_path', 'post_import_action', 'batch_limit', 'min_age_seconds', 'max_file_size_mb')
    def _check_configuration(self):
        validator = self.env['local.document.path.validator']
        for watch_path in self:
            validator.ensure_directory(watch_path.source_path, 'Source Root Path')
            if watch_path.post_import_action == 'archive':
                validator.ensure_directory(watch_path.archive_path, 'Archive Path')
            if watch_path.batch_limit <= 0:
                raise ValidationError(_('Batch limit must be greater than zero.'))
            if watch_path.min_age_seconds < 0:
                raise ValidationError(_('Minimum file age cannot be negative.'))
            if watch_path.max_file_size_mb < 0:
                raise ValidationError(_('Maximum file size cannot be negative.'))

    def _get_allowed_extensions(self):
        self.ensure_one()
        if not self.allowed_extensions:
            return set()
        return {
            extension.strip().lower().lstrip('.')
            for extension in self.allowed_extensions.split(',')
            if extension.strip()
        }

    def action_scan_now(self):
        for watch_path in self:
            _logger.info('LDI_MANUAL_SCAN_REQUEST watch_id=%s user_id=%s', watch_path.id, self.env.user.id)
            self.env['local.document.import.service'].run_watch_path(watch_path)
        return True

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Logs'),
            'res_model': 'local.document.import.log',
            'view_mode': 'list,form',
            'domain': [('watch_path_id', '=', self.id)],
            'context': {'default_watch_path_id': self.id},
        }
