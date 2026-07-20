import logging

from odoo import models


_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _create_order_picking(self):
        result = super()._create_order_picking()
        facts = self.mapped("picking_ids.move_ids.move_line_ids.volume_fact_ids")
        if facts:
            _logger.info(
                "VOLUME_POS_ENRICH_START pos_order_ids=%s picking_ids=%s fact_ids=%s",
                self.ids,
                self.picking_ids.ids,
                facts.ids,
            )
            enrichment = facts._system_recalculate(reason="pos_order_linked")
            _logger.info(
                "VOLUME_POS_ENRICH_DONE pos_order_ids=%s result=%s",
                self.ids,
                enrichment,
            )
        return result

