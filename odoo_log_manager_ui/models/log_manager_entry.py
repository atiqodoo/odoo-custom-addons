from odoo import api, fields, models


class LogManagerEntry(models.Model):
    _name = "log.manager.entry"
    _description = "Log Manager Entry"
    _order = "timestamp desc, id desc"
    _rec_name = "summary"

    timestamp = fields.Datetime(readonly=True, index=True)
    level = fields.Selection(
        [
            ("DEBUG", "Debug"),
            ("INFO", "Info"),
            ("WARNING", "Warning"),
            ("ERROR", "Error"),
            ("CRITICAL", "Critical"),
        ],
        readonly=True,
        index=True,
    )
    database = fields.Char(readonly=True, index=True)
    module = fields.Char(readonly=True, index=True)
    message = fields.Text(readonly=True)
    raw = fields.Text(readonly=True)
    line_no = fields.Integer(readonly=True)
    source_path = fields.Char(readonly=True, index=True)
    source_type = fields.Selection(
        [("live", "Live"), ("indexed", "Indexed")],
        default="live",
        readonly=True,
        index=True,
    )
    summary = fields.Char(compute="_compute_summary", store=True)

    @api.depends("level", "module", "message")
    def _compute_summary(self):
        for record in self:
            parts = [record.level or "LOG"]
            if record.module:
                parts.append(record.module)
            if record.message:
                parts.append(record.message[:100])
            record.summary = " | ".join(parts)

    def init(self):
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS log_manager_entry_message_idx "
            "ON log_manager_entry USING gin(to_tsvector('simple', coalesce(message, '')))"
        )
