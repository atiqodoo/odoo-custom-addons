# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class CollectPendingItemsWizard(models.TransientModel):
    """
    Transient wizard that allows a user to confirm the collection of pending
    items by a customer.

    This wizard is launched from a paint.pending.collection record via the
    'Collect Pending Items' button (action_collect_items). It pre-populates
    its lines with every collection line that still has remaining_qty > 0,
    defaulting collect_qty to the full remaining quantity.

    On confirmation:
        1. Lines are matched to collection lines by positional index (not by
           wizard line ID, which is reassigned by Odoo on web_save).
        2. Quantities are validated.
        3. collected_qty is incremented on each collection line.
        4. An internal stock picking is created to return items from the
           holding location back to the POS source location, **including the
           lot_id** captured during the original outgoing move.
        5. The parent pending collection state is updated to 'partial' or
           'done'.

    Important: Both wizards (register + collect) use index-based line matching
    because Odoo's transient model reassigns IDs on web_save, making the
    original IDs from default_get unreliable at action_confirm time.
    """

    _name = 'collect.pending.items.wizard'
    _description = 'Collect Pending Items Wizard'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------

    pending_collection_id = fields.Many2one(
        'paint.pending.collection',
        string='Pending Collection',
        required=True,
        readonly=True,
        help='The pending collection record this wizard is processing.',
    )

    line_ids = fields.One2many(
        'collect.pending.items.wizard.line',
        'wizard_id',
        string='Items to Collect',
        help='Lines representing each product the customer is collecting now.',
    )

    collection_date = fields.Datetime(
        string='Collection Date',
        default=fields.Datetime.now,
        required=True,
        help='Date and time of the current collection event.',
    )

    notes = fields.Text(
        string='Collection Notes',
        help='Optional notes specific to this collection event.',
    )

    # -------------------------------------------------------------------------
    # DEFAULT GET
    # -------------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        """
        Pre-populate the wizard with lines from the pending collection.

        For each collection line that still has remaining_qty > 0, a wizard
        line is created with collect_qty defaulting to the full remaining
        quantity (collect all by default).

        Args:
            fields_list (list[str]): Fields requested by the view.

        Returns:
            dict: Default field values including pre-built line_ids.

        Logs:
            INFO  – Separator, context, and per-line data.
            WARNING – If pending_collection_id is not in context.
            INFO  – Final res summary.
        """
        _logger.info(
            "[COLLECT_WIZARD] default_get: "
            "════════════════════════════════════════════════",
        )
        _logger.info(
            "[COLLECT_WIZARD] default_get: === Called with fields: %s ===",
            fields_list,
        )

        res = super().default_get(fields_list)

        _logger.info("[COLLECT_WIZARD] default_get: Context = %s.", self._context)
        _logger.info("[COLLECT_WIZARD] default_get: Initial res = %s.", res)

        if 'pending_collection_id' in res and res['pending_collection_id']:
            pending = self.env['paint.pending.collection'].browse(
                res['pending_collection_id']
            )

            _logger.info(
                "[COLLECT_WIZARD] default_get: "
                "Pending Collection = '%s' (ID: %s).",
                pending.name, pending.id,
            )
            _logger.info(
                "[COLLECT_WIZARD] default_get: "
                "Collection has %d total line(s).",
                len(pending.collection_line_ids),
            )

            lines = []
            for idx, collection_line in enumerate(pending.collection_line_ids):
                if collection_line.remaining_qty > 0:
                    line_data = {
                        'collection_line_id': collection_line.id,
                        'product_id': collection_line.product_id.id,
                        'pending_qty': collection_line.remaining_qty,
                        'collect_qty': collection_line.remaining_qty,
                    }
                    _logger.info(
                        "[COLLECT_WIZARD] default_get: "
                        "Line %d: '%s' — remaining_qty=%.2f.",
                        idx + 1, collection_line.product_id.name,
                        collection_line.remaining_qty,
                    )
                    _logger.info(
                        "[COLLECT_WIZARD] default_get: Line data = %s.",
                        line_data,
                    )
                    lines.append((0, 0, line_data))
                else:
                    _logger.info(
                        "[COLLECT_WIZARD] default_get: "
                        "Line %d: '%s' skipped (remaining_qty=0).",
                        idx + 1, collection_line.product_id.name,
                    )

            res['line_ids'] = lines
            _logger.info(
                "[COLLECT_WIZARD] default_get: Created %d wizard line(s).",
                len(lines),
            )
        else:
            _logger.warning(
                "[COLLECT_WIZARD] default_get: "
                "No pending_collection_id found in context or res. "
                "Wizard will open empty.",
            )

        _logger.info("[COLLECT_WIZARD] default_get: Final res = %s.", res)
        _logger.info(
            "[COLLECT_WIZARD] default_get: "
            "════════════════════════════════════════════════",
        )
        return res

    # -------------------------------------------------------------------------
    # ACTION CONFIRM
    # -------------------------------------------------------------------------

    def action_confirm(self):
        """
        Process the customer's collection of pending items.

        Execution steps:
            1. Re-read pending collection lines fresh from DB (not from wizard
               line IDs, which are reassigned on web_save).
            2. Match wizard lines to collection lines by positional index,
               sorted by ID for deterministic ordering.
            3. Validate each quantity (non-negative, does not exceed remaining).
            4. For each item with collect_qty > 0:
                a. Increment collected_qty on the collection line.
                b. Create an internal return stock picking (holding → POS stock),
                   passing the lot_id stored on the collection line to satisfy
                   Odoo's lot-tracking validation for tinted products.
            5. Update the parent pending collection state:
                - All remaining_qty == 0  → 'done' + set date_collected.
                - Otherwise              → 'partial'.
            6. Post a chatter message on the pending collection.

        Returns:
            dict: An ir.actions.act_window action reopening the pending
                  collection form.

        Raises:
            UserError:       If no pending collection is linked or no items
                             are selected for collection.
            ValidationError: If a quantity is negative or exceeds remaining.

        Logs:
            INFO  – Step-by-step progress with quantities.
            DEBUG – Intermediate per-line details.
            WARNING – Skipped items (qty=0).
            ERROR – Stock move failures (re-raised after logging).
        """
        self.ensure_one()

        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "═══════════════════════════════════════════════",
        )
        _logger.info(
            "[COLLECT_WIZARD] action_confirm: === Called on wizard ID: %s ===",
            self.id,
        )

        if not self.pending_collection_id:
            _logger.error(
                "[COLLECT_WIZARD] action_confirm: "
                "No pending_collection_id set on wizard %s. Aborting.",
                self.id,
            )
            raise UserError(_('No pending collection found.'))

        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "Pending Collection = '%s' (ID: %s).",
            self.pending_collection_id.name, self.pending_collection_id.id,
        )

        # --- Read FRESH data from DB to avoid stale transient IDs ---
        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "Reading FRESH data from pending collection (bypassing wizard line IDs).",
        )
        pending = self.pending_collection_id
        collection_lines = (
            pending.collection_line_ids
            .filtered(lambda l: l.remaining_qty > 0)
            .sorted(lambda l: l.id)
        )
        wizard_lines = self.line_ids.sorted(lambda l: l.sequence)

        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "Collection lines with remaining qty = %d.",
            len(collection_lines),
        )
        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "Wizard lines = %d.",
            len(wizard_lines),
        )
        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "Matching lines by positional index (sequence-sorted wizard lines).",
        )

        # --- Index-based matching & validation ---
        items_to_collect = []

        for idx, collection_line in enumerate(collection_lines):
            if idx < len(wizard_lines):
                wizard_line = wizard_lines[idx]
                collect_qty = wizard_line.collect_qty
                _logger.info(
                    "[COLLECT_WIZARD] action_confirm: "
                    "Index %d matched → collection_line ID=%s ('%s') "
                    "↔ wizard_line ID=%s, collect_qty=%.2f.",
                    idx,
                    collection_line.id, collection_line.product_id.name,
                    wizard_line.id, collect_qty,
                )
            else:
                collect_qty = 0.0
                _logger.info(
                    "[COLLECT_WIZARD] action_confirm: "
                    "Index %d → no wizard line found for collection_line ID=%s. "
                    "Defaulting collect_qty=0.",
                    idx, collection_line.id,
                )

            _logger.info(
                "[COLLECT_WIZARD] action_confirm: "
                "Processing collection_line %s: product='%s', "
                "remaining=%.2f, collecting=%.2f.",
                collection_line.id, collection_line.product_id.name,
                collection_line.remaining_qty, collect_qty,
            )

            # Validate quantities
            if collect_qty < 0:
                _logger.error(
                    "[COLLECT_WIZARD] action_confirm: "
                    "Negative collect_qty (%.2f) for '%s'. Raising ValidationError.",
                    collect_qty, collection_line.product_id.name,
                )
                raise ValidationError(
                    _('Collection quantity cannot be negative for %s.')
                    % collection_line.product_id.name
                )

            if collect_qty > collection_line.remaining_qty:
                _logger.error(
                    "[COLLECT_WIZARD] action_confirm: "
                    "collect_qty (%.2f) exceeds remaining_qty (%.2f) for '%s'. "
                    "Raising ValidationError.",
                    collect_qty, collection_line.remaining_qty,
                    collection_line.product_id.name,
                )
                raise ValidationError(
                    _('Collection quantity (%s) cannot exceed remaining quantity (%s) for %s.')
                    % (collect_qty, collection_line.remaining_qty,
                       collection_line.product_id.name)
                )

            if collect_qty > 0:
                items_to_collect.append({
                    'collection_line_id': collection_line.id,
                    'product_id': collection_line.product_id.id,
                    'product_name': collection_line.product_id.name,
                    'collect_qty': collect_qty,
                })
                _logger.info(
                    "[COLLECT_WIZARD] action_confirm: "
                    "  ✓ Added to collection list (qty=%.2f).",
                    collect_qty,
                )
            else:
                _logger.info(
                    "[COLLECT_WIZARD] action_confirm: "
                    "  ✗ Not collecting '%s' (collect_qty=0).",
                    collection_line.product_id.name,
                )

        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "Items selected for collection: %d product(s).",
            len(items_to_collect),
        )

        if not items_to_collect:
            _logger.warning(
                "[COLLECT_WIZARD] action_confirm: "
                "No items selected. Raising UserError.",
            )
            raise UserError(_('No items selected for collection.'))

        # --- Process each item: update qty + create stock move ---
        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "Updating collection lines and creating return stock moves.",
        )

        for item in items_to_collect:
            collection_line = self.env['paint.pending.collection.line'].browse(
                item['collection_line_id']
            )

            _logger.info(
                "[COLLECT_WIZARD] action_confirm: "
                "Updating line %s — '%s': "
                "collected_qty %.2f → %.2f (adding %.2f).",
                collection_line.id, item['product_name'],
                collection_line.collected_qty,
                collection_line.collected_qty + item['collect_qty'],
                item['collect_qty'],
            )

            collection_line.collected_qty += item['collect_qty']

            _logger.info(
                "[COLLECT_WIZARD] action_confirm: "
                "  collected_qty after update = %.2f, remaining_qty = %.2f.",
                collection_line.collected_qty, collection_line.remaining_qty,
            )

            _logger.info(
                "[COLLECT_WIZARD] action_confirm: "
                "Creating return stock move for '%s' (qty=%.2f).",
                item['product_name'], item['collect_qty'],
            )

            try:
                self._create_return_stock_move(collection_line, item['collect_qty'])
                _logger.info(
                    "[COLLECT_WIZARD] action_confirm: "
                    "  ✓ Return stock move created for '%s'.",
                    item['product_name'],
                )
            except Exception as e:
                _logger.error(
                    "[COLLECT_WIZARD] action_confirm: "
                    "  ✗ Return stock move FAILED for '%s': %s",
                    item['product_name'], str(e),
                )
                raise

        # --- Update pending collection state ---
        all_collected = all(
            line.remaining_qty == 0
            for line in pending.collection_line_ids
        )
        total_collected = sum(item['collect_qty'] for item in items_to_collect)

        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "All items collected = %s. Total units in this batch = %.2f.",
            all_collected, total_collected,
        )

        if all_collected:
            pending.state = 'done'
            pending.date_collected = self.collection_date
            message = _('All items collected.')
            _logger.info(
                "[COLLECT_WIZARD] action_confirm: "
                "State updated to 'done'. date_collected = %s.",
                pending.date_collected,
            )
        else:
            pending.state = 'partial'
            message = _('Partial collection: %s items collected.') % total_collected
            _logger.info(
                "[COLLECT_WIZARD] action_confirm: "
                "State updated to 'partial'. %s total units collected in this batch.",
                total_collected,
            )

        if self.notes:
            message += f'\n{self.notes}'
            _logger.info(
                "[COLLECT_WIZARD] action_confirm: "
                "Collection notes appended to message.",
            )

        pending.message_post(body=message)
        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "Chatter message posted on pending collection '%s'.",
            pending.name,
        )

        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "=== Completed successfully: %d product(s), %.2f total units. ===",
            len(items_to_collect), total_collected,
        )
        _logger.info(
            "[COLLECT_WIZARD] action_confirm: "
            "═══════════════════════════════════════════════",
        )

        return {
            'name': _('Pending Collection'),
            'type': 'ir.actions.act_window',
            'res_model': 'paint.pending.collection',
            'res_id': pending.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # -------------------------------------------------------------------------
    # RETURN STOCK MOVE
    # -------------------------------------------------------------------------

    def _create_return_stock_move(self, collection_line, qty):
        """
        Create and validate an internal stock picking to return a collected
        item from the holding location back to the POS source location.

        CRITICAL — Lot/Serial Number Handling:
            Tinted products are configured with lot-tracking in Odoo. When the
            original outgoing move (POS stock → holding location) was validated
            in action_create_stock_moves(), the lot_id was captured and stored
            on the collection line (paint.pending.collection.line.lot_id).

            This method reads collection_line.lot_id and passes it explicitly
            into the stock.move.line when building the return picking. Without
            this, Odoo's picking validation raises:

                "You need to supply a Lot/Serial Number for product: ..."

            The lot is supplied via move_line_ids on the stock.move, using the
            (0, 0, {...}) creation syntax, which is the standard Odoo pattern
            for specifying detailed move lines (including lot, source location,
            destination location, and done quantity).

            For non-lot-tracked products, lot_id will be False/empty and the
            move_line_ids entry is still created but without a lot reference,
            which Odoo accepts without error.

        Args:
            collection_line (paint.pending.collection.line): The line being
                collected, which holds the lot_id captured at outgoing move time.
            qty (float): The quantity to move back to POS stock.

        Returns:
            stock.picking: The validated picking record.

        Raises:
            UserError: If the destination location cannot be determined or if
                       no internal picking type is found.

        Logs:
            INFO  – Locations, lot information, picking and move IDs.
            DEBUG – Detailed move_line_ids construction.
            WARNING – If no lot is found (non-tracked product).
            INFO  – Validation result.
        """
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "────────────────────────────────────────────────",
        )
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Creating return move for product '%s' (ID: %s), qty=%.2f.",
            collection_line.product_id.name,
            collection_line.product_id.id,
            qty,
        )

        pending = self.pending_collection_id

        # --- Resolve destination (original POS source) location ---
        dest_location = (
            pending.pos_order_id.config_id.picking_type_id.default_location_src_id
        )
        if not dest_location:
            _logger.warning(
                "[COLLECT_WIZARD] _create_return_stock_move: "
                "Cannot determine destination location for POS order '%s'. "
                "POS config picking type has no default_location_src_id.",
                pending.pos_order_id.name,
            )
            raise UserError(_('Cannot determine destination location.'))

        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Source (holding) location → '%s' (ID: %s).",
            pending.holding_location_id.name, pending.holding_location_id.id,
        )
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Destination (POS stock) location → '%s' (ID: %s).",
            dest_location.name, dest_location.id,
        )

        # --- Resolve internal picking type ---
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id.company_id', '=', pending.company_id.id),
        ], limit=1)

        if not picking_type:
            _logger.warning(
                "[COLLECT_WIZARD] _create_return_stock_move: "
                "Internal picking type not found for company '%s'.",
                pending.company_id.name,
            )
            raise UserError(_('Internal picking type not found.'))

        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Using picking type → '%s' (ID: %s).",
            picking_type.name, picking_type.id,
        )

        # -----------------------------------------------------------------
        # CRITICAL FIX: Resolve lot_id from the collection line.
        #
        # Context:
        #   When action_create_stock_moves() in paint.pending.collection ran
        #   and validated the outgoing picking (POS stock → holding), it
        #   captured the lot assigned to each product from the validated
        #   move_line_ids and wrote it to collection_line.lot_id.
        #
        #   For lot-tracked products (like tinted paint variants), Odoo
        #   mandates that any stock move referencing this product must specify
        #   the same lot. Without providing the lot in the move_line_ids of
        #   this return picking, button_validate() raises:
        #       "You need to supply a Lot/Serial Number for product: ..."
        #
        # Fix applied:
        #   Read collection_line.lot_id (populated at outgoing move time).
        #   Build a move_line_ids entry on the stock.move with this lot_id.
        #   This satisfies Odoo's lot-tracking constraint during validation.
        # -----------------------------------------------------------------
        lot_id = collection_line.lot_id

        if lot_id:
            _logger.info(
                "[COLLECT_WIZARD] _create_return_stock_move: "
                "✓ Lot/Serial found on collection line → '%s' (ID: %s). "
                "Will be passed to return move line.",
                lot_id.name, lot_id.id,
            )
        else:
            _logger.info(
                "[COLLECT_WIZARD] _create_return_stock_move: "
                "  Product '%s' has no lot on collection line "
                "(non-lot-tracked or lot not captured). "
                "Proceeding without lot.",
                collection_line.product_id.name,
            )

        # ─────────────────────────────────────────────────────────────────────
        # OUTGOING MOVE STATE CHECK
        #
        # The outgoing picking (POS Stock → Customer Holding Area) may be in
        # one of two states when the customer comes to collect:
        #
        #   CASE A — state == 'done':
        #     The outgoing picking validated normally. Stock was physically
        #     transferred to Holding in Odoo's ledger. A return move
        #     (Holding → Stock) is correct and necessary to close the loop.
        #     We use button_validate() which runs all standard checks.
        #
        #   CASE B — state != 'done' (typically 'confirmed'):
        #     This happens when the product is lot-tracked (e.g. a tinted
        #     paint variant). The POS order already moved the product from
        #     Stock → Partners/Customers when the sale was processed. By the
        #     time action_create_stock_moves() ran, there was no stock left
        #     in the source location to reserve, so the outgoing picking
        #     stayed in 'confirmed' (not 'assigned', not 'done').
        #
        #     In this case, the Holding location has ZERO Odoo-tracked
        #     quantity for this lot. Creating a return move Holding → Stock
        #     would either:
        #       - Raise "You cannot end up with a negative stock quantity!"
        #         (via button_validate), or
        #       - Silently corrupt stock by posting a phantom +1 to Stock
        #         for a product that was already fully accounted by the POS
        #         (via _action_done).
        #
        #     The correct action: cancel the unvalidated outgoing picking
        #     (it is no longer needed — the POS move is the definitive record)
        #     and skip creating a return move entirely. The collected_qty
        #     update already done above is sufficient to track the handoff.
        # ─────────────────────────────────────────────────────────────────────

        outgoing_move = collection_line.stock_move_id
        outgoing_state = outgoing_move.state if outgoing_move else False

        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Outgoing move → ID: %s, state: '%s'.",
            outgoing_move.id if outgoing_move else 'None',
            outgoing_state or 'no move linked',
        )

        # ── CASE B: Outgoing move never validated ────────────────────────────
        if outgoing_state != 'done':
            _logger.info(
                "[COLLECT_WIZARD] _create_return_stock_move: "
                "CASE B — Outgoing picking not done (state='%s'). "
                "Product '%s' was consumed by POS before Holding transfer could validate. "
                "Stock and accounting are already correct via the POS move.",
                outgoing_state or 'no move',
                collection_line.product_id.name,
            )

            # Cancel the unvalidated outgoing picking so it does not linger
            # as an open 'confirmed' transfer in the system.
            if outgoing_move and outgoing_state not in ('done', 'cancel'):
                outgoing_picking = outgoing_move.picking_id
                _logger.info(
                    "[COLLECT_WIZARD] _create_return_stock_move: "
                    "  Cancelling unvalidated outgoing picking '%s' (ID: %s, state: '%s').",
                    outgoing_picking.name if outgoing_picking else 'N/A',
                    outgoing_picking.id if outgoing_picking else 'N/A',
                    outgoing_state,
                )
                try:
                    outgoing_picking._action_cancel()
                    _logger.info(
                        "[COLLECT_WIZARD] _create_return_stock_move: "
                        "  ✓ Outgoing picking '%s' cancelled successfully.",
                        outgoing_picking.name,
                    )
                except Exception as cancel_err:
                    # Non-fatal: log and continue. The picking may already be
                    # in a state that prevents cancellation (e.g. partially done).
                    # collected_qty is already updated — the collection proceeds.
                    _logger.warning(
                        "[COLLECT_WIZARD] _create_return_stock_move: "
                        "  ⚠ Could not cancel outgoing picking '%s': %s. "
                        "Continuing — collected_qty already updated.",
                        outgoing_picking.name if outgoing_picking else 'N/A',
                        str(cancel_err),
                    )
            else:
                _logger.info(
                    "[COLLECT_WIZARD] _create_return_stock_move: "
                    "  No outgoing move to cancel (move=%s, state=%s).",
                    outgoing_move.id if outgoing_move else 'None',
                    outgoing_state or 'N/A',
                )

            _logger.info(
                "[COLLECT_WIZARD] _create_return_stock_move: "
                "  No return picking created. "
                "collected_qty on line %s updated to %.2f — "
                "pending collection tracking is complete for this product.",
                collection_line.id,
                collection_line.collected_qty,
            )
            _logger.info(
                "[COLLECT_WIZARD] _create_return_stock_move: "
                "────────────────────────────────────────────────",
            )
            return None

        # ── CASE A: Outgoing move validated — stock is in Holding ────────────
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "CASE A — Outgoing picking is done. "
            "Stock for '%s' (lot: '%s') is in Holding. "
            "Creating return move Holding → Stock.",
            collection_line.product_id.name,
            lot_id.name if lot_id else 'not tracked',
        )

        # --- Create return picking ---
        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': pending.holding_location_id.id,
            'location_dest_id': dest_location.id,
            'origin': f'Collection: {pending.name}',
        }

        picking = self.env['stock.picking'].create(picking_vals)
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Return picking created → '%s' (ID: %s).",
            picking.name, picking.id,
        )

        # --- Build move with detailed move_line_ids including lot ---
        # move_line_ids is used instead of post-create line updates because it
        # allows us to specify lot_id, location_id, location_dest_id, and
        # quantity in a single atomic creation — the standard Odoo pattern
        # for immediate transfers.
        move_line_vals = {
            'product_id': collection_line.product_id.id,
            'product_uom_id': collection_line.product_id.uom_id.id,
            'quantity': qty,
            'location_id': pending.holding_location_id.id,
            'location_dest_id': dest_location.id,
            'lot_id': lot_id.id if lot_id else False,
        }

        _logger.debug(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "move_line_vals = %s.",
            move_line_vals,
        )

        move_vals = {
            'name': f'Collect: {collection_line.product_id.name}',
            'product_id': collection_line.product_id.id,
            'product_uom_qty': qty,
            'product_uom': collection_line.product_id.uom_id.id,
            'picking_id': picking.id,
            'location_id': pending.holding_location_id.id,
            'location_dest_id': dest_location.id,
            'move_line_ids': [(0, 0, move_line_vals)],
        }

        move = self.env['stock.move'].create(move_vals)
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Stock move created → ID: %s, product: '%s', qty: %.2f, lot: '%s'.",
            move.id,
            collection_line.product_id.name,
            qty,
            lot_id.name if lot_id else 'None (not tracked)',
        )

        # --- Confirm, assign and validate ---
        picking.action_confirm()
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Picking '%s' confirmed.",
            picking.name,
        )

        picking.action_assign()
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Picking '%s' assigned. Move state = '%s'.",
            picking.name, move.state,
        )

        # Set done quantity on the move for the immediate-transfer flow.
        move.quantity = move.product_uom_qty
        _logger.debug(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "move.quantity set to %.2f.",
            move.quantity,
        )

        picking.button_validate()
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "Picking '%s' validated successfully via button_validate(). "
            "Stock moved from Holding → POS Stock.",
            picking.name,
        )
        _logger.info(
            "[COLLECT_WIZARD] _create_return_stock_move: "
            "────────────────────────────────────────────────",
        )

        return picking


# =============================================================================
# WIZARD LINE
# =============================================================================

class CollectPendingItemsWizardLine(models.TransientModel):
    """
    Transient wizard line for CollectPendingItemsWizard.

    Represents a single product line that the customer is collecting.
    Each line is linked back to the corresponding paint.pending.collection.line
    via collection_line_id (read-only), which carries the lot_id used when
    building the return stock move.

    The collect_qty field is the user-editable field: the operator enters how
    many units the customer is taking in this collection event.

    Important: The sequence field is critical — the parent wizard's
    action_confirm() matches wizard lines to collection lines by positional
    index after sorting both sets by sequence/id. Any change to sequence
    ordering must be reflected consistently in both the wizard and the
    collection model.
    """

    _name = 'collect.pending.items.wizard.line'
    _description = 'Collect Pending Items Wizard Line'
    _order = 'sequence, id'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------

    wizard_id = fields.Many2one(
        'collect.pending.items.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
        help='Parent wizard this line belongs to.',
    )

    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help=(
            'Ordering sequence. CRITICAL: The parent wizard matches lines by '
            'positional index after sorting by sequence then ID. Do not alter '
            'default sequence values unless you fully understand the matching logic.'
        ),
    )

    collection_line_id = fields.Many2one(
        'paint.pending.collection.line',
        string='Collection Line',
        readonly=True,
        help=(
            'The underlying collection line this wizard line represents. '
            'This holds the lot_id used for the return stock move.'
        ),
    )

    product_id = fields.Many2one(
        'product.product',
        string='Product',
        readonly=True,
        help='Product being collected.',
    )

    pending_qty = fields.Float(
        string='Still Pending',
        readonly=True,
        help='Remaining quantity still to be collected (from collection line remaining_qty).',
    )

    collect_qty = fields.Float(
        string='Collect Now',
        default=0.0,
        help='Quantity the customer is collecting in this event. Must not exceed Still Pending.',
    )

    product_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        related='product_id.uom_id',
        readonly=True,
        help='Unit of measure for the product.',
    )

    tint_color_code = fields.Char(
        string='Color Code',
        related='collection_line_id.tint_color_code',
        readonly=True,
        help='Tint color code from the collection line (if applicable).',
    )

    # -------------------------------------------------------------------------
    # VALIDATION (called manually from action_confirm)
    # -------------------------------------------------------------------------

    def _check_quantities(self):
        """
        Validate collection quantities on wizard lines.

        Called manually from action_confirm() in the parent wizard rather than
        via @api.constrains, because transient model constraints can fire at
        unexpected times during the wizard lifecycle.

        Checks:
            - collect_qty must not be negative.
            - collect_qty must not exceed pending_qty.

        Raises:
            ValidationError: On any quantity violation.

        Logs:
            DEBUG – Per-line validation detail.
            ERROR – When a validation violation is detected.
        """
        _logger.debug(
            "[COLLECT_WIZARD_LINE] _check_quantities: "
            "Validating quantities on %d line(s).",
            len(self),
        )
        for line in self:
            product_name = line.product_id.name if line.product_id else 'Unknown product'
            _logger.debug(
                "[COLLECT_WIZARD_LINE] _check_quantities: "
                "Line — product='%s', pending_qty=%.2f, collect_qty=%.2f.",
                product_name, line.pending_qty, line.collect_qty,
            )

            if line.collect_qty < 0:
                _logger.error(
                    "[COLLECT_WIZARD_LINE] _check_quantities: "
                    "Negative collect_qty (%.2f) for '%s'. Raising ValidationError.",
                    line.collect_qty, product_name,
                )
                raise ValidationError(
                    _('Collection quantity cannot be negative.')
                )

            if line.pending_qty and line.collect_qty > line.pending_qty:
                _logger.error(
                    "[COLLECT_WIZARD_LINE] _check_quantities: "
                    "collect_qty (%.2f) exceeds pending_qty (%.2f) for '%s'. "
                    "Raising ValidationError.",
                    line.collect_qty, line.pending_qty, product_name,
                )
                raise ValidationError(
                    _('Collection quantity (%s) cannot exceed pending quantity (%s) for %s.')
                    % (line.collect_qty, line.pending_qty, product_name)
                )

        _logger.debug(
            "[COLLECT_WIZARD_LINE] _check_quantities: All quantities valid.",
        )