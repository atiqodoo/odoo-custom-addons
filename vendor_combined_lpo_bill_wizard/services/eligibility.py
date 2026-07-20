# -*- coding: utf-8 -*-
import logging


_logger = logging.getLogger(__name__)


class CombinedLpoEligibilityService:
    def __init__(self, env):
        self.env = env

    def iter_eligible_purchase_lines(self, purchases):
        for order in purchases:
            for line in order.order_line.filtered(lambda item: not item.display_type and item.product_id):
                qty = line._get_combined_lpo_billable_qty()
                reason = 'eligible' if qty else 'no_received_unbilled_qty'
                if 'is_promotion_foc' in line._fields and line.is_promotion_foc:
                    reason = 'foc_payable_excluded'
                _logger.info(
                    '[CLPO_ELIGIBILITY] purchase_line_id=%s po=%s product_id=%s '
                    'received=%s invoiced=%s eligible_qty=%s reason=%s',
                    line.id,
                    order.name,
                    line.product_id.id,
                    line.qty_received,
                    line.qty_invoiced,
                    qty,
                    reason,
                )
                if qty:
                    yield line, qty
