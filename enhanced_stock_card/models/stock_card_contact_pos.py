# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockCardWizardContactPos(models.TransientModel):
    _inherit = 'stock.card.wizard'

    def _collect_contact_pos_rows(self, partner_ids):
        date_from, date_to = self._contact_date_range()
        domain = [
            ('partner_id', 'in', partner_ids),
            ('date_order', '>=', date_from),
            ('date_order', '<=', date_to),
        ]
        orders = self.env['pos.order'].search(domain, order='date_order, id')
        _logger.info("[CONTACT REPORT][POS] Domain: %s", domain)
        _logger.info("[CONTACT REPORT][POS] Orders found: %s", len(orders))

        rows = []
        for order in orders:
            for line in order.lines:
                if not self._contact_product_allowed(line.product_id):
                    continue
                amount_incl = line.price_subtotal_incl or 0.0
                amount_excl = line.price_subtotal or 0.0
                qty = line.qty or 0.0
                rows.append(self._contact_row(
                    date=order.date_order,
                    contact=order.partner_id.display_name,
                    product=line.product_id.display_name,
                    product_id=line.product_id,
                    source_app='POS',
                    source_document=order.name,
                    document_state=order.state,
                    transaction_type='POS Sale' if qty >= 0 else 'POS Return',
                    qty_in=abs(qty) if qty < 0 else 0.0,
                    qty_out=qty if qty > 0 else 0.0,
                    amount_incl_vat=amount_incl,
                    vat_amount=amount_incl - amount_excl,
                    reference=order.pos_reference or order.name,
                    debug_source=f"pos.order:{order.id}/line:{line.id}",
                ))
        return rows
