# -*- coding: utf-8 -*-

import logging
import os

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LocalDocumentFolderResolver(models.AbstractModel):
    _name = 'local.document.folder.resolver'
    _description = 'Local Document Folder Resolver'

    def resolve_folder(self, watch_path, relative_folder):
        target_folder = watch_path.target_folder_id
        if not target_folder or target_folder.type != 'folder':
            raise UserError(_('Target Odoo folder is required and must be a Documents folder.'))

        if not relative_folder:
            return target_folder

        current_folder = target_folder
        for raw_segment in self._split_relative_folder(relative_folder):
            segment = self._sanitize_segment(raw_segment)
            existing = self.env['documents.document'].with_context(active_test=False).search(
                [
                    ('type', '=', 'folder'),
                    ('folder_id', '=', current_folder.id),
                    ('name', '=', segment),
                    ('shortcut_document_id', '=', False),
                ],
                limit=1,
            )
            if existing:
                current_folder = existing
                continue
            if not watch_path.auto_create_folders:
                raise UserError(_('Odoo subfolder does not exist and auto-create is disabled: %s') % segment)
            current_folder = self.env['documents.document'].sudo().create({
                'name': segment,
                'type': 'folder',
                'folder_id': current_folder.id,
                'owner_id': watch_path.owner_id.id,
                'company_id': watch_path.company_id.id if watch_path.company_id else False,
            })
            _logger.info(
                'LDI_FOLDER_CREATED watch_id=%s folder_id=%s parent_id=%s name=%s relative=%s',
                watch_path.id,
                current_folder.id,
                current_folder.folder_id.id,
                segment,
                relative_folder,
            )
        return current_folder

    def _split_relative_folder(self, relative_folder):
        parts = []
        normalized = os.path.normpath(relative_folder)
        for segment in normalized.split(os.sep):
            if segment and segment not in ('.', '..'):
                parts.append(segment)
        return parts

    def _sanitize_segment(self, segment):
        clean = segment.strip()
        if not clean:
            raise UserError(_('Local folder names cannot be empty.'))
        return clean[:255]
