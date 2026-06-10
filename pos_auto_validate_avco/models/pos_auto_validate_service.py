# -*- coding: utf-8 -*-
import logging
from markupsafe import escape as html_escape
from markupsafe import Markup
from odoo import models

_logger = logging.getLogger(__name__)

# Origin substring that identifies SHOP1 outgoing deliveries.
# Change this if your POS shop origin prefix changes.
_SHOP_ORIGIN = 'SHOP1'


class PosAutoValidateService(models.AbstractModel):
    """
    Central dispatch service for POS auto-validation.

    Replaces three Odoo automation rules:
      - Auto-Validate POS on Purchase Receipt      (automations/3)
      - Auto-Validate POS Picking on Return/Exchange (automations/4)
      - AUTO-VALIDATION-ON-MANUFACTURING             (automations/5)

    Anglo-Saxon + AVCO design:
      AVCO is captured BEFORE and AFTER super()._action_done() so every
      outgoing delivery is validated at the correct post-receipt AVCO.
      Price difference entries (514500) are handled by pos_neg_stock_anglosaxon;
      this module only reads the final standard_price and logs it.
    """

    _name = 'pos.auto.validate.service'
    _description = 'POS Auto-Validate — AVCO-aware Anglo-Saxon Dispatch'

    def _html_text(self, value):
        return html_escape(value or '')

    def _html_qty(self, qty):
        return '%.4g' % (qty or 0.0)

    def _html_move_sentence(self, product, qty, source=None, dest=None,
                            direction='outgoing', extra=''):
        color = '#168039' if direction == 'incoming' else '#b42318'
        label = 'Incoming stock' if direction == 'incoming' else 'Outgoing stock'
        sign = '+' if direction == 'incoming' else '-'
        source_name = source.display_name if source else False
        dest_name = dest.display_name if dest else False
        route = ''
        if source_name and dest_name:
            route = ' from <b>%s</b> to <b>%s</b>' % (
                self._html_text(source_name),
                self._html_text(dest_name),
            )
        suffix = ' %s' % extra if extra else ''
        return (
            "<span style='color:%s;font-weight:600'>%s</span>: "
            "<b>%s%s</b> units of <b>%s</b>%s.%s"
        ) % (
            color,
            label,
            sign,
            self._html_qty(qty),
            self._html_text(product.display_name),
            route,
            suffix,
        )

    def _html_record_moves(self, record):
        if not getattr(record, 'move_ids', False):
            return ''

        lines = []
        for move in record.move_ids.filtered(lambda m: m.state == 'done'):
            qty = move.quantity or move.product_uom_qty
            if not qty:
                continue
            if move.location_dest_id.usage == 'internal':
                lines.append(
                    '<li>%s</li>' % self._html_move_sentence(
                        move.product_id,
                        qty,
                        move.location_id,
                        move.location_dest_id,
                        direction='incoming',
                    )
                )
            elif move.location_id.usage == 'internal':
                lines.append(
                    '<li>%s</li>' % self._html_move_sentence(
                        move.product_id,
                        qty,
                        move.location_id,
                        move.location_dest_id,
                        direction='outgoing',
                    )
                )

        if not lines:
            return ''
        return (
            "<p style='margin:4px 0'>Stock movement on this document:</p>"
            "<ul style='margin:2px 0'>%s</ul>"
        ) % ''.join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC ENTRY POINTS  (called by stock_picking / mrp_production overrides)
    # ─────────────────────────────────────────────────────────────────────────

    def run_on_receipt(self, picking, avco_before, avco_after):
        """Trigger: purchase receipt just validated."""
        _logger.info('[AVS] receipt trigger → %s', picking.name)
        products = self._done_products(picking)
        if not products:
            _logger.debug('[AVS] receipt %s: no done moves, abort', picking.name)
            return
        candidates = self._find_by_origin(products)
        results = self._process_pickings(candidates, avco_after)
        self._post_source_chatter(picking, 'Purchase Receipt', avco_before, avco_after, results)

    def run_on_return(self, picking, avco_before, avco_after):
        """Trigger: any customer return picking (COD or standard) just validated."""
        _logger.info('[AVS] return trigger → %s', picking.name)
        products = self._done_products(picking)
        if not products:
            _logger.debug('[AVS] return %s: no done moves, abort', picking.name)
            return
        candidates = self._find_by_origin(products)
        results = self._process_pickings(candidates, avco_after)
        self._post_source_chatter(picking, 'Customer Return', avco_before, avco_after, results)

    def run_on_manufacturing(self, mo, avco_before, avco_after):
        """Trigger: manufacturing order just marked done."""
        _logger.info('[AVS] MO trigger → %s  product: %s',
                     mo.name, mo.product_id.display_name)
        product = mo.product_id
        if not product:
            _logger.warning('[AVS] MO %s: no product_id, abort', mo.name)
            return
        candidates = self._find_by_pos_type(product)
        results = self._process_pickings(candidates, avco_after)
        self._post_mo_chatter(mo, avco_before, avco_after, results)

    # ─────────────────────────────────────────────────────────────────────────
    # CANDIDATE SEARCH
    # ─────────────────────────────────────────────────────────────────────────

    def _done_products(self, picking):
        """Products on moves that are now done (called after super())."""
        return picking.move_ids.filtered(
            lambda m: m.state == 'done'
        ).mapped('product_id')

    def _find_by_origin(self, products):
        """Receipt / return: SHOP1 origin filter."""
        return self._search_and_assign([
            ('state', 'in', ['confirmed', 'waiting', 'assigned']),
            ('picking_type_code', '=', 'outgoing'),
            ('origin', 'ilike', _SHOP_ORIGIN),
            ('move_ids.product_id', 'in', products.ids),
        ])

    def _find_by_pos_type(self, product):
        """MO: match by POS operation type name (mirrors original automation #3)."""
        return self._search_and_assign([
            ('state', 'in', ['confirmed', 'waiting', 'assigned']),
            ('picking_type_code', '=', 'outgoing'),
            ('picking_type_id.name', 'ilike', 'pos'),
            ('move_ids.product_id', '=', product.id),
        ])

    def _search_and_assign(self, domain):
        """
        Search candidate outgoing pickings, attempt action_assign on waiting
        ones, then return only the ones that are now assigned.
        """
        pickings = self.env['stock.picking'].search(
            domain, order='scheduled_date asc'
        )
        if not pickings:
            _logger.debug('[AVS] no candidates found for domain %s', domain)
            return pickings

        waiting = pickings.filtered(lambda p: p.state in ['confirmed', 'waiting'])
        if waiting:
            _logger.debug('[AVS] action_assign on %d waiting pickings', len(waiting))
            waiting.action_assign()

        assigned = pickings.filtered(lambda p: p.state == 'assigned')
        _logger.info('[AVS] %d / %d pickings ready after assign',
                     len(assigned), len(pickings))
        return assigned

    # ─────────────────────────────────────────────────────────────────────────
    # MOVE LINE BUILDER  — partial-aware (FIFO lot selection, AVCO costing)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_move_lines(self, picking):
        """
        For every active move on the picking:
          • check on-hand quants at the source location
          • fill as much as available  (partial OK — backorder handles the rest)
          • rebuild move_line_ids from quants sorted by in_date (oldest first)
          • write move.quantity = fill_qty, move.picked = True

        Returns:
            any_fulfilled (bool)  — True if at least one move got stock
            is_partial    (bool)  — True if any move was under-filled
            detail        (list)  — HTML strings, one per move, for chatter
        """
        any_fulfilled = False
        is_partial = False
        detail = []

        active_moves = picking.move_ids.filtered(
            lambda m: m.state not in ['done', 'cancel']
        )
        if not active_moves:
            _logger.debug('[AVS] picking %s: no active moves', picking.name)
            return False, False, ['No active moves on this delivery.']

        for move in active_moves:
            product = move.product_id
            demanded = move.product_uom_qty

            quants = self.env['stock.quant'].search([
                ('product_id',  '=', product.id),
                ('location_id', '=', move.location_id.id),
                ('quantity',    '>',  0),
            ])
            available = sum(quants.mapped('quantity'))

            _logger.debug(
                '[AVS]   move %s | %s | demanded=%.4f | available=%.4f',
                move.id, product.display_name, demanded, available
            )

            if available <= 0:
                detail.append(
                    "<span style='color:#b42318;font-weight:600'>Outgoing stock</span>: "
                    "<b>%s</b> could not be delivered because there was no stock "
                    "available. <b>%s</b> units remain open."
                    % (self._html_text(product.display_name), self._html_qty(demanded))
                )
                _logger.info('[AVS]   %s: zero stock, will go to backorder',
                             product.display_name)
                continue

            fill_qty = min(available, demanded)

            if fill_qty < demanded:
                is_partial = True
                detail.append(
                    "%s <span style='color:#875A7B'>%s units remain open.</span>"
                    % (
                        self._html_move_sentence(
                            product,
                            fill_qty,
                            move.location_id,
                            move.location_dest_id,
                            direction='outgoing',
                        ),
                        self._html_qty(demanded - fill_qty),
                    )
                )
                _logger.info('[AVS]   %s: partial %.4g / %.4g',
                             product.display_name, fill_qty, demanded)
            else:
                detail.append(
                    self._html_move_sentence(
                        product,
                        fill_qty,
                        move.location_id,
                        move.location_dest_id,
                        direction='outgoing',
                        extra='The delivery is fully completed.',
                    )
                )

            # Rebuild move lines from quants (oldest-in-date first for lot tracing)
            move.move_line_ids.unlink()
            remaining = fill_qty
            for quant in quants.sorted(key=lambda q: q.in_date or ''):
                if remaining <= 0:
                    break
                take = min(quant.quantity, remaining)
                self.env['stock.move.line'].create({
                    'move_id':          move.id,
                    'picking_id':       picking.id,
                    'product_id':       product.id,
                    'product_uom_id':   move.product_uom.id,
                    'location_id':      move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'quantity':         take,
                    'lot_id':     quant.lot_id.id     if quant.lot_id     else False,
                    'package_id': quant.package_id.id if quant.package_id else False,
                    'owner_id':   quant.owner_id.id   if quant.owner_id   else False,
                })
                remaining -= take

            move.write({'quantity': fill_qty, 'picked': True})
            any_fulfilled = True

        return any_fulfilled, is_partial, detail

    # ─────────────────────────────────────────────────────────────────────────
    # VALIDATE ONE PICKING
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_one(self, picking):
        """
        Validate a single outgoing picking.

        Context flags:
          skip_immediate=True     — move lines already built, skip qty dialog
          skip_backorder=True     — skip the backorder confirmation wizard
          cancel_backorder=False  — but DO auto-create the backorder (partial fills)
          skip_activity_done=True — suppress "schedule activity" popup

        Returns: (status: 'validated'|'partial'|'failed',  detail: str)
        """
        try:
            with self.env.cr.savepoint():
                picking.with_context(
                    skip_immediate=True,
                    skip_backorder=True,
                    cancel_backorder=False,
                    skip_activity_done=True,
                )._action_done()

            backorder = self.env['stock.picking'].search([
                ('backorder_id', '=', picking.id),
                ('state', 'not in', ['done', 'cancel']),
            ], limit=1)

            if backorder:
                _logger.info('[AVS] partial validated: %s → backorder %s',
                             picking.name, backorder.name)
                return ('partial',
                        'A backorder named <b>%s</b> was created for the remaining units.'
                        % self._html_text(backorder.name))

            _logger.info('[AVS] fully validated: %s', picking.name)
            return ('validated', 'All quantities were delivered.')

        except Exception as exc:
            _logger.exception('[AVS] FAILED to validate picking %s', picking.name)
            return ('failed', str(exc)[:300])

    # ─────────────────────────────────────────────────────────────────────────
    # PROCESS ALL CANDIDATES
    # ─────────────────────────────────────────────────────────────────────────

    def _process_pickings(self, pickings, avco_after):
        """
        Build move lines and validate every candidate picking.
        Posts a short note on each picking.
        Returns results dict for the source record chatter.
        """
        results = {
            'validated': [],   # [(name, move_detail, val_detail), ...]
            'partial':   [],
            'skipped':   [],   # [(name, move_detail), ...]
            'failed':    [],
        }

        if not pickings:
            _logger.info('[AVS] no assigned candidates — nothing to dispatch')
            return results

        for picking in pickings:
            _logger.info('[AVS] processing: %s (state=%s)',
                         picking.name, picking.state)

            any_ok, is_partial, move_detail = self._build_move_lines(picking)

            if not any_ok:
                results['skipped'].append((picking.name, move_detail))
                picking.message_post(
                    body=Markup(self._html_skipped(move_detail)),
                    subtype_xmlid='mail.mt_note',
                )
                _logger.info('[AVS] skipped: %s (no stock for any move)', picking.name)
                continue

            status, val_detail = self._validate_one(picking)
            results[status].append((picking.name, move_detail, val_detail))

            picking.message_post(
                body=Markup(self._html_picking_note(
                    status, move_detail, val_detail, avco_after, picking
                )),
                subtype_xmlid='mail.mt_note',
            )

        _logger.info(
            '[AVS] dispatch complete | validated=%d partial=%d skipped=%d failed=%d',
            len(results['validated']), len(results['partial']),
            len(results['skipped']),  len(results['failed']),
        )
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # HTML BUILDERS — chatter content
    # ─────────────────────────────────────────────────────────────────────────

    def _html_avco_table(self, avco_before, avco_after):
        """
        AVCO comparison table for the source record chatter.
        Shows before → after for every product, flags changes, and explains
        the price-difference entry when the AVCO moved.
        """
        currency = self.env.company.currency_id.name or 'KES'
        rows = []

        for pid, cost_before in avco_before.items():
            cost_after = avco_after.get(pid, cost_before)
            product    = self.env['product.product'].browse(pid)
            diff       = cost_after - cost_before

            if abs(diff) > 0.001:
                sign = '+' if diff > 0 else ''
                change_cell = (
                    "<td style='color:#875A7B'>The cost changed by <b>%s%.2f</b>.</td>"
                    % (sign, diff)
                )
                # Explain the 514500 price-difference entry that
                # pos_neg_stock_anglosaxon already posted automatically.
                note = (
                    "<tr><td colspan='5' style='padding-left:14px;color:#777;"
                    "font-size:11px'>"
                    "Odoo posted the stock value correction automatically through "
                    "the Price Differences account.</td></tr>"
                )
            else:
                change_cell = "<td style='color:gray'>The cost did not change.</td>"
                note = ''

            rows.append(
                "<tr>"
                "<td><b>%s</b></td>"
                "<td style='color:gray'>%s %.2f</td>"
                "<td>to</td>"
                "<td><b style='color:green'>%s %.2f</b></td>"
                "%s"
                "</tr>%s"
                % (self._html_text(product.display_name),
                   currency, cost_before,
                   currency, cost_after,
                   change_cell, note)
            )

        if not rows:
            return ''

        return (
            "<b>Cost used for automatic delivery validation</b><br/>"
            "<small style='color:#555'>"
            "The delivery orders below were validated using the latest average cost "
            "shown in the After column."
            "</small>"
            "<table style='margin:6px 0;border-collapse:collapse;font-size:12px'>"
            "<tr style='background:#f0f0f0'>"
            "<th style='padding:2px 8px'>Product</th>"
            "<th>AVCO Before</th><th></th>"
            "<th>AVCO After</th><th>Change</th>"
            "</tr>"
            "%s"
            "</table>"
        ) % ''.join(rows)

    def _html_results_block(self, results):
        """Summary section: validated / partial / skipped / failed."""
        parts = []

        if results['validated']:
            items = ''.join(
                "<li><b>%s</b><ul style='margin:1px 0'>%s</ul></li>"
                % (name, ''.join("<li>%s</li>" % d for d in detail))
                for name, detail, _ in results['validated']
            )
            parts.append(
                "<b style='color:#168039'>Completed delivery orders (%d)</b>"
                "<ul>%s</ul>" % (len(results['validated']), items)
            )

        if results['partial']:
            items = ''.join(
                "<li><b>%s</b> &mdash; %s"
                "<ul style='margin:1px 0'>%s</ul></li>"
                % (name, val_detail,
                   ''.join("<li>%s</li>" % d for d in detail))
                for name, detail, val_detail in results['partial']
            )
            parts.append(
                "<b style='color:#875A7B'>Partially completed delivery orders (%d)</b>"
                "<ul>%s</ul>" % (len(results['partial']), items)
            )

        if results['skipped']:
            items = ''.join(
                "<li><b>%s</b><ul style='margin:1px 0'>%s</ul></li>"
                % (name, ''.join("<li>%s</li>" % d for d in detail))
                for name, detail in results['skipped']
            )
            parts.append(
                "<b style='color:gray'>Delivery orders left open because stock was unavailable (%d)</b>"
                "<ul>%s</ul>"
                "<small style='color:#888'>These deliveries stay open and will be "
                "auto-dispatched on the next receipt, return, or MO.</small>"
                % (len(results['skipped']), items)
            )

        if results['failed']:
            items = ''.join(
                "<li><b>%s</b>: <code>%s</code></li>"
                % (name, val_detail)
                for name, _, val_detail in results['failed']
            )
            parts.append(
                "<b style='color:#b42318'>Delivery orders that could not be validated (%d)</b>"
                "<ul>%s</ul>" % (len(results['failed']), items)
            )

        if not parts:
            parts.append(
                "<i style='color:gray'>"
                "No open SHOP1 delivery orders needed these products."
                "</i>"
            )

        return ''.join(parts)

    def _post_source_chatter(self, record, trigger_label,
                              avco_before, avco_after, results):
        """Full report posted on the triggering receipt or return picking."""
        total = sum(len(v) for v in results.values())
        body = (
            "<div style='border-left:4px solid #875A7B;padding:4px 0 4px 10px'>"
            "<b>POS auto-validation report</b><br/>"
            "<small>This report was created after <b>%s</b> was completed: "
            "<b>%s</b>.</small><br/>"
            "%s"
            "<br/>"
            "%s"
            "<hr style='margin:6px 0;border:none;border-top:1px solid #ddd'/>"
            "<b>Delivery result</b> "
            "<small style='color:#888'>%d delivery order(s) checked.</small><br/>"
            "%s"
            "</div>"
        ) % (
            trigger_label, record.name,
            self._html_record_moves(record),
            self._html_avco_table(avco_before, avco_after),
            total,
            self._html_results_block(results),
        )
        record.message_post(body=Markup(body), subtype_xmlid='mail.mt_note')

    def _post_mo_chatter(self, mo, avco_before, avco_after, results):
        """Full report posted on the Manufacturing Order."""
        product = mo.product_id
        # Narrow the AVCO dicts to just this product
        ab = {product.id: avco_before.get(product.id, 0)}
        aa = {product.id: avco_after.get(product.id, 0)}
        total = sum(len(v) for v in results.values())
        body = (
            "<div style='border-left:4px solid #875A7B;padding:4px 0 4px 10px'>"
            "<b>POS auto-validation report</b><br/>"
            "<small>This report was created after manufacturing order "
            "<b>%s</b> was completed.</small><br/>"
            "<small>Finished product: <b>%s</b>.</small><br/><br/>"
            "%s"
            "<hr style='margin:6px 0;border:none;border-top:1px solid #ddd'/>"
            "<b>Delivery result</b> "
            "<small style='color:#888'>%d delivery order(s) checked.</small><br/>"
            "%s"
            "</div>"
        ) % (
            mo.name, self._html_text(product.display_name),
            self._html_avco_table(ab, aa),
            total,
            self._html_results_block(results),
        )
        mo.message_post(body=Markup(body), subtype_xmlid='mail.mt_note')

    def _html_picking_note(self, status, move_detail, val_detail,
                            avco_after, picking):
        """Short note posted on each outgoing picking that was processed."""
        icons = {
            'validated': "<b style='color:#168039'>This delivery was completed automatically.</b>",
            'partial':   "<b style='color:#875A7B'>This delivery was partially completed automatically.</b>",
            'failed':    "<b style='color:#b42318'>This delivery could not be completed automatically.</b>",
        }
        currency = self.env.company.currency_id.name or 'KES'
        picking_product_ids = set(picking.move_ids.mapped('product_id').ids)

        avco_lines = ''.join(
            "<li>%s: <b>%s %.4g / unit</b></li>"
            % (
                self._html_text(self.env['product.product'].browse(pid).display_name),
                currency,
                cost,
            )
            for pid, cost in avco_after.items()
            if pid in picking_product_ids
        ) or '<li>see product moves</li>'

        detail_lines = ''.join("<li>%s</li>" % d for d in move_detail)
        partial_note = (
            "<br/><b>Remaining delivery:</b> %s" % val_detail
        ) if status == 'partial' else ''

        return (
            "<div style='border-left:3px solid #b42318;padding:2px 0 2px 8px'>"
            "%s<br/>"
            "<small>"
            "<b>Cost used when this delivery was validated:</b>"
            "<ul style='margin:2px 0'>%s</ul>"
            "<i>Odoo posted the cost of goods sold using the cost above.</i>"
            "%s<br/><br/>"
            "<b>Stock movement:</b><ul style='margin:2px 0'>%s</ul>"
            "</small>"
            "</div>"
        ) % (
            icons.get(status, status),
            avco_lines,
            partial_note,
            detail_lines,
        )

    def _html_skipped(self, move_detail):
        """Note for a picking skipped due to zero available stock."""
        detail_lines = ''.join("<li>%s</li>" % d for d in move_detail)
        return (
            "<div style='border-left:3px solid #AAAAAA;padding:2px 0 2px 8px'>"
            "<b style='color:gray'>This delivery stayed open.</b><br/>"
            "<small>"
            "No stock was available for the products on this delivery order. "
            "Odoo will try again after the next purchase receipt, customer return, "
            "or completed manufacturing order.<br/>"
            "<b>Stock movement:</b>"
            "<ul style='margin:2px 0'>%s</ul>"
            "</small>"
            "</div>"
        ) % detail_lines
