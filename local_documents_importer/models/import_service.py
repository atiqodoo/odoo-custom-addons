# -*- coding: utf-8 -*-

import hashlib
import logging
import os
import shutil
import time

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LocalDocumentImportService(models.AbstractModel):
    _name = 'local.document.import.service'
    _description = 'Local Document Import Service'

    def run_all_enabled(self):
        watch_paths = self.env['local.document.watch.path'].search([('active', '=', True)])
        _logger.info('LDI_CRON_START enabled_watch_paths=%s', len(watch_paths))
        totals = {'seen': 0, 'imported': 0, 'skipped': 0, 'errors': 0}
        for watch_path in watch_paths:
            result = self.run_watch_path(watch_path)
            for key in totals:
                totals[key] += result.get(key, 0)
        _logger.info('LDI_CRON_DONE totals=%s', totals)
        return totals

    def run_watch_path(self, watch_path):
        watch_path.ensure_one()
        _logger.info(
            'LDI_WATCH_START watch_id=%s name=%s source=%s target_folder_id=%s batch_limit=%s',
            watch_path.id,
            watch_path.display_name,
            watch_path.source_path,
            watch_path.target_folder_id.id,
            watch_path.batch_limit,
        )
        result = {'seen': 0, 'imported': 0, 'skipped': 0, 'errors': 0}
        processed = 0

        for file_info in self.env['local.document.file.scanner'].iter_files(watch_path):
            result['seen'] += 1
            if processed >= watch_path.batch_limit:
                _logger.info(
                    'LDI_BATCH_LIMIT_REACHED watch_id=%s limit=%s seen=%s',
                    watch_path.id,
                    watch_path.batch_limit,
                    result['seen'],
                )
                break

            log = self._prepare_log(watch_path, file_info)
            if log.state == 'imported':
                result['skipped'] += 1
                _logger.debug('LDI_SKIP_IMPORTED log_id=%s path=%s', log.id, log.source_path)
                continue

            try:
                decision = self._process_log(watch_path, log, file_info)
            except Exception as exc:
                result['errors'] += 1
                self.env.cr.rollback()
                log = self.env['local.document.import.log'].search([('source_path', '=', file_info['source_path'])], limit=1)
                if log:
                    log.sudo().write({
                        'state': 'error',
                        'error_message': str(exc),
                        'last_seen_date': fields.Datetime.now(),
                    })
                _logger.exception(
                    'LDI_IMPORT_EXCEPTION watch_id=%s log_id=%s path=%s error=%s',
                    watch_path.id,
                    log.id if log else False,
                    file_info['source_path'],
                    exc,
                )
                continue

            if decision == 'imported':
                processed += 1
                result['imported'] += 1
            else:
                result['skipped'] += 1

        watch_path.sudo().write({'last_scan_date': fields.Datetime.now()})
        _logger.info('LDI_WATCH_DONE watch_id=%s result=%s', watch_path.id, result)
        return result

    def _prepare_log(self, watch_path, file_info):
        Log = self.env['local.document.import.log'].sudo()
        log = Log.search([('source_path', '=', file_info['source_path'])], limit=1)
        vals = {
            'watch_path_id': watch_path.id,
            'relative_folder': file_info['relative_folder'],
            'original_filename': file_info['original_filename'],
            'file_extension': file_info['file_extension'],
            'file_size': file_info['file_size'],
            'modified_time': file_info['modified_time'],
            'last_seen_date': fields.Datetime.now(),
        }
        if log:
            if log.file_size != file_info['file_size'] or log.modified_time != file_info['modified_time']:
                vals.update({
                    'state': 'pending',
                    'checksum': False,
                    'error_message': False,
                    'debug_note': 'File metadata changed; waiting for stability before import.',
                })
            log.write(vals)
            return log
        vals.update({
            'source_path': file_info['source_path'],
            'state': 'pending',
            'debug_note': 'First seen; waiting for stability before import.',
        })
        log = Log.create(vals)
        _logger.info('LDI_LOG_CREATED watch_id=%s log_id=%s path=%s', watch_path.id, log.id, log.source_path)
        return log

    def _process_log(self, watch_path, log, file_info):
        if not self.env['local.document.path.validator'].ensure_file_under_root(
            watch_path.source_path,
            file_info['source_path'],
        ):
            raise UserError('Source file is outside configured root path.')

        max_bytes = watch_path.max_file_size_mb * 1024 * 1024
        if max_bytes and file_info['file_size'] > max_bytes:
            log.sudo().write({
                'state': 'skipped',
                'debug_note': 'File exceeded configured maximum size.',
            })
            _logger.warning(
                'LDI_SKIP_SIZE watch_id=%s log_id=%s path=%s size=%s max_bytes=%s',
                watch_path.id,
                log.id,
                file_info['source_path'],
                file_info['file_size'],
                max_bytes,
            )
            return 'skipped'

        age_seconds = max(0, time.time() - file_info['modified_time'])
        if age_seconds < watch_path.min_age_seconds:
            log.sudo().write({'debug_note': 'File is too new; waiting before import.'})
            _logger.debug(
                'LDI_WAIT_MIN_AGE watch_id=%s log_id=%s path=%s age=%.2f required=%s',
                watch_path.id,
                log.id,
                file_info['source_path'],
                age_seconds,
                watch_path.min_age_seconds,
            )
            return 'skipped'

        checksum = self._file_checksum(file_info['source_path'])
        duplicate = self.env['local.document.import.log'].sudo().search(
            [
                ('id', '!=', log.id),
                ('checksum', '=', checksum),
                ('state', '=', 'imported'),
                ('watch_path_id', '=', watch_path.id),
            ],
            limit=1,
        )
        if duplicate and watch_path.duplicate_policy == 'skip':
            log.sudo().write({
                'state': 'skipped',
                'checksum': checksum,
                'debug_note': 'Skipped because checksum already exists in this watch path.',
            })
            _logger.info(
                'LDI_SKIP_DUPLICATE watch_id=%s log_id=%s duplicate_log_id=%s checksum=%s path=%s',
                watch_path.id,
                log.id,
                duplicate.id,
                checksum,
                file_info['source_path'],
            )
            return 'skipped'

        folder = self.env['local.document.folder.resolver'].resolve_folder(watch_path, file_info['relative_folder'])
        document = self._create_document(watch_path, folder, file_info)
        log.sudo().write({
            'state': 'imported',
            'checksum': checksum,
            'document_id': document.id,
            'folder_id': folder.id,
            'imported_date': fields.Datetime.now(),
            'error_message': False,
            'debug_note': 'Imported successfully.',
        })
        self._handle_source_after_import(watch_path, file_info, log)
        _logger.info(
            'LDI_IMPORTED watch_id=%s log_id=%s document_id=%s folder_id=%s path=%s size=%s checksum=%s',
            watch_path.id,
            log.id,
            document.id,
            folder.id,
            file_info['source_path'],
            file_info['file_size'],
            checksum,
        )
        return 'imported'

    def _create_document(self, watch_path, folder, file_info):
        with open(file_info['source_path'], 'rb') as source_file:
            raw = source_file.read()
        document = self.env['documents.document'].sudo().create({
            'name': file_info['original_filename'],
            'folder_id': folder.id,
            'owner_id': watch_path.owner_id.id,
            'company_id': watch_path.company_id.id if watch_path.company_id else False,
            'raw': raw,
        })
        return document

    def _file_checksum(self, path):
        digest = hashlib.sha256()
        with open(path, 'rb') as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def _handle_source_after_import(self, watch_path, file_info, log):
        if watch_path.post_import_action == 'keep':
            return
        if watch_path.post_import_action == 'delete':
            os.remove(file_info['source_path'])
            _logger.info('LDI_SOURCE_DELETED watch_id=%s log_id=%s path=%s', watch_path.id, log.id, file_info['source_path'])
            return
        archive_root = self.env['local.document.path.validator'].ensure_directory(
            watch_path.archive_path,
            'Archive Path',
        )
        relative_folder = file_info['relative_folder'] or ''
        destination_dir = os.path.join(archive_root, relative_folder)
        os.makedirs(destination_dir, exist_ok=True)
        destination = self._unique_destination(destination_dir, file_info['original_filename'])
        shutil.move(file_info['source_path'], destination)
        _logger.info(
            'LDI_SOURCE_ARCHIVED watch_id=%s log_id=%s from=%s to=%s',
            watch_path.id,
            log.id,
            file_info['source_path'],
            destination,
        )

    def _unique_destination(self, destination_dir, filename):
        base, extension = os.path.splitext(filename)
        destination = os.path.join(destination_dir, filename)
        counter = 1
        while os.path.exists(destination):
            destination = os.path.join(destination_dir, '%s_%s%s' % (base, counter, extension))
            counter += 1
        return destination
