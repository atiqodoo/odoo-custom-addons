from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    log_manager_engine_path = fields.Char(
        string="Log Manager Engine Path",
        config_parameter="odoo_log_manager_ui.engine_path",
    )
    log_manager_config_path = fields.Char(
        string="Log Manager Config Path",
        config_parameter="odoo_log_manager_ui.config_path",
    )
    log_manager_auto_rotate_enabled = fields.Boolean(
        string="Enable Automatic Rotation",
        config_parameter="odoo_log_manager_ui.auto_rotate_enabled",
    )
    log_manager_rotation_strategy = fields.Selection(
        [("size", "Size"), ("time", "Time")],
        string="Rotation Strategy",
        default="size",
        config_parameter="odoo_log_manager_ui.rotation_strategy",
    )
    log_manager_max_size_mb = fields.Integer(
        string="Maximum Size (MB)",
        default=100,
        config_parameter="odoo_log_manager_ui.max_size_mb",
    )
    log_manager_locked_file_mode = fields.Selection(
        [
            ("copy", "Copy"),
            ("copy_truncate", "Copy and Truncate"),
            ("fail", "Fail"),
        ],
        string="Locked File Mode",
        default="copy",
        config_parameter="odoo_log_manager_ui.locked_file_mode",
    )
    log_manager_auto_rotate_interval_number = fields.Integer(
        string="Rotation Interval",
        default=5,
        config_parameter="odoo_log_manager_ui.auto_rotate_interval_number",
    )
    log_manager_auto_rotate_interval_type = fields.Selection(
        [
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        string="Rotation Interval Unit",
        default="hours",
        config_parameter="odoo_log_manager_ui.auto_rotate_interval_type",
    )

    def set_values(self):
        super().set_values()
        cron = self.env.ref(
            "odoo_log_manager_ui.ir_cron_log_manager_auto_rotate",
            raise_if_not_found=False,
        )
        if cron:
            cron.write(
                {
                    "active": self.log_manager_auto_rotate_enabled,
                    "interval_number": self.log_manager_auto_rotate_interval_number or 1,
                    "interval_type": self.log_manager_auto_rotate_interval_type or "hours",
                }
            )
