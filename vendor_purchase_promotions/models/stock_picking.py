import logging

from odoo import models


_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        result = super().button_validate()
        purchase_lines = self.move_ids.purchase_line_id
        applications = self.env['vendor.purchase.promotion.application'].search([
            '|',
            ('charged_line_id', 'in', purchase_lines.ids),
            ('foc_line_id', 'in', purchase_lines.ids),
        ]) if purchase_lines else self.env['vendor.purchase.promotion.application']
        if applications:
            applications._compute_foc_status()
            applications.bill_ids._sync_promotion_payment_hold()
            for application in applications:
                _logger.info(
                    '[VPP_RECEIPT] validated picking_ids=%s application_id=%s charged_received=%s '
                    'foc_expected=%s foc_received=%s foc_outstanding=%s state=%s bill_ids=%s',
                    self.ids,
                    application.id,
                    application.charged_line_id.qty_received,
                    application.promised_foc_qty,
                    application.received_foc_qty,
                    application.outstanding_foc_qty,
                    application.fulfillment_state,
                    application.bill_ids.ids,
                )
        return result

