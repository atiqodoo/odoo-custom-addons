import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models, _


_logger = logging.getLogger(__name__)


class ProductMovementVolumeBackfillWizard(models.TransientModel):
    _name = "product.movement.volume.backfill.wizard"
    _description = "Movement Volume Backfill Wizard"

    date_from = fields.Date(string="From")
    date_to = fields.Date(string="To", default=fields.Date.context_today)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    product_ids = fields.Many2many("product.product", string="Products")
    max_records = fields.Integer(
        default=5000,
        help="Maximum missing move lines processed in one run. Use zero for no limit.",
    )

    def action_backfill(self):
        self.ensure_one()
        domain = [
            ("state", "=", "done"),
            ("quantity", "!=", 0),
            ("company_id", "=", self.company_id.id),
            ("volume_fact_ids", "=", False),
        ]
        if self.date_from:
            domain.append(("date", ">=", self._local_date_boundary_utc(self.date_from)))
        if self.date_to:
            domain.append(
                ("date", "<", self._local_date_boundary_utc(self.date_to + timedelta(days=1)))
            )
        if self.product_ids:
            domain.append(("product_id", "in", self.product_ids.ids))

        limit = max(0, self.max_records)
        lines = self.env["stock.move.line"].search(domain, order="id", limit=limit or None)
        _logger.info(
            "VOLUME_BACKFILL_START wizard_id=%s company_id=%s date_from=%s date_to=%s "
            "product_ids=%s max_records=%s move_line_count=%s",
            self.id,
            self.company_id.id,
            self.date_from,
            self.date_to,
            self.product_ids.ids,
            limit,
            len(lines),
        )
        result = self.env["product.movement.volume.builder"].build_from_move_lines(
            lines, source="backfill"
        )
        _logger.info("VOLUME_BACKFILL_DONE wizard_id=%s result=%s", self.id, result)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Movement Volume Backfill"),
                "message": _(
                    "Candidates: %(candidates)s, created: %(created)s, skipped: %(skipped)s, failed: %(failed)s",
                    **result,
                ),
                "type": "success" if not result["failed"] else "warning",
                "sticky": bool(result["failed"]),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _local_date_boundary_utc(self, value):
        timezone = pytz.timezone(self.env.user.tz or "UTC")
        local_boundary = timezone.localize(datetime.combine(value, time.min))
        return local_boundary.astimezone(pytz.UTC).replace(tzinfo=None)
