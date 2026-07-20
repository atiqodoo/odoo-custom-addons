import os
import subprocess
import time
from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Datetime


class MpesaBridgeControl(models.TransientModel):
    _name = 'mpesa.bridge.control'
    _description = 'M-Pesa SMS Bridge Control'

    bridge_type = fields.Selection(
        selection=[('python', 'Python Bridge'), ('go', 'Go Bridge')],
        string='Active Engine',
        compute='_compute_bridge_type',
        help='Engine currently selected in General Settings.',
    )
    bridge_runner_path = fields.Char(
        'Bridge Runner',
        compute='_compute_bridge_runner_path',
        readonly=True,
    )
    bridge_running = fields.Boolean('Bridge Running', compute='_compute_status')
    restart_locked = fields.Boolean('Restart Locked', compute='_compute_status')
    process_info = fields.Text('Process Info', compute='_compute_status')
    last_log_line = fields.Text('Latest Log Line', compute='_compute_status')

    def _compute_bridge_type(self):
        for rec in self:
            rec.bridge_type = rec._get_bridge_type()

    def _compute_bridge_runner_path(self):
        for rec in self:
            rec.bridge_runner_path = rec._active_runner()

    @api.depends('bridge_runner_path', 'bridge_type')
    def _compute_status(self):
        running, process_info = self._bridge_process_info()
        health_running = self._latest_health_running()
        log_line = self._latest_log_line()
        locked = self._restart_locked()
        for rec in self:
            rec.bridge_running = running or health_running
            rec.restart_locked = locked
            rec.process_info = process_info
            rec.last_log_line = log_line

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        return values

    def action_start_bridge(self):
        self.ensure_one()
        if self._restart_locked():
            return self._notification('Bridge restart is already in progress. Please wait.', 'warning')
        self._dedupe_bridge_processes()
        running, _process_info = self._bridge_process_info()
        if running:
            return self._notification('M-Pesa bridge is already running.', 'info')

        self._start_bridge_process()
        time.sleep(3)
        self._dedupe_bridge_processes()
        return self._notification('M-Pesa bridge start requested.', 'success')

    def action_restart_bridge(self):
        self.ensure_one()
        if self._restart_locked():
            return self._notification('Bridge restart is already in progress. Please wait.', 'warning')

        self._set_restart_lock(seconds=60)
        try:
            self._stop_bridge_processes()
            time.sleep(2)
            self._start_bridge_process(force_restart=True)
            time.sleep(8)
            self._dedupe_bridge_processes()
            running, _process_info = self._bridge_process_info()
            if not running:
                return self._notification('Bridge restart was requested, but no bridge process was detected after restart.', 'danger')
        finally:
            self._clear_restart_lock()
        return self._notification('M-Pesa bridge restart completed.', 'success')

    def _start_bridge_process(self, force_restart=False):
        runner = self._active_runner()
        if not os.path.exists(runner):
            raise FileNotFoundError(f'Bridge runner not found: {runner}')

        args = [
            'powershell.exe',
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-WindowStyle',
            'Hidden',
            '-File',
            runner,
        ]
        if force_restart:
            args.append('-ForceRestart')

        subprocess.Popen(
            args,
            cwd=os.path.dirname(runner),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )

    @api.model
    def _stop_bridge_processes(self):
        command = self._active_process_stop_command()
        subprocess.run(
            ['powershell.exe', '-NoProfile', '-Command', command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            timeout=8,
        )

    @api.model
    def _dedupe_bridge_processes(self):
        command = self._active_process_dedupe_command()
        subprocess.run(
            ['powershell.exe', '-NoProfile', '-Command', command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            timeout=8,
        )

    @api.model
    def _get_bridge_type(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'mpesa_c2b_sms.bridge_type',
            'python',
        )

    @api.model
    def _python_runner_path(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'mpesa_c2b_sms.bridge_runner_path',
            r'C:\odoo18\mpesa_sms_bridge\run_bridge.ps1',
        )

    @api.model
    def _go_runner_path(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'mpesa_c2b_sms.go_bridge_runner_path',
            r'C:\odoo18\mpesa_sms_bridge_go\run_bridge.ps1',
        )

    @api.model
    def _active_runner(self):
        if self._get_bridge_type() == 'go':
            return self._go_runner_path()
        return self._python_runner_path()

    @api.model
    def _active_process_stop_command(self):
        if self._get_bridge_type() == 'go':
            return self._go_process_command(
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            )
        runner = self._python_runner_path()
        bridge_py = os.path.join(os.path.dirname(runner), 'bridge.py')
        return self._process_match_command(
            runner,
            bridge_py,
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
        )

    @api.model
    def _active_process_dedupe_command(self):
        action = (
            "Sort-Object CreationDate | "
            "Select-Object -Skip 1 | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        if self._get_bridge_type() == 'go':
            return self._go_process_command(action)
        runner = self._python_runner_path()
        bridge_py = os.path.join(os.path.dirname(runner), 'bridge.py')
        return self._process_match_command(runner, bridge_py, action, python_only=True)

    @staticmethod
    def _go_process_command(action):
        return (
            "$matches = @(Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -eq 'bridge.exe' -and $_.ExecutablePath -like '*mpesa_sms_bridge_go*' } | "
            "Sort-Object ProcessId -Unique); "
            "$matches | "
            f"{action}"
        )

    @staticmethod
    def _process_match_command(runner, bridge_py, action, python_only=False):
        ps_bridge = bridge_py.replace("'", "''")
        ps_runner = runner.replace("'", "''")
        runner_match = ''
        if not python_only:
            runner_match = (
                f"$runnerMatches = @($processes | Where-Object {{ $_.Name -match 'powershell' -and $_.CommandLine -like '*{ps_runner}*' }}); "
            )
        return (
            "$processes = @(Get-CimInstance Win32_Process); "
            f"$pathMatches = @($processes | Where-Object {{ $_.Name -match 'python' -and $_.CommandLine -like '*{ps_bridge}*' }}); "
            "$hiddenOdooChildren = @($processes | Where-Object { "
            "if ($_.Name -notmatch 'python' -or -not [string]::IsNullOrWhiteSpace($_.CommandLine)) { return $false }; "
            "$candidate = $_; "
            "$parent = $processes | Where-Object { $_.ProcessId -eq $candidate.ParentProcessId } | Select-Object -First 1; "
            "if (-not $parent -or $parent.Name -notmatch 'powershell') { return $false }; "
            "$grand = $processes | Where-Object { $_.ProcessId -eq $parent.ParentProcessId } | Select-Object -First 1; "
            "return ($grand -and $grand.Name -match 'python') "
            "}); "
            f"{runner_match}"
            "$matches = @($pathMatches + $hiddenOdooChildren"
            + (" + $runnerMatches" if not python_only else "")
            + ") | Sort-Object ProcessId -Unique; "
            "$matches | "
            f"{action}"
        )

    @api.model
    def _restart_locked(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'mpesa_c2b_sms.bridge_restart_lock_until',
            '',
        )
        if not value:
            return False
        try:
            return Datetime.from_string(value) > Datetime.now()
        except Exception:
            return False

    @api.model
    def _set_restart_lock(self, seconds=60):
        lock_until = Datetime.now() + timedelta(seconds=seconds)
        self.env['ir.config_parameter'].sudo().set_param(
            'mpesa_c2b_sms.bridge_restart_lock_until',
            Datetime.to_string(lock_until),
        )

    @api.model
    def _clear_restart_lock(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'mpesa_c2b_sms.bridge_restart_lock_until',
            '',
        )

    def action_refresh_status(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _bridge_process_info(self):
        try:
            if self._get_bridge_type() == 'go':
                process_filter = (
                    "Where-Object { $_.Name -eq 'bridge.exe' -and $_.ExecutablePath -like '*mpesa_sms_bridge_go*' } | "
                )
            else:
                process_filter = (
                    "Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'mpesa_sms_bridge' -and $_.CommandLine -match 'bridge.py' } | "
                )
            output = subprocess.check_output(
                [
                    'powershell.exe',
                    '-NoProfile',
                    '-Command',
                    (
                        "Get-CimInstance Win32_Process | "
                        f"{process_filter}"
                        "Select-Object ProcessId,Name,CommandLine | "
                        "ConvertTo-Json -Compress"
                    ),
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                timeout=8,
            ).strip()
        except Exception:
            return False, ''
        return bool(output), output

    @api.model
    def _latest_health_running(self):
        health = self.env['mpesa.modem.health'].sudo().search([], order='timestamp desc', limit=1)
        if not health or not health.modem_connected or not health.timestamp:
            return False
        return (Datetime.now() - health.timestamp).total_seconds() <= 180

    @api.model
    def _latest_log_line(self):
        runner = self._active_runner()
        log_path = os.path.join(os.path.dirname(runner), 'bridge.log')
        if not os.path.exists(log_path):
            return ''
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as handle:
                lines = [line.strip() for line in handle.readlines() if line.strip()]
        except OSError:
            return ''
        return lines[-1] if lines else ''

    @staticmethod
    def _notification(message, notification_type):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'M-Pesa SMS Bridge',
                'message': message,
                'type': notification_type,
                'sticky': False,
            },
        }
