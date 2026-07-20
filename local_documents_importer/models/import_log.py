# -*- coding: utf-8 -*-

from odoo import fields, models


class LocalDocumentImportLog(models.Model):
    _name = 'local.document.import.log'
    _description = 'Local Document Import Log'
    _order = 'last_seen_date desc, id desc'
    _rec_name = 'source_path'

    watch_path_id = fields.Many2one(
        'local.document.watch.path',
        string='Watch Path',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(related='watch_path_id.company_id', store=True, readonly=True)
    source_path = fields.Char(required=True, index=True)
    relative_folder = fields.Char(index=True)
    original_filename = fields.Char(required=True, index=True)
    file_extension = fields.Char(index=True)
    file_size = fields.Integer(index=True)
    modified_time = fields.Float(index=True)
    checksum = fields.Char(index=True)
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('imported', 'Imported'),
            ('skipped', 'Skipped'),
            ('error', 'Error'),
        ],
        default='pending',
        required=True,
        index=True,
    )
    document_id = fields.Many2one('documents.document', string='Odoo Document', ondelete='set null')
    folder_id = fields.Many2one('documents.document', string='Odoo Folder', ondelete='set null')
    first_seen_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    last_seen_date = fields.Datetime(default=fields.Datetime.now)
    imported_date = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True)
    debug_note = fields.Text(readonly=True)

    _sql_constraints = [
        (
            'source_path_unique',
            'unique(source_path)',
            'Each source file path can only have one import log.',
        ),
    ]

    def action_open_document(self):
        self.ensure_one()
        if not self.document_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': self.document_id.display_name,
            'res_model': 'documents.document',
            'res_id': self.document_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
