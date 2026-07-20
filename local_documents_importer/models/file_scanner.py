# -*- coding: utf-8 -*-

import logging
import os

from odoo import models

_logger = logging.getLogger(__name__)


class LocalDocumentFileScanner(models.AbstractModel):
    _name = 'local.document.file.scanner'
    _description = 'Local Document File Scanner'

    TEMP_PREFIXES = ('.~', '~$')
    TEMP_SUFFIXES = ('.tmp', '.part', '.crdownload')

    def iter_files(self, watch_path):
        source_root = self.env['local.document.path.validator'].ensure_directory(
            watch_path.source_path,
            'Source Root Path',
        )
        allowed_extensions = watch_path._get_allowed_extensions()
        scanned = yielded = skipped = 0

        if watch_path.recursive:
            walker = os.walk(source_root)
        else:
            walker = [(source_root, [], os.listdir(source_root))]

        for current_root, _dirs, filenames in walker:
            for filename in filenames:
                scanned += 1
                full_path = os.path.join(current_root, filename)
                if not os.path.isfile(full_path):
                    continue
                if self._is_temporary_file(filename):
                    skipped += 1
                    _logger.debug('LDI_SCAN_SKIP_TEMP path=%s', full_path)
                    continue
                extension = os.path.splitext(filename)[1].lower().lstrip('.')
                if allowed_extensions and extension not in allowed_extensions:
                    skipped += 1
                    _logger.debug('LDI_SCAN_SKIP_EXTENSION path=%s extension=%s', full_path, extension)
                    continue
                try:
                    stat = os.stat(full_path)
                except OSError as exc:
                    skipped += 1
                    _logger.warning('LDI_SCAN_STAT_FAILED path=%s error=%s', full_path, exc)
                    continue
                yielded += 1
                yield {
                    'source_path': os.path.normpath(full_path),
                    'root_path': source_root,
                    'relative_folder': self._relative_folder(source_root, current_root),
                    'original_filename': filename,
                    'file_extension': extension,
                    'file_size': stat.st_size,
                    'modified_time': stat.st_mtime,
                }

        _logger.info(
            'LDI_SCAN_COMPLETE watch_id=%s source=%s scanned=%s yielded=%s skipped=%s recursive=%s',
            watch_path.id,
            source_root,
            scanned,
            yielded,
            skipped,
            watch_path.recursive,
        )

    def _is_temporary_file(self, filename):
        lower_name = filename.lower()
        return lower_name.startswith(self.TEMP_PREFIXES) or lower_name.endswith(self.TEMP_SUFFIXES)

    def _relative_folder(self, source_root, current_root):
        relative = os.path.relpath(current_root, source_root)
        if relative == '.':
            return False
        return os.path.normpath(relative)
