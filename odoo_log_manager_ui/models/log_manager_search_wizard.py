from odoo import fields, models


class LogManagerSearchWizard(models.TransientModel):
    _name = "log.manager.search.wizard"
    _description = "Log Manager Search Wizard"

    level = fields.Selection(
        [
            ("DEBUG", "Debug"),
            ("INFO", "Info"),
            ("WARNING", "Warning"),
            ("ERROR", "Error"),
            ("CRITICAL", "Critical"),
        ]
    )
    database = fields.Char()
    module = fields.Char()
    keyword = fields.Char()
    since = fields.Datetime()
    until = fields.Datetime()
    limit = fields.Integer(default=100)
    offset = fields.Integer(default=0)

    def action_search(self):
        self.ensure_one()
        criteria = {
            "level": self.level or None,
            "database": self.database or None,
            "module": self.module or None,
            "keyword": self.keyword or None,
            "since": self.since,
            "until": self.until,
            "limit": self.limit or 100,
            "offset": self.offset or 0,
        }
        entries = self.env["log.manager.adapter"].search(criteria)
        entry_model = self.env["log.manager.entry"].sudo()
        entry_model.search([("source_type", "=", "indexed")]).unlink()
        values = [self._entry_values(entry) for entry in entries]
        if values:
            entry_model.create(values)
        return {
            "type": "ir.actions.act_window",
            "name": "Indexed Log Search",
            "res_model": "log.manager.entry",
            "view_mode": "list,form",
            "domain": [("source_type", "=", "indexed")],
        }

    def _entry_values(self, entry):
        return {
            "timestamp": fields.Datetime.to_string(entry.timestamp)
            if entry.timestamp
            else False,
            "level": entry.level if entry.level in dict(self.env["log.manager.entry"]._fields["level"].selection) else False,
            "database": entry.database,
            "module": entry.module,
            "message": entry.message,
            "raw": entry.raw,
            "line_no": entry.line_no,
            "source_type": "indexed",
        }
