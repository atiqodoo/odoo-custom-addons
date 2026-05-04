# -*- coding: utf-8 -*-
"""stock_picking.py

Two behavioural extensions on stock.picking:

1. Force Validation (outgoing / POS)
   ──────────────────────────────────
   When button_validate() is called on an outgoing picking that is linked to a
   POS order, this module bypasses the normal stock-availability wizard and forces
   quantity_done = product_uom_qty on every pending move.  Odoo's standard
   _action_done() then runs, creating negative stock.valuation.layers at the
   current AVCO (falling back to standard_price when qty_on_hand == 0).

   After super() completes, _tag_pos_negative_svls() marks the new negative SVLs
   with pos_negative_origin=True and links them to the source pos.order so the
   FIFO reconciliation logic can target them precisely.

2. Price Difference Trigger (incoming / vendor receipt)
   ──────────────────────────────────────────────────────
   _action_done() carries a PRE-hook that snapshots each product's negative
   qty_available BEFORE super() processes the receipt.  After super() completes
   (which updates on-hand qty and creates receipt SVLs), a POST-hook calls
   stock_move._reconcile_neg_layers_for_product() for each product that had
   negative stock, generating the Anglo-Saxon price difference journal entries.
"""

import logging
from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    """Extends stock.picking for POS force-validation and AVCO price difference triggers.

    See module docstring above for full behavioural overview.
    """

    _inherit = 'stock.picking'

    # ─────────────────────────────────────────────────────────────────────────
    # POS Detection Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _is_pos_picking(self):
        """Determine whether this picking originated from a POS order.

        Uses a cascading three-strategy detection to be robust across Odoo 18
        POS configurations that may or may not expose a direct session field:

        Strategy 1 — Direct ``pos_session_id`` field on the picking (preferred).
        Strategy 2 — Reverse lookup via ``pos.order.picking_ids``.
        Strategy 3 — Origin string equality match against ``pos.order.name``.

        Returns:
            bool: True if the picking is POS-linked, False otherwise.
        """
        self.ensure_one()

        # Strategy 1: direct session link (set by POS module on outgoing picks)
        if hasattr(self, 'pos_session_id') and self.pos_session_id:
            _logger.debug(
                '[NegStock] %s: POS session link found → %s',
                self.name, self.pos_session_id.name,
            )
            return True

        # Strategy 2: reverse relational lookup (most reliable when field absent)
        pos_order = self.env['pos.order'].search(
            [('picking_ids', 'in', self.ids)], limit=1
        )
        if pos_order:
            _logger.debug(
                '[NegStock] %s: linked to POS order %s via picking_ids',
                self.name, pos_order.name,
            )
            return True

        # Strategy 3: origin string match
        if self.origin:
            pos_by_name = self.env['pos.order'].search(
                [('name', '=', self.origin)], limit=1
            )
            if pos_by_name:
                _logger.debug(
                    '[NegStock] %s: linked to POS order %s via origin',
                    self.name, pos_by_name.name,
                )
                return True

        return False

    def _get_linked_pos_order(self):
        """Return the pos.order associated with this picking (if any).

        Tries picking_ids reverse lookup first, falls back to origin match.

        Returns:
            pos.order: First matching record, or empty recordset if none found.
        """
        self.ensure_one()
        order = self.env['pos.order'].search(
            [('picking_ids', 'in', self.ids)], limit=1
        )
        if not order and self.origin:
            order = self.env['pos.order'].search(
                [('name', '=', self.origin)], limit=1
            )
        return order

    # ─────────────────────────────────────────────────────────────────────────
    # Force Validation — button_validate override
    # ─────────────────────────────────────────────────────────────────────────

    def button_validate(self):
        """Override to force-validate POS outgoing pickings without availability check.

        For POS-linked outgoing pickings:
          1. Calls _force_pos_quantities() to set qty_done = demand on all moves.
          2. Calls _action_done() directly, bypassing the Immediate Transfer and
             Backorder wizard dialogs that would otherwise pop up.

        For all other pickings (non-POS or non-outgoing), the standard super()
        flow is preserved completely.

        Returns:
            dict | bool: Wizard action dict for regular pickings, or True for
                         force-validated POS pickings.

        Note:
            This method intentionally does NOT call super() for the POS subset.
            The _action_done() call replicates the final step of button_validate()
            after all wizard interactions have been skipped.
        """
        pos_out = self.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p._is_pos_picking()
        )
        regular = self - pos_out

        result = True

        # Handle normal pickings the standard way
        if regular:
            result = super(StockPicking, regular).button_validate()

        # Force-validate POS outgoing pickings
        if pos_out:
            _logger.info(
                '[NegStock] button_validate: %d POS outgoing picking(s) will be '
                'force-validated: %s',
                len(pos_out),
                ', '.join(pos_out.mapped('name')),
            )
            for picking in pos_out:
                picking._force_pos_quantities()

            # Call _action_done directly with cancel_backorder=True (Odoo 18 convention)
            pos_out.with_context(cancel_backorder=True)._action_done()

        return result

    def _force_pos_quantities(self):
        """Set quantity_done = product_uom_qty on all pending moves in this picking.

        Sets move.quantity (the Odoo 18 done qty field).  The field setter
        automatically cascades to move_line.quantity via _set_quantity_done,
        so this works regardless of the "Use Detailed Operations" setting.

        Emits structured log lines per product, including AVCO cost and exposure
        value (shortfall × AVCO) so the accountant can audit the event later.

        Warnings
        --------
        - Logs WARNING when a product's standard_price == 0.  The resulting
          negative SVL will carry zero unit_cost, making COGS = 0 for those
          units.  The accountant should correct this via a manual JE or by
          setting the product cost before the sale.
        - Logs INFO for every unit going negative (shortfall > 0).

        Side Effects:
            Mutates move.quantity in-place (cascades to move_line.quantity).
        """
        self.ensure_one()
        for move in self.move_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        ):
            product = move.product_id
            demand = move.product_uom_qty
            current_qty = product.qty_available  # global on-hand (AVCO is global)

            if current_qty < demand:
                shortfall = demand - max(current_qty, 0.0)
                avco = product.standard_price

                if avco == 0.0:
                    _logger.warning(
                        '[NegStock] ZERO-COST WARNING | Product: "%s" (id=%d) | '
                        'Picking: %s | standard_price=0.00 | '
                        'Negative SVL will be valued at 0.  COGS understated.  '
                        'Set a product cost before this sale to avoid valuation errors.',
                        product.display_name, product.id, self.name,
                    )
                else:
                    _logger.info(
                        '[NegStock] OVERSELL | Product: "%s" (id=%d) | '
                        'Picking: %s | shortfall=%.4f units | AVCO=%.6f | '
                        'Exposure value=%.4f',
                        product.display_name, product.id,
                        self.name, shortfall, avco, shortfall * avco,
                    )

            # In Odoo 18, move.quantity (done) is set directly; its setter
            # cascades to move_line.quantity automatically via _set_quantity_done.
            if move.quantity < demand:
                move.quantity = demand

    # ─────────────────────────────────────────────────────────────────────────
    # _action_done: Pre / Post Hooks
    # ─────────────────────────────────────────────────────────────────────────

    def _action_done(self):
        """Inject pre-snapshot and post-reconciliation hooks around standard processing.

        PRE-HOOK (runs before super):
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        For every incoming picking move whose product currently has
        qty_available < 0, capture a snapshot dict:

            {(picking_id, move_id, product_id): {
                neg_qty_before    : absolute negative qty at this moment,
                units_at_risk     : min(neg_qty, received_qty) — max reconcilable,
                incoming_unit_cost: move._get_pos_neg_incoming_cost(),
                picking_id        : int,
            }}

        This snapshot must happen BEFORE super() because super() updates
        qty_available and the original negative exposure would be lost.

        Also records the set of outgoing POS move IDs so the POST-HOOK can tag
        the newly created negative SVLs after Odoo creates them.

        POST-HOOK (runs after super):
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        1. _tag_pos_negative_svls() — sets pos_negative_origin=True and
           pos_order_id on any SVL created from a POS force-validated move.

        2. _reconcile_neg_layers_for_product() (on stock.move) — runs the
           FIFO reconciliation algorithm, creates price difference JEs, and
           writes pos.neg.reconciliation.line audit records.

        Note:
            stock.picking._action_done() in Odoo 18 takes no parameters.
            cancel_backorder only exists on stock.move._action_done().

        Returns:
            bool: Value returned by super()._action_done().
        """
        # ── PRE-HOOK: Snapshot negative exposure before receipt changes stock ─

        receipt_snapshots = {}
        incoming_pickings = self.filtered(lambda p: p.picking_type_code == 'incoming')

        for picking in incoming_pickings:
            for move in picking.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')
                and m.product_id.type == 'product'
            ):
                product = move.product_id
                current_qty = product.qty_available

                if current_qty < 0:
                    incoming_cost = move._get_pos_neg_incoming_cost()
                    key = (picking.id, move.id, product.id)
                    receipt_snapshots[key] = {
                        'product_id': product.id,
                        'neg_qty_before': abs(current_qty),
                        'units_at_risk': min(abs(current_qty), move.product_uom_qty),
                        'incoming_unit_cost': incoming_cost,
                        'picking_id': picking.id,
                    }
                    _logger.info(
                        '[NegStock] PRE-SNAPSHOT | Picking: %s | Product: "%s" | '
                        'neg_qty=%.4f | units_at_risk=%.4f | incoming_cost=%.6f',
                        picking.name,
                        product.display_name,
                        abs(current_qty),
                        receipt_snapshots[key]['units_at_risk'],
                        incoming_cost,
                    )

        # ── PRE-HOOK: Record POS outgoing move IDs before _action_done ────────

        pos_out_move_ids = set()
        for picking in self.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p._is_pos_picking()
        ):
            for move in picking.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')
            ):
                pos_out_move_ids.add(move.id)

        _logger.debug(
            '[NegStock] _action_done: %d incoming snapshot(s), %d POS outgoing move(s)',
            len(receipt_snapshots),
            len(pos_out_move_ids),
        )

        # ── STANDARD ODOO PROCESSING ──────────────────────────────────────────

        result = super()._action_done()

        # ── POST-HOOK 1: Tag negative SVLs from POS oversells ─────────────────

        if pos_out_move_ids:
            self._tag_pos_negative_svls(pos_out_move_ids)

        # ── POST-HOOK 2: FIFO reconciliation for incoming receipts ────────────

        if receipt_snapshots:
            # Aggregate by product (a receipt may have multiple moves per product)
            by_product = {}
            for key, snap in receipt_snapshots.items():
                pid = snap['product_id']
                if pid not in by_product:
                    by_product[pid] = snap.copy()
                else:
                    # Multiple moves for same product — add their risk units
                    by_product[pid]['units_at_risk'] += snap['units_at_risk']
                    _logger.debug(
                        '[NegStock] Multiple moves for product_id=%d — '
                        'aggregated units_at_risk=%.4f',
                        pid, by_product[pid]['units_at_risk'],
                    )

            for pid, snap in by_product.items():
                source_picking = self.env['stock.picking'].browse(snap['picking_id'])
                self.env['stock.move']._reconcile_neg_layers_for_product(
                    product_id=pid,
                    incoming_qty=snap['units_at_risk'],
                    incoming_unit_cost=snap['incoming_unit_cost'],
                    source_picking=source_picking,
                )

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Post-Processing Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _tag_pos_negative_svls(self, pos_move_ids):
        """Tag freshly created negative SVLs from POS force-validated outgoing moves.

        After super()._action_done() completes, query for SVLs whose
        stock_move_id is in the recorded POS move set AND that are negative AND
        not yet tagged (pos_negative_origin=False).  Write the flag and link the
        source pos.order so FIFO reconciliation can target them later.

        Args:
            pos_move_ids (set[int]): stock.move IDs that were force-validated
                                     in this _action_done call.

        Side Effects:
            Writes pos_negative_origin=True and pos_order_id on matching SVLs.
        """
        if not pos_move_ids:
            return

        neg_svls = self.env['stock.valuation.layer'].search([
            ('stock_move_id', 'in', list(pos_move_ids)),
            ('quantity', '<', 0),
            ('pos_negative_origin', '=', False),
        ])

        if not neg_svls:
            _logger.debug(
                '[NegStock] _tag_pos_negative_svls: no untagged negative SVLs found '
                'for move_ids=%s', list(pos_move_ids),
            )
            return

        for svl in neg_svls:
            picking = svl.stock_move_id.picking_id
            pos_order = self.env['stock.picking'].browse(picking.id)._get_linked_pos_order()

            svl.write({
                'pos_negative_origin': True,
                'pos_order_id': pos_order.id if pos_order else False,
            })

            _logger.info(
                '[NegStock] Tagged SVL id=%d | product="%s" | qty=%.4f | '
                'unit_cost=%.6f | pos_order=%s',
                svl.id,
                svl.product_id.display_name,
                svl.quantity,
                svl.unit_cost,
                pos_order.name if pos_order else 'N/A',
            )

            # Post audit message on the POS order chatter for visibility
            if pos_order:
                pos_order.message_post(
                    body=(
                        '<b>[Negative Stock Created]</b><br/>'
                        f'Product: {svl.product_id.display_name}<br/>'
                        f'Qty oversold: {abs(svl.quantity):.2f}<br/>'
                        f'AVCO at sale: {svl.unit_cost:.4f}<br/>'
                        f'Exposure value: {abs(svl.value):.4f}<br/>'
                        f'SVL reference: #{svl.id}'
                    )
                )
