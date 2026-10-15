import logging
import os
import zipfile

import odoo
from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DbBackupHistory(models.Model):
    _name = "db.backup.history"
    _description = "Database Backup History"
    _order = "backup_date desc"

    name = fields.Char("File Name", required=True)
    backup_config_id = fields.Many2one(
        "db.backup.configure",
        string="Backup Configuration",
        readonly=True,
        index=True,
        ondelete="set null")
    backup_path = fields.Char("Staging Path")
    offsite_backup_path = fields.Char("Offsite Backup Path")
    backup_date = fields.Datetime("Backup Date", default=fields.Datetime.now)
    backup_format = fields.Selection([
        ('zip', 'Zip'),
        ('dump', 'Dump'),
    ], string="Backup Format", readonly=True)
    run_type = fields.Selection([
        ('automatic', 'Automatic'),
        ('manual', 'Manual'),
    ], string="Run Type", default='automatic', required=True, readonly=True)
    status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], default='success', required=True, readonly=True)
    file_size_bytes = fields.Integer("File Size (Bytes)", readonly=True)
    file_size = fields.Char("File Size", readonly=True)
    error_message = fields.Text("Error", readonly=True)
    integrity_status = fields.Selection([
        ('not_checked', 'Not Checked'),
        ('passed', 'Passed'),
        ('warning', 'Warning'),
        ('failed', 'Failed'),
    ], string="Integrity Status", default='not_checked', required=True, readonly=True)
    expected_filestore_files = fields.Integer("Expected Filestore Files", readonly=True)
    backup_filestore_files = fields.Integer("Backup Filestore Files", readonly=True)
    missing_filestore_files = fields.Integer("Missing Filestore Files", readonly=True)
    missing_filestore_sample = fields.Text("Missing Filestore Sample", readonly=True)

    def action_download_file(self):
        """Download backup from local/offsite filesystem storage."""
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only administrators can download database backups."))
        if not self._get_existing_backup_path():
            raise UserError(_("Backup file was not found on disk."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/db_auto_backup/download/{self.id}",
            "target": "self",
        }

    def action_restore_to_test_database(self):
        """Open an admin-only wizard to restore this backup as a new database."""
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only administrators can restore database backups."))
        if self.status != 'success':
            raise UserError(_("Only successful backups can be restored."))
        if not self._get_existing_backup_path():
            raise UserError(_("Backup file was not found on disk."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Restore to Test Database"),
            "res_model": "db.backup.restore.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "active_model": self._name,
                "active_id": self.id,
            },
        }

    def action_delete_file(self):
        """Delete backup files from disk and remove metadata."""
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only administrators can delete database backups."))
        for path in [self.backup_path, self.offsite_backup_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    _logger.info(
                        '[DB_AUTO_BACKUP][HISTORY_DELETE][FILE_REMOVED] history_id=%s path=%s',
                        self.id, path)
                except OSError as error:
                    _logger.exception(
                        '[DB_AUTO_BACKUP][HISTORY_DELETE][ERROR] history_id=%s path=%s error=%s',
                        self.id, path, error)
                    raise UserError(_("Could not delete backup file: %s") % error) from error
        self.unlink()

    def action_check_backup_integrity(self):
        """Re-run filestore integrity check for a backup file."""
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only administrators can check backup integrity."))
        self.check_backup_integrity()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Integrity Check Complete'),
                'message': _('Backup integrity check finished.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def check_backup_integrity(self):
        """Compare current database filestore references with files inside the zip."""
        for history in self:
            history._check_backup_integrity()

    def _check_backup_integrity(self):
        self.ensure_one()
        backup_path = self._get_existing_backup_path()
        source_db_name = self.backup_config_id.db_name or self.env.cr.dbname
        _logger.info(
            '[DB_AUTO_BACKUP][BACKUP_INTEGRITY][START] history_id=%s db=%s path=%s',
            self.id, source_db_name, backup_path)
        if self.status != 'success' or self.backup_format != 'zip' or not backup_path:
            self.write({
                'integrity_status': 'not_checked',
                'expected_filestore_files': 0,
                'backup_filestore_files': 0,
                'missing_filestore_files': 0,
                'missing_filestore_sample': False,
            })
            _logger.info(
                '[DB_AUTO_BACKUP][BACKUP_INTEGRITY][END] history_id=%s status=not_checked reason=not_zip_success',
                self.id)
            return

        try:
            expected_files = self._get_source_db_store_fnames(source_db_name)
            backup_files = self._get_zip_filestore_fnames(backup_path)
            missing_files = sorted(expected_files - backup_files)
            integrity_status = 'passed' if not missing_files else 'warning'
            sample = '\n'.join(missing_files[:20]) if missing_files else False
            self.write({
                'integrity_status': integrity_status,
                'expected_filestore_files': len(expected_files),
                'backup_filestore_files': len(backup_files),
                'missing_filestore_files': len(missing_files),
                'missing_filestore_sample': sample,
            })
            _logger.info(
                '[DB_AUTO_BACKUP][BACKUP_INTEGRITY][END] history_id=%s expected=%s actual=%s missing=%s status=%s',
                self.id, len(expected_files), len(backup_files), len(missing_files), integrity_status)
        except Exception as error:
            self.write({
                'integrity_status': 'failed',
                'missing_filestore_sample': str(error),
            })
            _logger.exception(
                '[DB_AUTO_BACKUP][BACKUP_INTEGRITY][ERROR] history_id=%s error=%s',
                self.id, error)

    def _get_source_db_store_fnames(self, source_db_name):
        source_db = odoo.sql_db.db_connect(source_db_name)
        with source_db.cursor() as cr:
            cr.execute("""
                SELECT DISTINCT store_fname
                  FROM ir_attachment
                 WHERE store_fname IS NOT NULL
            """)
            return {
                store_fname.replace('\\', '/')
                for (store_fname,) in cr.fetchall()
                if store_fname
            }

    def _get_zip_filestore_fnames(self, backup_path):
        filestore_files = set()
        with zipfile.ZipFile(backup_path) as backup_zip:
            for filename in backup_zip.namelist():
                normalized = filename.replace('\\', '/')
                if normalized.startswith('filestore/') and not normalized.endswith('/'):
                    filestore_files.add(normalized[len('filestore/'):])
        return filestore_files

    def _get_existing_backup_path(self):
        self.ensure_one()
        for path in [self.backup_path, self.offsite_backup_path]:
            if path and os.path.isfile(path):
                return path
        return False
