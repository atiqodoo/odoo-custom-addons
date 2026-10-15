import os

import odoo
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.service import db as service_db


class DbBackupRestoreWizard(models.TransientModel):
    _name = "db.backup.restore.wizard"
    _description = "Restore External Backup to Test Database"

    backup_history_id = fields.Many2one(
        "db.backup.history",
        string="Backup History",
        readonly=True)
    source_backup_path = fields.Char("Source Backup File", required=True)
    target_db_name = fields.Char("Target Database", required=True)
    master_pwd = fields.Char("Master Password", required=True)
    neutralize_database = fields.Boolean(
        "Neutralize Restored Database",
        default=True,
        help="Disable production behavior such as outgoing integrations where Odoo supports neutralization.")
    confirmation_phrase = fields.Char("Confirmation Phrase", required=True)
    expected_confirmation_phrase = fields.Char(
        "Expected Confirmation",
        compute="_compute_expected_confirmation_phrase")
    current_db_name = fields.Char(
        "Current Database",
        default=lambda self: self.env.cr.dbname,
        readonly=True)
    target_filestore_path = fields.Char(
        "Target Filestore Path",
        compute="_compute_environment_mapping")
    addons_path = fields.Char(
        "Addons Path",
        compute="_compute_environment_mapping")
    logfile = fields.Char(
        "Log File",
        compute="_compute_environment_mapping")
    data_dir = fields.Char(
        "Data Directory",
        compute="_compute_environment_mapping")
    database_exists = fields.Boolean(
        "Target Exists",
        compute="_compute_database_exists")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if active_model == "db.backup.history" and active_id:
            history = self.env["db.backup.history"].browse(active_id).exists()
            if history:
                if history.status != "success":
                    raise UserError(_("Only successful backups can be restored."))
                source_path = history._get_existing_backup_path()
                if not source_path:
                    raise UserError(_("Backup file was not found on disk."))
                values.update({
                    "backup_history_id": history.id,
                    "source_backup_path": source_path,
                    "target_db_name": self._default_target_db_name(history),
                })
        return values

    @api.depends("target_db_name")
    def _compute_expected_confirmation_phrase(self):
        for wizard in self:
            wizard.expected_confirmation_phrase = _("RESTORE %s") % (wizard.target_db_name or "")

    @api.depends("target_db_name")
    def _compute_environment_mapping(self):
        for wizard in self:
            target_db_name = (wizard.target_db_name or "").strip()
            wizard.target_filestore_path = odoo.tools.config.filestore(target_db_name) if target_db_name else False
            wizard.addons_path = odoo.tools.config.get("addons_path")
            wizard.logfile = odoo.tools.config.get("logfile")
            wizard.data_dir = odoo.tools.config.get("data_dir")

    @api.depends("target_db_name")
    def _compute_database_exists(self):
        for wizard in self:
            target_db_name = (wizard.target_db_name or "").strip()
            wizard.database_exists = bool(target_db_name and service_db.exp_db_exist(target_db_name))

    def action_restore_backup(self):
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only administrators can restore database backups."))
        expected = self.expected_confirmation_phrase
        if self.confirmation_phrase != expected:
            raise ValidationError(_("Type '%s' to confirm this restore.") % expected)
        log = self.env["db.backup.restore.service"].restore_as_new_database(
            self.source_backup_path,
            self.target_db_name,
            self.master_pwd,
            backup_history=self.backup_history_id,
            neutralize_database=self.neutralize_database,
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Restore Log"),
            "res_model": "db.backup.restore.log",
            "res_id": log.id,
            "view_mode": "form",
            "target": "current",
        }

    def _default_target_db_name(self, history):
        backup_name = os.path.splitext(history.name or "")[0]
        candidate = f"{backup_name}_test"
        return candidate[:63]
