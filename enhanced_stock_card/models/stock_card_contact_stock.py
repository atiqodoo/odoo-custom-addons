# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockCardWizardContactStock(models.TransientModel):
    _inherit = 'stock.card.wizard'

    def _collect_contact_stock_move_rows(self, partner_ids):
        date_from, date_to = self._contact_date_range()
        domain = [
            ('state', '=', 'done'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            '|', '|', '|',
            ('partner_id', 'in', partner_ids),
            ('picking_id.partner_id', 'in', partner_ids),
            ('sale_line_id.order_id.partner_id', 'in', partner_ids),
            ('purchase_line_id.order_id.partner_id', 'in', partner_ids),
        ]
        if self.product_ids:
            domain.append(('product_id', 'in', self.product_ids.ids))

        moves = self.env['stock.move'].search(domain, order='date, id')
        _logger.info("[CONTACT REPORT][STOCK] Domain: %s", domain)
        _logger.info("[CONTACT REPORT][STOCK] Moves found before location filter: %s", len(moves))

        rows = []
        for move in moves:
            if not self._contact_move_location_allowed(move):
                _logger.info("[CONTACT REPORT][STOCK] Move %s skipped by location filter", move.id)
                continue
            rows.append(self._prepare_contact_stock_move_row(move))
        return rows

    def _prepare_contact_stock_move_row(self, move):
        location_ids = self.location_ids.ids
        qty_in = 0.0
        qty_out = 0.0

        if location_ids:
            source_selected = move.location_id.id in location_ids
            dest_selected = move.location_dest_id.id in location_ids
            if dest_selected and not source_selected:
                qty_in = move.quantity
            elif source_selected and not dest_selected:
                qty_out = move.quantity
            elif source_selected and dest_selected:
                if self.show_internal_transfers:
                    qty_in = move.quantity
                    qty_out = move.quantity
                else:
                    qty_in = 0.0
                    qty_out = 0.0
        else:
            if move.location_dest_id.usage == 'internal' and move.location_id.usage != 'internal':
                qty_in = move.quantity
            elif move.location_id.usage == 'internal' and move.location_dest_id.usage != 'internal':
                qty_out = move.quantity
            elif self.show_internal_transfers and move.location_id.usage == 'internal' and move.location_dest_id.usage == 'internal':
                qty_in = move.quantity
                qty_out = move.quantity

        layer = move.stock_valuation_layer_ids[:1] if move.stock_valuation_layer_ids else False
        inventory_value = layer.value if layer else 0.0
        amount_incl_vat, vat_amount = self._get_contact_move_amounts(move)

        partner = move.partner_id or move.picking_id.partner_id
        if not partner and move.sale_line_id:
            partner = move.sale_line_id.order_id.partner_id
        if not partner and move.purchase_line_id:
            partner = move.purchase_line_id.order_id.partner_id

        return self._contact_row(
            date=move.date,
            contact=partner.display_name if partner else '',
            product=move.product_id.display_name,
            product_id=move.product_id,
            source_app='Inventory',
            source_document=move.reference or (move.picking_id.name if move.picking_id else move.name),
            document_state=move.state,
            transaction_type=self._determine_move_type(move),
            qty_in=qty_in,
            qty_out=qty_out,
            inventory_value=inventory_value,
            amount_incl_vat=amount_incl_vat,
            vat_amount=vat_amount,
            location=f"{move.location_id.complete_name} -> {move.location_dest_id.complete_name}",
            reference=move.reference or move.name,
            debug_source=f"stock.move:{move.id}",
        )

    def _get_contact_move_amounts(self, move):
        if move.picking_id and move.picking_id.pos_order_id:
            pos_order = move.picking_id.pos_order_id
            pos_lines = pos_order.lines.filtered(lambda line: line.product_id == move.product_id and line.qty > 0)
            amount = sum(pos_lines.mapped('price_subtotal_incl'))
            subtotal = sum(pos_lines.mapped('price_subtotal'))
            _logger.info(
                "[CONTACT REPORT][STOCK] POS amount for move %s from order %s: incl=%s excl=%s",
                move.id,
                pos_order.name,
                amount,
                subtotal,
            )
            return amount, amount - subtotal

        if move.sale_line_id:
            return move.sale_line_id.price_total or 0.0, (move.sale_line_id.price_total or 0.0) - (move.sale_line_id.price_subtotal or 0.0)

        if move.purchase_line_id:
            amount, subtotal = self._get_contact_purchase_amounts(move)
            return amount, amount - subtotal

        return 0.0, 0.0

    def _get_contact_purchase_amounts(self, move):
        purchase_line = move.purchase_line_id
        purchase_order = purchase_line.order_id
        posted_bills = purchase_order.invoice_ids.filtered(
            lambda inv: inv.state == 'posted' and inv.move_type in ('in_invoice', 'in_refund')
        )
        amount = 0.0
        subtotal = 0.0

        for bill in posted_bills:
            invoice_lines = bill.invoice_line_ids.filtered(
                lambda line: line.product_id == move.product_id and line.display_type not in ('line_section', 'line_note')
            )
            amount += sum(invoice_lines.mapped('price_total'))
            subtotal += sum(invoice_lines.mapped('price_subtotal'))

        if amount:
            _logger.info(
                "[CONTACT REPORT][STOCK] Purchase amount for move %s from posted bills on %s: incl=%s excl=%s",
                move.id,
                purchase_order.name,
                amount,
                subtotal,
            )
            return amount, subtotal

        amount = purchase_line.price_total or 0.0
        subtotal = purchase_line.price_subtotal or 0.0
        _logger.info(
            "[CONTACT REPORT][STOCK] Purchase amount for move %s from PO fallback %s: incl=%s excl=%s",
            move.id,
            purchase_order.name,
            amount,
            subtotal,
        )
        return amount, subtotal
