import logging
import os

import odoo
from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DbBackupRestoreLog(models.Model):
    _name = "db.backup.restore.log"
    _description = "Database Backup Restore Log"
    _order = "restore_date desc"

    name = fields.Char("Reference", required=True)
    backup_history_id = fields.Many2one(
        "db.backup.history",
        string="Backup History",
        readonly=True,
        ondelete="set null")
    backup_config_id = fields.Many2one(
        "db.backup.configure",
        string="Backup Configuration",
        readonly=True,
        ondelete="set null")
    source_backup_path = fields.Char("Source Backup Path", readonly=True)
    target_db_name = fields.Char("Target Database", required=True, readonly=True)
    restore_date = fields.Datetime("Restore Date", default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one(
        "res.users",
        string="Restored By",
        default=lambda self: self.env.user,
        readonly=True)
    status = fields.Selection([
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    ], default="pending", required=True, readonly=True)
    restore_mode = fields.Selection([
        ("new_database", "New Database"),
    ], default="new_database", required=True, readonly=True)
    neutralize_database = fields.Boolean("Neutralized", readonly=True)
    duration = fields.Float("Duration (Seconds)", readonly=True)
    target_filestore_path = fields.Char("Target Filestore Path", readonly=True)
    addons_path = fields.Char("Addons Path", readonly=True)
    logfile = fields.Char("Log File", readonly=True)
    error_message = fields.Text("Error", readonly=True)
    integrity_status = fields.Selection([
        ("not_checked", "Not Checked"),
        ("passed", "Passed"),
        ("warning", "Warning"),
        ("failed", "Failed"),
    ], string="Integrity Status", default="not_checked", required=True, readonly=True)
    expected_filestore_files = fields.Integer("Expected Filestore Files", readonly=True)
    restored_filestore_files = fields.Integer("Restored Filestore Files", readonly=True)
    missing_filestore_files = fields.Integer("Missing Filestore Files", readonly=True)
    missing_filestore_sample = fields.Text("Missing Filestore Sample", readonly=True)

    def action_open_target_database(self):
        self.ensure_one()
        if self.status != "success":
            raise UserError(_("Only successful restores can be opened."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/login?db={self.target_db_name}",
            "target": "new",
        }

    def action_open_backup_history(self):
        self.ensure_one()
        if not self.backup_history_id:
            raise UserError(_("This restore log is not linked to a backup history record."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "db.backup.history",
            "res_id": self.backup_history_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def check_restore_integrity(self):
        """Compare restored database attachment rows with the target filestore."""
        for log in self:
            log._check_restore_integrity()

    def _check_restore_integrity(self):
        self.ensure_one()
        _logger.info(
            "[DB_AUTO_BACKUP][RESTORE_INTEGRITY][START] restore_log_id=%s target_db=%s filestore=%s",
            self.id, self.target_db_name, self.target_filestore_path)
        if not self.target_db_name:
            self.write({"integrity_status": "not_checked"})
            _logger.info(
                "[DB_AUTO_BACKUP][RESTORE_INTEGRITY][END] restore_log_id=%s status=not_checked reason=no_target_db",
                self.id)
            return
        try:
            expected_files = self._get_target_db_store_fnames()
            restored_files = self._get_restored_filestore_fnames()
            missing_files = sorted(expected_files - restored_files)
            integrity_status = "passed" if not missing_files else "warning"
            sample = "\n".join(missing_files[:20]) if missing_files else False
            self.write({
                "integrity_status": integrity_status,
                "expected_filestore_files": len(expected_files),
                "restored_filestore_files": len(restored_files),
                "missing_filestore_files": len(missing_files),
                "missing_filestore_sample": sample,
            })
            _logger.info(
                "[DB_AUTO_BACKUP][RESTORE_INTEGRITY][END] restore_log_id=%s expected=%s actual=%s missing=%s status=%s",
                self.id, len(expected_files), len(restored_files), len(missing_files), integrity_status)
        except Exception as error:
            self.write({
                "integrity_status": "failed",
                "missing_filestore_sample": str(error),
            })
            _logger.exception(
                "[DB_AUTO_BACKUP][RESTORE_INTEGRITY][ERROR] restore_log_id=%s target_db=%s error=%s",
                self.id, self.target_db_name, error)

    def _get_target_db_store_fnames(self):
        target_db = odoo.sql_db.db_connect(self.target_db_name)
        with target_db.cursor() as cr:
            cr.execute("""
                SELECT DISTINCT store_fname
                  FROM ir_attachment
                 WHERE store_fname IS NOT NULL
            """)
            return {
                store_fname.replace("\\", "/")
                for (store_fname,) in cr.fetchall()
                if store_fname
            }

    def _get_restored_filestore_fnames(self):
        filestore_path = self.target_filestore_path or odoo.tools.config.filestore(self.target_db_name)
        if not os.path.isdir(filestore_path):
            return set()
        restored_files = set()
        for root, _, filenames in os.walk(filestore_path):
            for filename in filenames:
                path = os.path.join(root, filename)
                restored_files.add(os.path.relpath(path, filestore_path).replace("\\", "/"))
        return restored_files
