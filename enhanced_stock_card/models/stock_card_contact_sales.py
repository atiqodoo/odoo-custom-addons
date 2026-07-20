# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockCardWizardContactSales(models.TransientModel):
    _inherit = 'stock.card.wizard'

    def _collect_contact_sale_rows(self, partner_ids):
        date_from, date_to = self._contact_date_range()
        states = ['draft', 'sent', 'sale', 'done'] if self.include_draft_sales else ['sale', 'done']
        domain = [
            ('partner_id', 'in', partner_ids),
            ('date_order', '>=', date_from),
            ('date_order', '<=', date_to),
            ('state', 'in', states),
        ]
        orders = self.env['sale.order'].search(domain, order='date_order, id')
        _logger.info("[CONTACT REPORT][SALES] Domain: %s", domain)
        _logger.info("[CONTACT REPORT][SALES] Orders found: %s", len(orders))

        rows = []
        for order in orders:
            for line in order.order_line.filtered(lambda sale_line: not sale_line.display_type):
                if not self._contact_product_allowed(line.product_id):
                    continue
                qty = line.product_uom_qty or 0.0
                amount_incl = line.price_total or 0.0
                amount_excl = line.price_subtotal or 0.0
                rows.append(self._contact_row(
                    date=order.date_order,
                    contact=order.partner_id.display_name,
                    product=line.product_id.display_name,
                    product_id=line.product_id,
                    source_app='Sales',
                    source_document=order.name,
                    document_state=order.state,
                    transaction_type='Quotation' if order.state in ('draft', 'sent') else 'Sales Order',
                    qty_out=qty,
                    amount_incl_vat=amount_incl,
                    vat_amount=amount_incl - amount_excl,
                    reference=order.client_order_ref or order.name,
                    debug_source=f"sale.order:{order.id}/line:{line.id}",
                ))
        return rows
