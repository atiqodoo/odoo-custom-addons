import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import timedelta

import odoo
import pytz
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import find_pg_tool, exec_pg_environ
from odoo.service import db

_logger = logging.getLogger(__name__)


class DbBackupConfigure(models.Model):
    _name = 'db.backup.configure'
    _description = 'Automatic Database Backup'

    name = fields.Char(string='Name', required=True, help='Add the name')
    db_name = fields.Char(string='Database Name', required=True,
                          help='Name of the database')
    master_pwd = fields.Char(string='Master Password', required=True,
                             help='Master password')
    backup_format = fields.Selection([
        ('zip', 'Zip'),
        ('dump', 'Dump')
    ], string='Backup Format', default='zip', required=True,
        help='Format of the backup')
    backup_frequency = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ], default='daily', string='Backup Frequency', help='Frequency of Backup Scheduling')
    backup_start_time = fields.Float(
        string='Backup Start Time',
        default=2.0,
        help='Local time when the scheduled backup should start.')
    backup_start_time_display = fields.Char(
        string='Clock Time (AM/PM)',
        compute='_compute_backup_start_time_display',
        help='Readable local backup start time.')
    weekly_start_date = fields.Date(
        string='Weekly Start Date',
        default=fields.Date.context_today,
        help='First date for weekly backups. Future weekly runs repeat from this date at the configured time.')
    include_filestore = fields.Boolean(
        string='Include Filestore',
        default=True,
        help='Include Odoo attachments/documents in zip backups.')
    backup_path = fields.Char(
        string='Staging Path',
        help='Local staging directory where Odoo creates the completed backup first.')
    copy_to_offsite = fields.Boolean(
        string='Copy to Offsite Folder',
        default=True,
        help='Copy the completed backup to a synced/offsite folder after staging finishes.')
    offsite_backup_path = fields.Char(
        string='Offsite Backup Path',
        help='Synced folder path, for example a Google Drive for desktop folder.')

    active = fields.Boolean(default=False, string='Active',
                            help='Activate the Scheduled Action or not')
    auto_remove = fields.Boolean(string='Remove Old Backups',
                                 help='Remove old backups')
    days_to_remove = fields.Integer(string='Remove After',
                                    help='Automatically delete stored backups'
                                         ' after this specified number of days')
    retention_min_backups = fields.Integer(
        string='Minimum Backups to Keep',
        default=3,
        help='Always keep this many newest backups even when they are older than the retention period.')
    notify_user = fields.Boolean(string='Notify User',
                                 help='Send an email notification to user when'
                                      'the backup operation is successful'
                                      'or failed')
    user_id = fields.Many2one('res.users', string='User',
                              help='Name of the user')
    backup_filename = fields.Char(string='Backup Filename',
                                  help='For Storing generated backup filename')
    generated_exception = fields.Text(string='Last Error', readonly=True,
                                      help='Last backup error message')
    backup_history_ids = fields.One2many(
        'db.backup.history',
        'backup_config_id',
        string='Backup Logs',
        readonly=True)
    restore_log_ids = fields.One2many(
        'db.backup.restore.log',
        'backup_config_id',
        string='Restore Logs',
        readonly=True)
    last_backup_status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], string='Last Backup Status', compute='_compute_last_backup_result')
    last_backup_date = fields.Datetime(
        string='Last Backup Date',
        compute='_compute_last_backup_result')
    last_backup_error = fields.Text(
        string='Last Backup Error',
        compute='_compute_last_backup_result')

    @api.depends('backup_start_time')
    def _compute_backup_start_time_display(self):
        for rec in self:
            total_minutes = int(round((rec.backup_start_time or 0.0) * 60))
            total_minutes = max(0, min(total_minutes, (24 * 60) - 1))
            hour, minute = divmod(total_minutes, 60)
            period = 'AM' if hour < 12 else 'PM'
            hour_12 = hour % 12 or 12
            rec.backup_start_time_display = f'{hour_12:02d}:{minute:02d} {period}'

    @api.depends('backup_history_ids.status', 'backup_history_ids.backup_date',
                 'backup_history_ids.error_message')
    def _compute_last_backup_result(self):
        for rec in self:
            latest = rec.backup_history_ids[:1]
            rec.last_backup_status = latest.status if latest else False
            rec.last_backup_date = latest.backup_date if latest else False
            rec.last_backup_error = latest.error_message if latest else False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_backup_cron_start_time()
        return records

    def write(self, vals):
        old_frequencies = set(self.mapped('backup_frequency'))
        result = super().write(vals)
        if {'backup_frequency', 'backup_start_time', 'weekly_start_date', 'active'} & set(vals):
            frequencies = old_frequencies | set(self.mapped('backup_frequency'))
            self._sync_backup_cron_start_time(frequencies=frequencies)
        return result


    @api.constrains('backup_frequency', 'weekly_start_date', 'active')
    def _check_weekly_start_date(self):
        for rec in self:
            if rec.active and rec.backup_frequency == 'weekly' and not rec.weekly_start_date:
                raise ValidationError(_("Please choose a weekly start date."))

    @api.constrains('db_name')
    def _check_db_credentials(self):
        """Validate entered database name and master password"""
        database_list = db.list_dbs(force=True)
        if self.db_name not in database_list:
            raise ValidationError(_("Invalid Database Name!"))
        try:
            odoo.service.db.check_super(self.master_pwd)
        except Exception:
            raise ValidationError(_("Invalid Master Password!"))

    def _get_backup_cron(self, frequency):
        return self.env.ref(
            f'db_auto_backup.ir_cron_auto_db_backup_{frequency}',
            raise_if_not_found=False,
        )

    def _cron_nextcall_from_start_time(self, cron, start_time):
        """Return the next cron run in UTC for a user-facing local time."""
        timezone_name = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(timezone_name)
        now_utc = fields.Datetime.now()
        now_local = pytz.utc.localize(now_utc).astimezone(user_tz)

        total_minutes = int(round((start_time or 0.0) * 60))
        total_minutes = max(0, min(total_minutes, (24 * 60) - 1))
        hour, minute = divmod(total_minutes, 60)
        candidate_local = now_local.replace(
            hour=hour, minute=minute, second=0, microsecond=0)

        interval_type = cron.interval_type
        while candidate_local <= now_local:
            if interval_type == 'weeks':
                candidate_local += timedelta(weeks=cron.interval_number or 1)
            elif interval_type == 'months':
                candidate_local += relativedelta(months=cron.interval_number or 1)
            else:
                candidate_local += timedelta(days=cron.interval_number or 1)

        return fields.Datetime.to_string(candidate_local.astimezone(pytz.utc).replace(tzinfo=None))

    def _cron_nextcall_from_config(self, cron, config):
        """Return the next cron run in UTC from one backup configuration."""
        if config.backup_frequency != 'weekly' or not config.weekly_start_date:
            return self._cron_nextcall_from_start_time(cron, config.backup_start_time)

        timezone_name = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(timezone_name)
        now_utc = fields.Datetime.now()
        now_local = pytz.utc.localize(now_utc).astimezone(user_tz)
        total_minutes = int(round((config.backup_start_time or 0.0) * 60))
        total_minutes = max(0, min(total_minutes, (24 * 60) - 1))
        hour, minute = divmod(total_minutes, 60)
        candidate_local = user_tz.localize(fields.Datetime.to_datetime(
            f'{config.weekly_start_date} {hour:02d}:{minute:02d}:00'))

        while candidate_local <= now_local:
            candidate_local += timedelta(weeks=cron.interval_number or 1)

        return fields.Datetime.to_string(candidate_local.astimezone(pytz.utc).replace(tzinfo=None))

    def _sync_backup_cron_start_time(self, frequencies=None):
        """Apply configured local start times to the shared backup crons."""
        frequencies = frequencies or set(self.mapped('backup_frequency')) or {'daily', 'weekly', 'monthly'}
        for frequency in frequencies:
            cron = self._get_backup_cron(frequency)
            if not cron:
                _logger.warning(
                    '[DB_AUTO_BACKUP][CRON_START_TIME][ERROR] frequency=%s reason=missing_cron',
                    frequency)
                continue
            configs = self.with_context(active_test=False).search([
                ('backup_frequency', '=', frequency),
                ('active', '=', True),
            ])
            if not configs:
                if cron.active:
                    _logger.info(
                        '[DB_AUTO_BACKUP][CRON_START_TIME][START] frequency=%s cron_id=%s action=deactivate reason=no_active_configs',
                        frequency, cron.id)
                    cron.sudo().write({'active': False})
                    _logger.info(
                        '[DB_AUTO_BACKUP][CRON_START_TIME][END] frequency=%s cron_id=%s active=%s',
                        frequency, cron.id, False)
                continue
            nextcalls = [
                self._cron_nextcall_from_config(cron, config)
                for config in configs
            ]
            nextcall = min(nextcalls)
            _logger.info(
                '[DB_AUTO_BACKUP][CRON_START_TIME][START] frequency=%s cron_id=%s configs=%s',
                frequency, cron.id, configs.ids)
            cron.sudo().write({
                'active': True,
                'nextcall': nextcall,
            })
            _logger.info(
                '[DB_AUTO_BACKUP][CRON_START_TIME][END] frequency=%s cron_id=%s active=%s nextcall=%s',
                frequency, cron.id, True, nextcall)

    def _schedule_auto_backup(self, frequency):
        """Function for generating and storing backup.
           Database backup for all the active records in backup configuration
           model will be created."""
        records = self.search([
            ('backup_frequency', '=', frequency),
            ('active', '=', True),
        ])
        for rec in records:
            rec._run_backup()

    def action_run_backup_now(self):
        """Run a backup manually from the configuration form."""
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only administrators can run database backups manually."))
        self._run_backup(manual=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Backup Complete'),
                'message': _('Backup %s was created successfully.') % self.backup_filename,
                'type': 'success',
                'sticky': False,
            }
        }

    def _run_backup(self, manual=False):
        """Create one backup for each selected configuration."""
        mail_template_success = self.env.ref(
            'db_auto_backup.mail_template_data_db_backup_successful')
        mail_template_failed = self.env.ref(
            'db_auto_backup.mail_template_data_db_backup_failed')
        for rec in self:
            backup_time = fields.datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
            backup_filename = f"{rec.db_name}_{backup_time}.{rec.backup_format}"
            rec.backup_filename = backup_filename
            rec.generated_exception = False
            start_time = fields.Datetime.now()
            backup_file = False
            temp_backup_file = False
            offsite_file = False
            try:
                _logger.info(
                    '[DB_AUTO_BACKUP][RUN_BACKUP][START] config_id=%s db=%s filename=%s manual=%s',
                    rec.id, rec.db_name, backup_filename, manual)
                backup_file = rec._prepare_backup_file(backup_filename)
                temp_backup_file = f'{backup_file}.tmp'
                with open(temp_backup_file, "wb") as backup_stream:
                    rec.dump_data(
                        rec.db_name,
                        backup_stream,
                        rec.backup_format,
                        rec.backup_frequency,
                        include_filestore=rec.include_filestore,
                        manual=manual,
                    )
                rec._finalize_backup_file(temp_backup_file, backup_file)
                offsite_file = rec._copy_backup_to_offsite(backup_file, backup_filename)
                rec._create_backup_history(
                    backup_filename,
                    backup_file,
                    offsite_file=offsite_file,
                    status='success',
                    run_type='manual' if manual else 'automatic',
                )
                rec._remove_old_backups()
                if rec.notify_user:
                    mail_template_success.send_mail(rec.id, force_send=True)
                duration = (fields.Datetime.now() - start_time).total_seconds()
                _logger.info(
                    '[DB_AUTO_BACKUP][RUN_BACKUP][END] config_id=%s db=%s filename=%s size=%s offsite=%s duration=%s',
                    rec.id, rec.db_name, backup_filename, os.path.getsize(backup_file), bool(offsite_file), duration)
            except Exception as e:
                if temp_backup_file and os.path.exists(temp_backup_file):
                    os.remove(temp_backup_file)
                rec.generated_exception = str(e)
                rec._create_backup_history(
                    backup_filename,
                    backup_file,
                    offsite_file=offsite_file,
                    status='failed',
                    run_type='manual' if manual else 'automatic',
                    error_message=str(e),
                )
                _logger.exception(
                    '[DB_AUTO_BACKUP][RUN_BACKUP][ERROR] config_id=%s db=%s filename=%s error=%s',
                    rec.id, rec.db_name, backup_filename, e)
                if rec.notify_user:
                    mail_template_failed.send_mail(rec.id, force_send=True)
                if manual:
                    raise UserError(_("Backup failed: %s") % e) from e

    def _prepare_backup_file(self, backup_filename):
        self.ensure_one()
        if not self.backup_path:
            raise ValidationError(_("Please configure a staging path."))
        if not os.path.isdir(self.backup_path):
            os.makedirs(self.backup_path)
        return os.path.join(self.backup_path, backup_filename)

    def _finalize_backup_file(self, temp_backup_file, backup_file):
        self.ensure_one()
        if not os.path.exists(temp_backup_file):
            raise UserError(_("Temporary backup file was not created."))
        if os.path.getsize(temp_backup_file) <= 0:
            raise UserError(_("Temporary backup file is empty."))
        os.replace(temp_backup_file, backup_file)
        _logger.info(
            '[DB_AUTO_BACKUP][STAGING_FINALIZE][END] config_id=%s path=%s size=%s',
            self.id, backup_file, os.path.getsize(backup_file))

    def _copy_backup_to_offsite(self, backup_file, backup_filename):
        self.ensure_one()
        if not self.copy_to_offsite:
            return False
        if not self.offsite_backup_path:
            raise ValidationError(_("Please configure an offsite backup path."))
        if not os.path.isdir(self.offsite_backup_path):
            os.makedirs(self.offsite_backup_path)

        offsite_file = os.path.join(self.offsite_backup_path, backup_filename)
        temp_offsite_file = f'{offsite_file}.tmp'
        _logger.info(
            '[DB_AUTO_BACKUP][OFFSITE_COPY][START] config_id=%s source=%s target=%s',
            self.id, backup_file, offsite_file)
        shutil.copy2(backup_file, temp_offsite_file)
        if os.path.getsize(temp_offsite_file) != os.path.getsize(backup_file):
            raise UserError(_("Offsite copy size does not match the staged backup."))
        os.replace(temp_offsite_file, offsite_file)
        _logger.info(
            '[DB_AUTO_BACKUP][OFFSITE_COPY][END] config_id=%s target=%s size=%s',
            self.id, offsite_file, os.path.getsize(offsite_file))
        return offsite_file

    def _create_backup_history(self, backup_filename, backup_file=False,
                               offsite_file=False, status='success',
                               run_type='automatic', error_message=False):
        self.ensure_one()
        file_size = os.path.getsize(backup_file) if backup_file and os.path.exists(backup_file) else 0
        history = self.env["db.backup.history"].create({
            "name": backup_filename,
            "backup_config_id": self.id,
            "backup_path": backup_file,
            "offsite_backup_path": offsite_file,
            "backup_date": fields.Datetime.now(),
            "backup_format": self.backup_format,
            "run_type": run_type,
            "status": status,
            "file_size_bytes": file_size,
            "file_size": self._format_file_size(file_size),
            "error_message": error_message,
        })
        if status == 'success':
            history.check_backup_integrity()
        return history

    def _remove_old_backups(self):
        self.ensure_one()
        if not self.auto_remove:
            return
        if self.days_to_remove <= 0:
            return
        cutoff = fields.Datetime.now() - timedelta(days=self.days_to_remove)
        _logger.info(
            '[DB_AUTO_BACKUP][RETENTION][START] config_id=%s db=%s cutoff=%s',
            self.id, self.db_name, cutoff)
        removed_files = 0
        for directory in [self.backup_path, self.offsite_backup_path]:
            if directory and os.path.isdir(directory):
                removed_files += self._remove_old_backup_files(directory, cutoff)
        histories = self.env['db.backup.history'].search([
            ('name', '=like', f'{self.db_name}_%'),
            ('backup_date', '<', cutoff),
        ], order='backup_date desc')
        histories = histories[self.retention_min_backups:]
        history_count = len(histories)
        histories.unlink()
        stale_histories = self.env['db.backup.history'].search([
            ('name', '=like', f'{self.db_name}_%'),
        ]).filtered(lambda history: not history._get_existing_backup_path())
        stale_history_count = len(stale_histories)
        stale_histories.unlink()
        _logger.info(
            '[DB_AUTO_BACKUP][RETENTION][END] config_id=%s removed_files=%s removed_history=%s removed_stale_history=%s',
            self.id, removed_files, history_count, stale_history_count)

    def _remove_old_backup_files(self, directory, cutoff):
        removed_files = 0
        valid_extensions = ('.zip', '.dump')
        backup_files = []
        for filename in os.listdir(directory):
            if filename.startswith(f'{self.db_name}_') and filename.endswith(valid_extensions):
                file_path = os.path.join(directory, filename)
                if os.path.isfile(file_path):
                    backup_files.append(file_path)
        backup_files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        for file_path in backup_files[self.retention_min_backups:]:
            modified_at = fields.datetime.fromtimestamp(os.path.getmtime(file_path))
            if modified_at < cutoff:
                os.remove(file_path)
                removed_files += 1
                _logger.info(
                    '[DB_AUTO_BACKUP][RETENTION][FILE_REMOVED] config_id=%s path=%s',
                    self.id, file_path)
        return removed_files

    def _format_file_size(self, size_bytes):
        if not size_bytes:
            return "0 MB"
        return f"{round(size_bytes / 1024 / 1024, 2)} MB"

    def dump_data(self, db_name, stream, backup_format, backup_frequency,
                  include_filestore=True, manual=False):
        """Dump database `db` into file-like object `stream` if stream is None
        return a file object with the dump. """
        cron_user_id = self.env.ref(f'db_auto_backup.ir_cron_auto_db_backup_{backup_frequency}').user_id.id
        is_manual_admin = manual and self.env.user.has_group('base.group_system')
        if cron_user_id != self.env.user.id and not is_manual_admin:
            _logger.error(
                'Unauthorized database operation. Backups should only be available from the cron job or administrators.')
            raise ValidationError("Unauthorized database operation. Backups should only be available from the cron job or administrators.")
        _logger.info(
            '[DB_AUTO_BACKUP][DUMP_DATA][START] db=%s format=%s include_filestore=%s',
            db_name, backup_format, include_filestore)
        cmd = [find_pg_tool('pg_dump'), '--no-owner', db_name]
        env = exec_pg_environ()
        if backup_format == 'zip':
            with tempfile.TemporaryDirectory() as dump_dir:
                filestore = odoo.tools.config.filestore(db_name)
                cmd.insert(-1,'--file=' + os.path.join(dump_dir, 'dump.sql'))
                subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.STDOUT, check=True)
                if include_filestore and os.path.exists(filestore):
                    shutil.copytree(filestore,
                                    os.path.join(dump_dir, 'filestore'))
                with open(os.path.join(dump_dir, 'manifest.json'), 'w') as fh:
                    db = odoo.sql_db.db_connect(db_name)
                    with db.cursor() as cr:
                        json.dump(self._dump_db_manifest(cr), fh, indent=4)
                if stream:
                    odoo.tools.osutil.zip_dir(dump_dir, stream,
                                              include_dir=False,
                                              fnct_sort=lambda
                                                  file_name: file_name != 'dump.sql')
                else:
                    t = tempfile.TemporaryFile()
                    odoo.tools.osutil.zip_dir(dump_dir, t, include_dir=False,
                                              fnct_sort=lambda
                                                  file_name: file_name != 'dump.sql')
                    t.seek(0)
                    return t
        else:
            cmd.insert(-1,'--format=c')
            process = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE)
            stdout, _ = process.communicate()
            if stream:
                stream.write(stdout)
            else:
                return stdout
        _logger.info(
            '[DB_AUTO_BACKUP][DUMP_DATA][END] db=%s format=%s',
            db_name, backup_format)

    def _dump_db_manifest(self, cr):
        """ This function generates a manifest dictionary for database dump."""
        pg_version = "%d.%d" % divmod(cr._obj.connection.server_version / 100, 100)
        cr.execute(
            "SELECT name, latest_version FROM ir_module_module WHERE state = 'installed'")
        modules = dict(cr.fetchall())
        manifest = {
            'odoo_dump': '1',
            'db_name': cr.dbname,
            'version': odoo.release.version,
            'version_info': odoo.release.version_info,
            'major_version': odoo.release.major_version,
            'pg_version': pg_version,
            'modules': modules,
        }
        return manifest
