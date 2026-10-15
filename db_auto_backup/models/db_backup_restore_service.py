import logging
import os
import re
import time

import odoo
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.service import db as service_db

_logger = logging.getLogger(__name__)


class DbBackupRestoreService(models.AbstractModel):
    _name = "db.backup.restore.service"
    _description = "Database Backup Restore Service"

    _DB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")

    @api.model
    def restore_as_new_database(self, source_backup_path, target_db_name,
                                master_pwd, backup_history=False,
                                neutralize_database=True):
        """Restore a local backup file into a new database only."""
        self._check_restore_access()
        source_backup_path = self._normalize_source_path(source_backup_path)
        target_db_name = self._normalize_target_db_name(target_db_name)
        self._validate_restore_request(source_backup_path, target_db_name, master_pwd)

        started_at = fields.Datetime.now()
        started_monotonic = time.monotonic()
        log = self.env["db.backup.restore.log"].create({
            "name": _("Restore %s") % target_db_name,
            "backup_history_id": backup_history.id if backup_history else False,
            "backup_config_id": backup_history.backup_config_id.id if backup_history and backup_history.backup_config_id else False,
            "source_backup_path": source_backup_path,
            "target_db_name": target_db_name,
            "restore_date": started_at,
            "status": "pending",
            "restore_mode": "new_database",
            "neutralize_database": neutralize_database,
            "target_filestore_path": odoo.tools.config.filestore(target_db_name),
            "addons_path": odoo.tools.config.get("addons_path"),
            "logfile": odoo.tools.config.get("logfile"),
        })

        _logger.info(
            "[DB_AUTO_BACKUP][RESTORE][START] restore_log_id=%s backup_history_id=%s target_db=%s user_id=%s neutralize=%s",
            log.id, backup_history.id if backup_history else False, target_db_name,
            self.env.user.id, neutralize_database)
        try:
            service_db.restore_db(
                target_db_name,
                source_backup_path,
                copy=True,
                neutralize_database=neutralize_database,
            )
        except Exception as error:
            duration = time.monotonic() - started_monotonic
            safe_error = str(error)
            log.write({
                "status": "failed",
                "duration": duration,
                "error_message": safe_error,
            })
            _logger.exception(
                "[DB_AUTO_BACKUP][RESTORE][ERROR] restore_log_id=%s backup_history_id=%s target_db=%s error=%s",
                log.id, backup_history.id if backup_history else False, target_db_name, safe_error)
            raise UserError(_("Database restore failed: %s") % safe_error) from error

        log.check_restore_integrity()
        duration = time.monotonic() - started_monotonic
        log.write({
            "status": "success",
            "duration": duration,
        })
        _logger.info(
            "[DB_AUTO_BACKUP][RESTORE][END] restore_log_id=%s backup_history_id=%s target_db=%s duration=%s",
            log.id, backup_history.id if backup_history else False, target_db_name, duration)
        return log

    def _check_restore_access(self):
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only administrators can restore database backups."))

    def _normalize_source_path(self, source_backup_path):
        return os.path.abspath(os.path.expanduser((source_backup_path or "").strip()))

    def _normalize_target_db_name(self, target_db_name):
        return (target_db_name or "").strip()

    def _validate_restore_request(self, source_backup_path, target_db_name, master_pwd):
        if not source_backup_path:
            raise ValidationError(_("Please choose a source backup file."))
        if not os.path.isfile(source_backup_path):
            raise ValidationError(_("Source backup file was not found."))
        if not target_db_name:
            raise ValidationError(_("Please enter a target database name."))
        if not self._DB_NAME_PATTERN.match(target_db_name):
            raise ValidationError(_("Database name can only contain letters, numbers, dots, underscores, and hyphens."))
        if target_db_name == self.env.cr.dbname:
            raise ValidationError(_("Restore must use a new database name, not the current database."))
        if service_db.exp_db_exist(target_db_name):
            raise ValidationError(_("Target database already exists. Choose a new database name."))
        try:
            service_db.check_super(master_pwd)
        except Exception as error:
            raise ValidationError(_("Invalid master password.")) from error
