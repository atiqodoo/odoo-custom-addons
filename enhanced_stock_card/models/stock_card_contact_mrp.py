# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockCardWizardContactMrp(models.TransientModel):
    _inherit = 'stock.card.wizard'

    def _collect_contact_mrp_rows(self, partner_ids):
        date_from, date_to = self._contact_date_range()
        domain = [
            ('state', 'in', ['confirmed', 'progress', 'to_close', 'done']),
            '|',
            ('date_start', '>=', date_from),
            ('date_finished', '>=', date_from),
            '|',
            ('date_start', '<=', date_to),
            ('date_finished', '<=', date_to),
        ]
        productions = self.env['mrp.production'].search(domain, order='date_start, id')
        _logger.info("[CONTACT REPORT][MRP] Domain: %s", domain)
        _logger.info("[CONTACT REPORT][MRP] Productions found before contact inference: %s", len(productions))

        rows = []
        for production in productions:
            partner = self._infer_mrp_partner(production, partner_ids)
            if not partner:
                continue
            moves = production.move_raw_ids | production.move_finished_ids
            for move in moves.filtered(lambda stock_move: self._contact_product_allowed(stock_move.product_id)):
                if not self._contact_move_location_allowed(move):
                    continue
                layer = move.stock_valuation_layer_ids[:1] if move.stock_valuation_layer_ids else False
                rows.append(self._contact_row(
                    date=move.date or production.date_start or production.date_finished,
                    contact=partner.display_name,
                    product=move.product_id.display_name,
                    product_id=move.product_id,
                    source_app='Manufacturing',
                    source_document=production.name,
                    document_state=production.state,
                    transaction_type='MO Finished Product' if move.production_id else 'MO Consumption',
                    qty_in=move.quantity if move.production_id else 0.0,
                    qty_out=move.quantity if move.raw_material_production_id else 0.0,
                    inventory_value=layer.value if layer else 0.0,
                    location=f"{move.location_id.complete_name} -> {move.location_dest_id.complete_name}",
                    reference=production.origin or production.name,
                    debug_source=f"mrp.production:{production.id}/stock.move:{move.id}",
                ))
        _logger.info("[CONTACT REPORT][MRP] Rows after contact inference: %s", len(rows))
        return rows

    def _infer_mrp_partner(self, production, partner_ids):
        if hasattr(production, 'partner_id') and production.partner_id and production.partner_id.id in partner_ids:
            return production.partner_id

        origin = production.origin
        if origin:
            sale = self.env['sale.order'].search([
                ('name', '=', origin),
                ('partner_id', 'in', partner_ids),
            ], limit=1)
            if sale:
                _logger.info("[CONTACT REPORT][MRP] Production %s linked by origin to sale %s", production.name, sale.name)
                return sale.partner_id

        sale_moves = (production.move_raw_ids | production.move_finished_ids).filtered(
            lambda move: move.sale_line_id and move.sale_line_id.order_id.partner_id.id in partner_ids
        )
        if sale_moves:
            sale = sale_moves[0].sale_line_id.order_id
            _logger.info("[CONTACT REPORT][MRP] Production %s linked by move sale line to sale %s", production.name, sale.name)
            return sale.partner_id

        return False
