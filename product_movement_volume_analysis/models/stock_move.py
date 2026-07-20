import logging

from odoo import fields, models


_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, cancel_backorder=False):
        done_moves = super()._action_done(cancel_backorder=cancel_backorder)
        completed = done_moves.filtered(lambda move: move.state == "done")
        move_lines = completed.mapped("move_line_ids").filtered(lambda line: line.state == "done")
        if not move_lines:
            return done_moves

        _logger.info(
            "VOLUME_HOOK_START move_ids=%s move_line_ids=%s cancel_backorder=%s",
            completed.ids,
            move_lines.ids,
            cancel_backorder,
        )
        try:
            result = self.env["product.movement.volume.builder"].build_from_move_lines(
                move_lines, source="hook"
            )
            _logger.info("VOLUME_HOOK_DONE move_ids=%s result=%s", completed.ids, result)
        except Exception:
            # Analytics must never prevent a valid warehouse operation. The cron repairs gaps.
            _logger.exception(
                "VOLUME_HOOK_FAILED move_ids=%s move_line_ids=%s; reconciliation cron will retry",
                completed.ids,
                move_lines.ids,
            )
        return done_moves


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    volume_fact_ids = fields.One2many(
        "product.movement.volume",
        "move_line_id",
        string="Movement Volume Facts",
        readonly=True,
    )
