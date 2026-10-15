from odoo import api, fields, models


class LogManagerArchive(models.Model):
    _name = "log.manager.archive"
    _description = "Log Manager Archive"
    _order = "indexed_at desc, id desc"

    name = fields.Char(required=True)
    path = fields.Char(required=True, index=True)
    size_bytes = fields.Integer(readonly=True)
    compressed_size = fields.Integer(readonly=True)
    line_count = fields.Integer(readonly=True)
    first_ts = fields.Datetime(readonly=True)
    last_ts = fields.Datetime(readonly=True)
    indexed_at = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("path_unique", "unique(path)", "Each indexed archive path must be unique."),
    ]

    @api.model
    def action_sync_archives(self):
        archives = self.env["log.manager.adapter"].archives()
        for archive in archives:
            values = {
                "name": archive.get("filename") or archive.get("path"),
                "path": archive.get("path"),
                "size_bytes": archive.get("size_bytes") or 0,
                "compressed_size": archive.get("compressed_size") or 0,
                "line_count": archive.get("line_count") or 0,
                "first_ts": self._dt(archive.get("first_ts")),
                "last_ts": self._dt(archive.get("last_ts")),
                "indexed_at": self._dt(archive.get("indexed_at")),
            }
            existing = self.search([("path", "=", values["path"])], limit=1)
            if existing:
                existing.write(values)
            else:
                self.create(values)
        return {
            "type": "ir.actions.act_window",
            "name": "Log Archives",
            "res_model": "log.manager.archive",
            "view_mode": "list,form",
        }

    def _dt(self, value):
        if not value:
            return False
        return str(value).replace("T", " ")[:19]
