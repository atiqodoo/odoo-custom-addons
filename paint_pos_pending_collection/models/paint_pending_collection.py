# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class PaintPendingCollection(models.Model):
    """
    Model representing a deferred/pending collection record for a POS order.

    When a customer pays in full at the POS but leaves some items in the store
    for later collection, this model tracks those items, their quantities, the
    holding location they have been moved to, and the collection lifecycle
    (draft → partial → done / cancelled).

    Key relationships:
        - pos_order_id       : The originating POS order (Many2one)
        - collection_line_ids: Individual product lines pending collection (One2many)
        - holding_location_id: Stock location where items are physically held

    Sequence: paint.pending.collection  →  PEND/YYYY/XXXX
    Inherits: mail.thread (chatter), mail.activity.mixin (activities)
    """

    _name = 'paint.pending.collection'
    _description = 'POS Pending Collection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_left desc, id desc'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        copy=False,
        default='/',
        tracking=True,
        help='Auto-generated sequence reference in format PEND/YYYY/XXXX.',
    )

    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        readonly=True,
        ondelete='cascade',
        tracking=True,
        help='The POS order that originated this pending collection.',
    )

    pos_reference = fields.Char(
        string='POS Receipt',
        related='pos_order_id.pos_reference',
        store=True,
        readonly=True,
        help='POS receipt number from the originating order.',
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='pos_order_id.partner_id',
        store=True,
        readonly=True,
        tracking=True,
        help='Customer who made the purchase and has items pending collection.',
    )

    partner_phone = fields.Char(
        string='Phone',
        related='partner_id.phone',
        store=True,
        readonly=True,
        help='Customer phone number for contact purposes.',
    )

    partner_mobile = fields.Char(
        string='Mobile',
        related='partner_id.mobile',
        store=True,
        readonly=True,
        help='Customer mobile number for contact purposes.',
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('partial', 'Partially Collected'),
        ('done', 'Fully Collected'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True,
        help=(
            'Lifecycle state of the pending collection:\n'
            '  draft    – Created, items moved to holding location.\n'
            '  partial  – Some items have been collected by the customer.\n'
            '  done     – All items fully collected.\n'
            '  cancelled– Collection cancelled; items returned to stock.'
        ),
    )

    collection_line_ids = fields.One2many(
        'paint.pending.collection.line',
        'pending_collection_id',
        string='Pending Items',
        copy=False,
        help='Lines representing each product left in store for collection.',
    )

    holding_location_id = fields.Many2one(
        'stock.location',
        string='Holding Location',
        required=True,
        domain=[('usage', '=', 'internal')],
        default=lambda self: self._get_default_holding_location(),
        help='Internal stock location where the pending items are physically stored.',
    )

    date_left = fields.Datetime(
        string='Date Left',
        default=fields.Datetime.now,
        required=True,
        tracking=True,
        help='Date and time when the customer left items in the store.',
    )

    date_collected = fields.Datetime(
        string='Date Fully Collected',
        readonly=True,
        tracking=True,
        help='Date and time when all items were fully collected by the customer.',
    )

    days_pending = fields.Integer(
        string='Days Pending',
        compute='_compute_days_pending',
        store=True,
        help='Number of days items have been pending collection (0 once done/cancelled).',
    )

    notes = fields.Text(
        string='Notes',
        help='Any additional notes or instructions for this pending collection.',
    )

    total_pending_qty = fields.Float(
        string='Total Pending Qty',
        compute='_compute_totals',
        store=True,
        help='Total quantity of items originally pending (sum of all lines pending_qty).',
    )

    total_collected_qty = fields.Float(
        string='Total Collected Qty',
        compute='_compute_totals',
        store=True,
        help='Total quantity already collected by the customer across all lines.',
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        help='Company this pending collection belongs to.',
    )

    barcode = fields.Char(
        string='Barcode',
        compute='_compute_barcode',
        store=True,
        help='Scannable barcode derived from the reference number (slashes removed).',
    )

    # -------------------------------------------------------------------------
    # DEFAULT METHODS
    # -------------------------------------------------------------------------

    @api.model
    def _get_default_holding_location(self):
        """
        Determine the default stock holding location for pending items.

        Resolution order:
            1. Try to find the dedicated XML-defined location via external ID
               'paint_pos_pending_collection.stock_location_customer_holding'.
            2. Fall back to the first internal location belonging to the
               current company if the dedicated location is not found.

        Returns:
            stock.location: A single location record, or an empty recordset
                            if no internal location exists at all.

        Logs:
            INFO  – Name of the resolved location.
            WARNING – If the dedicated location is not found and fallback is used.
        """
        _logger.info(
            "[PENDING_COLLECTION] _get_default_holding_location: "
            "Resolving default holding location for company '%s' (ID: %s).",
            self.env.company.name, self.env.company.id,
        )

        location = self.env.ref(
            'paint_pos_pending_collection.stock_location_customer_holding',
            raise_if_not_found=False,
        )

        if location:
            _logger.info(
                "[PENDING_COLLECTION] _get_default_holding_location: "
                "Found dedicated holding location → '%s' (ID: %s).",
                location.name, location.id,
            )
        else:
            _logger.warning(
                "[PENDING_COLLECTION] _get_default_holding_location: "
                "Dedicated holding location XML ref not found. "
                "Falling back to first available internal location.",
            )
            location = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('company_id', '=', self.env.company.id),
            ], limit=1)

            if location:
                _logger.info(
                    "[PENDING_COLLECTION] _get_default_holding_location: "
                    "Fallback location resolved → '%s' (ID: %s).",
                    location.name, location.id,
                )
            else:
                _logger.warning(
                    "[PENDING_COLLECTION] _get_default_holding_location: "
                    "No internal location found for company '%s'. "
                    "Returning empty recordset.",
                    self.env.company.name,
                )

        return location

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('name')
    def _compute_barcode(self):
        """
        Generate a scannable barcode string from the collection reference.

        Strips forward-slash characters from the name so the resulting string
        can be represented as a standard linear barcode (e.g. Code128).

        Example:
            name = 'PEND/2026/0010'  →  barcode = 'PEND20260010'

        Logs:
            DEBUG – Computed barcode value for each record.
        """
        _logger.debug(
            "[PENDING_COLLECTION] _compute_barcode: Computing barcodes for %d record(s).",
            len(self),
        )
        for record in self:
            record.barcode = record.name.replace('/', '')
            _logger.debug(
                "[PENDING_COLLECTION] _compute_barcode: Record '%s' → barcode = '%s'.",
                record.name, record.barcode,
            )

    @api.depends('date_left', 'state')
    def _compute_days_pending(self):
        """
        Calculate the number of calendar days items have been pending collection.

        Rules:
            - Returns 0 if the state is 'done' or 'cancelled' (no longer pending).
            - Returns the number of whole days since date_left otherwise.
            - Returns 0 if date_left is not set.

        Logs:
            DEBUG – Days pending value per record.
        """
        _logger.debug(
            "[PENDING_COLLECTION] _compute_days_pending: "
            "Computing days pending for %d record(s).",
            len(self),
        )
        for record in self:
            if record.state in ('done', 'cancelled'):
                record.days_pending = 0
                _logger.debug(
                    "[PENDING_COLLECTION] _compute_days_pending: "
                    "Record '%s' is '%s' → days_pending = 0.",
                    record.name, record.state,
                )
            elif record.date_left:
                delta = fields.Datetime.now() - record.date_left
                record.days_pending = delta.days
                _logger.debug(
                    "[PENDING_COLLECTION] _compute_days_pending: "
                    "Record '%s' → days_pending = %d.",
                    record.name, record.days_pending,
                )
            else:
                record.days_pending = 0
                _logger.debug(
                    "[PENDING_COLLECTION] _compute_days_pending: "
                    "Record '%s' has no date_left → days_pending = 0.",
                    record.name,
                )

    @api.depends('collection_line_ids.pending_qty', 'collection_line_ids.collected_qty')
    def _compute_totals(self):
        """
        Aggregate total pending and collected quantities across all collection lines.

        total_pending_qty  = sum of pending_qty  on all lines
        total_collected_qty= sum of collected_qty on all lines

        Logs:
            DEBUG – Totals per record after computation.
        """
        _logger.debug(
            "[PENDING_COLLECTION] _compute_totals: "
            "Computing quantity totals for %d record(s).",
            len(self),
        )
        for record in self:
            record.total_pending_qty = sum(
                record.collection_line_ids.mapped('pending_qty')
            )
            record.total_collected_qty = sum(
                record.collection_line_ids.mapped('collected_qty')
            )
            _logger.debug(
                "[PENDING_COLLECTION] _compute_totals: "
                "Record '%s' → total_pending_qty = %.2f, total_collected_qty = %.2f.",
                record.name, record.total_pending_qty, record.total_collected_qty,
            )

    # -------------------------------------------------------------------------
    # ORM OVERRIDES
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create to auto-assign a sequence reference to new records.

        For each record in vals_list where name is missing or still '/',
        the next value from the IR sequence 'paint.pending.collection' is
        fetched and assigned.

        Args:
            vals_list (list[dict]): List of field-value dictionaries for creation.

        Returns:
            paint.pending.collection: Newly created recordset.

        Logs:
            INFO  – Number of records being created.
            DEBUG – Sequence assignment per record.
            INFO  – IDs and names of created records.
        """
        _logger.info(
            "[PENDING_COLLECTION] create: Creating %d pending collection record(s).",
            len(vals_list),
        )

        for idx, vals in enumerate(vals_list):
            if vals.get('name', '/') == '/':
                sequence_val = self.env['ir.sequence'].next_by_code(
                    'paint.pending.collection'
                ) or '/'
                vals['name'] = sequence_val
                _logger.debug(
                    "[PENDING_COLLECTION] create: Record %d assigned sequence → '%s'.",
                    idx + 1, sequence_val,
                )
            else:
                _logger.debug(
                    "[PENDING_COLLECTION] create: Record %d already has name → '%s'. "
                    "Sequence assignment skipped.",
                    idx + 1, vals['name'],
                )

        records = super().create(vals_list)

        for record in records:
            _logger.info(
                "[PENDING_COLLECTION] create: Created pending collection "
                "ID=%s, name='%s', pos_order=%s.",
                record.id, record.name,
                record.pos_order_id.name if record.pos_order_id else 'None',
            )

        return records

    # -------------------------------------------------------------------------
    # STOCK MOVE ACTIONS
    # -------------------------------------------------------------------------

    def action_create_stock_moves(self):
        """
        Create and validate an internal stock transfer to move pending items
        from the POS source location to the holding location.

        Flow:
            1. Validate that collection lines exist.
            2. Determine the source location from the POS config picking type.
            3. Find an internal picking type for the company.
            4. Build a stock.picking with one stock.move per collection line.
            5. Confirm, assign (reserve), and auto-validate if all moves
               are in 'assigned' state.
            6. **Link the resulting lot_id back to each collection line.**
               This is critical: tinted products are lot-tracked, and the
               lot assigned during this outgoing move must be stored on the
               collection line so it can be re-used when creating the
               return move during customer collection (preventing the
               "You need to supply a Lot/Serial Number" error).

        Returns:
            stock.picking: The validated (or confirmed) picking record.

        Raises:
            UserError: If collection lines are empty, source location is
                       missing, or no internal picking type is found.

        Logs:
            INFO  – Progress through each step.
            DEBUG – Picking and move details.
            WARNING – When auto-validation is skipped (not fully assigned).
            INFO  – Lot/Serial Number captured per line after validation.
        """
        self.ensure_one()

        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "═══════════════════════════════════════════════════════════",
        )
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Starting for pending collection '%s' (ID: %s).",
            self.name, self.id,
        )
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Collection has %d line(s). State = '%s'.",
            len(self.collection_line_ids), self.state,
        )

        if not self.collection_line_ids:
            _logger.warning(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "No collection lines found. Aborting.",
            )
            raise UserError(_('No pending items to move to holding location.'))

        # --- Resolve source location from POS config ---
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Resolving source location from POS config picking type.",
        )
        source_location = (
            self.pos_order_id.config_id.picking_type_id.default_location_src_id
        )
        if not source_location:
            _logger.warning(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "Source location not found in POS configuration for order '%s'.",
                self.pos_order_id.name,
            )
            raise UserError(_('Source location not found in POS configuration.'))

        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Source location → '%s' (ID: %s).",
            source_location.name, source_location.id,
        )
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Destination (holding) location → '%s' (ID: %s).",
            self.holding_location_id.name, self.holding_location_id.id,
        )

        # --- Resolve internal picking type ---
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Searching for internal picking type for company ID %s.",
            self.company_id.id,
        )
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id.company_id', '=', self.company_id.id),
        ], limit=1)

        if not picking_type:
            _logger.warning(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "Internal picking type not found for company '%s'.",
                self.company_id.name,
            )
            raise UserError(_('Internal picking type not found.'))

        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Using picking type → '%s' (ID: %s).",
            picking_type.name, picking_type.id,
        )

        # --- Build picking and move values ---
        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': source_location.id,
            'location_dest_id': self.holding_location_id.id,
            'origin': f'{self.pos_reference} - {self.name}',
            'move_ids_without_package': [],
        }

        for line in self.collection_line_ids:
            move_vals = {
                'name': line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.pending_qty,
                'product_uom': line.product_id.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': self.holding_location_id.id,
            }
            picking_vals['move_ids_without_package'].append((0, 0, move_vals))
            _logger.debug(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "Queued move for product '%s' (ID: %s), qty=%.2f.",
                line.product_id.name, line.product_id.id, line.pending_qty,
            )

        # --- Create the picking ---
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Creating stock picking with %d move(s).",
            len(self.collection_line_ids),
        )
        picking = self.env['stock.picking'].create(picking_vals)
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Picking created → '%s' (ID: %s).",
            picking.name, picking.id,
        )

        # --- Confirm and assign ---
        picking.action_confirm()
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Picking confirmed. Attempting reservation (action_assign).",
        )
        picking.action_assign()
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Reservation done. Move states: %s.",
            {m.product_id.name: m.state for m in picking.move_ids},
        )

        # --- Auto-validate if all moves are assigned ---
        all_assigned = all(m.state == 'assigned' for m in picking.move_ids)
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "All moves assigned = %s.",
            all_assigned,
        )

        if all_assigned:
            _logger.info(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "Auto-validating picking '%s'.",
                picking.name,
            )
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
            picking.button_validate()
            _logger.info(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "Picking '%s' validated successfully.",
                picking.name,
            )
        else:
            _logger.warning(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "Not all moves are in 'assigned' state. "
                "Auto-validation skipped. Manual validation may be required.",
            )

        # --- Link stock_move_id to each collection line ---
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Linking stock moves back to collection lines.",
        )
        for line in self.collection_line_ids:
            matched_move = picking.move_ids.filtered(
                lambda m: m.product_id == line.product_id
            )[:1]
            line.stock_move_id = matched_move

            _logger.debug(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "Line product '%s' → stock_move_id = %s (state: %s).",
                line.product_id.name,
                matched_move.id if matched_move else 'None',
                matched_move.state if matched_move else 'N/A',
            )

        # -----------------------------------------------------------------
        # CRITICAL FIX: Capture lot_id onto each collection line.
        #
        # Two-stage strategy:
        #
        # Stage 1 — Stock move lines (preferred):
        #   When the outgoing picking validates cleanly, Odoo writes the
        #   assigned lot onto move_line_ids. We read it from there.
        #
        # Stage 2 — POS pack_lot_ids (fallback):
        #   Tinted products are lot-tracked. Their lot is consumed from Stock
        #   when the POS order is processed. If the outgoing pending-collection
        #   move cannot be reserved/validated (move stays 'confirmed', no
        #   move_line_ids created), we fall back to reading the lot name
        #   directly from the original POS order line's pack_lot_ids and
        #   looking it up in stock.lot by (name, product_id).
        #
        # The captured lot is stored on collection_line.lot_id and is later
        # read by collect.pending.items.wizard._create_return_stock_move()
        # to supply the lot on the return picking. Without this, Odoo raises:
        #   "You need to supply a Lot/Serial Number for product: ..."
        # -----------------------------------------------------------------
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "━━━ Capturing Lot/Serial Numbers (Stage 1: move lines) ━━━",
        )
        for line in self.collection_line_ids:
            if not line.stock_move_id:
                _logger.warning(
                    "[PENDING_COLLECTION] action_create_stock_moves: "
                    "Line for product '%s' has no linked stock_move_id.",
                    line.product_id.name,
                )
                continue
            move_lines = line.stock_move_id.move_line_ids
            _logger.debug(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "Product '%s' → move_line_ids count = %d.",
                line.product_id.name, len(move_lines),
            )
            if move_lines and move_lines[0].lot_id:
                captured_lot = move_lines[0].lot_id
                line.lot_id = captured_lot
                _logger.info(
                    "[PENDING_COLLECTION] action_create_stock_moves: "
                    "✓ [Stage 1] Lot from move line: '%s' → '%s' (ID: %s).",
                    line.product_id.name, captured_lot.name, captured_lot.id,
                )
            else:
                _logger.info(
                    "[PENDING_COLLECTION] action_create_stock_moves: "
                    "  [Stage 1] No lot on move lines for '%s' — will try POS fallback.",
                    line.product_id.name,
                )

        # Stage 2: POS pack_lot_ids fallback for lines still without a lot.
        # Build a per-product queue of lots from the POS order's pack_lot_ids,
        # then pop one lot per collection line in sequence order.
        lines_needing_lot = self.collection_line_ids.filtered(
            lambda l: not l.lot_id
        )
        if lines_needing_lot:
            _logger.info(
                "[PENDING_COLLECTION] action_create_stock_moves: "
                "━━━ Stage 2: POS pack_lot_ids fallback for %d line(s) ━━━",
                len(lines_needing_lot),
            )
            from collections import defaultdict
            pos_lot_queue = defaultdict(list)

            for pos_line in self.pos_order_id.lines:
                for pack_lot in pos_line.pack_lot_ids:
                    if not pack_lot.lot_name:
                        continue
                    lot_rec = self.env['stock.lot'].search([
                        ('name', '=', pack_lot.lot_name),
                        ('product_id', '=', pos_line.product_id.id),
                    ], limit=1)
                    if lot_rec:
                        pos_lot_queue[pos_line.product_id.id].append(lot_rec)
                        _logger.debug(
                            "[PENDING_COLLECTION] action_create_stock_moves: "
                            "  POS pack_lot queued: product '%s' → lot '%s'.",
                            pos_line.product_id.name, lot_rec.name,
                        )
                    else:
                        _logger.warning(
                            "[PENDING_COLLECTION] action_create_stock_moves: "
                            "  pack_lot_name '%s' not found in stock.lot for product '%s'.",
                            pack_lot.lot_name, pos_line.product_id.name,
                        )

            for line in lines_needing_lot.sorted('id'):
                product_id = line.product_id.id
                if pos_lot_queue.get(product_id):
                    lot = pos_lot_queue[product_id].pop(0)
                    line.lot_id = lot
                    _logger.info(
                        "[PENDING_COLLECTION] action_create_stock_moves: "
                        "✓ [Stage 2] Lot from POS pack_lot: '%s' → '%s' (ID: %s).",
                        line.product_id.name, lot.name, lot.id,
                    )
                else:
                    _logger.info(
                        "[PENDING_COLLECTION] action_create_stock_moves: "
                        "  [Stage 2] No lot found in POS pack_lot for '%s' "
                        "(product not lot-tracked or lot not recorded at sale time).",
                        line.product_id.name,
                    )

        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "━━━ Lot capture complete ━━━",
        )

        # --- Update state ---
        if self.state == 'draft':
            if self.total_collected_qty > 0:
                self.state = 'partial'
                _logger.info(
                    "[PENDING_COLLECTION] action_create_stock_moves: "
                    "State updated to 'partial' (some items already collected).",
                )
            else:
                _logger.info(
                    "[PENDING_COLLECTION] action_create_stock_moves: "
                    "State remains 'draft' (no items collected yet).",
                )

        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "Completed successfully. Picking = '%s' (ID: %s).",
            picking.name, picking.id,
        )
        _logger.info(
            "[PENDING_COLLECTION] action_create_stock_moves: "
            "═══════════════════════════════════════════════════════════",
        )

        return picking

    # -------------------------------------------------------------------------
    # WIZARD LAUNCHERS
    # -------------------------------------------------------------------------

    def action_collect_items(self):
        """
        Open the 'Collect Pending Items' wizard in a dialog window.

        Passes the current pending collection ID via context so the wizard
        can pre-populate its lines.

        Returns:
            dict: An ir.actions.act_window action dict targeting
                  collect.pending.items.wizard in 'new' (dialog) mode.

        Logs:
            INFO – Record name and ID when wizard is launched.
        """
        self.ensure_one()
        _logger.info(
            "[PENDING_COLLECTION] action_collect_items: "
            "Opening collect wizard for pending collection '%s' (ID: %s).",
            self.name, self.id,
        )
        return {
            'name': _('Collect Pending Items'),
            'type': 'ir.actions.act_window',
            'res_model': 'collect.pending.items.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_pending_collection_id': self.id,
            },
        }

    # -------------------------------------------------------------------------
    # CANCEL
    # -------------------------------------------------------------------------

    def action_cancel(self):
        """
        Cancel this pending collection and create reverse stock moves to return
        all remaining items from the holding location back to the POS source
        location.

        Rules:
            - Cannot cancel a record in 'done' state.
            - For each collection line that has a stock_move_id and remaining
              qty > 0, a new internal picking is created to reverse the move.

        Raises:
            UserError: If the collection is already in 'done' state.

        Logs:
            INFO  – Start of cancellation, per-line move reversal.
            WARNING – Lines skipped (no stock_move_id or zero pending qty).
            INFO  – Final state update to 'cancelled'.
        """
        self.ensure_one()

        _logger.info(
            "[PENDING_COLLECTION] action_cancel: "
            "═══════════════════════════════════════════════════════════",
        )
        _logger.info(
            "[PENDING_COLLECTION] action_cancel: "
            "Cancellation requested for '%s' (ID: %s). Current state = '%s'.",
            self.name, self.id, self.state,
        )

        if self.state == 'done':
            _logger.warning(
                "[PENDING_COLLECTION] action_cancel: "
                "Cannot cancel '%s' — it is already fully collected (done).",
                self.name,
            )
            raise UserError(_('Cannot cancel a fully collected order.'))

        _logger.info(
            "[PENDING_COLLECTION] action_cancel: "
            "Processing %d collection line(s) for stock reversal.",
            len(self.collection_line_ids),
        )

        for line in self.collection_line_ids:
            _logger.info(
                "[PENDING_COLLECTION] action_cancel: "
                "Processing line — product '%s', pending_qty=%.2f, "
                "stock_move_id=%s.",
                line.product_id.name,
                line.pending_qty,
                line.stock_move_id.id if line.stock_move_id else 'None',
            )

            if not line.stock_move_id or line.pending_qty <= 0:
                _logger.warning(
                    "[PENDING_COLLECTION] action_cancel: "
                    "Skipping line for '%s' — no stock_move_id or zero pending qty.",
                    line.product_id.name,
                )
                continue

            source_location = line.stock_move_id.location_dest_id
            dest_location = line.stock_move_id.location_id

            _logger.info(
                "[PENDING_COLLECTION] action_cancel: "
                "Return move: '%s' → '%s', qty=%.2f.",
                source_location.name, dest_location.name, line.pending_qty,
            )

            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('warehouse_id.company_id', '=', self.company_id.id),
            ], limit=1)

            if not picking_type:
                _logger.warning(
                    "[PENDING_COLLECTION] action_cancel: "
                    "Internal picking type not found for company '%s'. "
                    "Skipping line for '%s'.",
                    self.company_id.name, line.product_id.name,
                )
                continue

            picking_vals = {
                'picking_type_id': picking_type.id,
                'location_id': source_location.id,
                'location_dest_id': dest_location.id,
                'origin': f'Return: {self.name}',
            }

            picking = self.env['stock.picking'].create(picking_vals)
            _logger.info(
                "[PENDING_COLLECTION] action_cancel: "
                "Return picking created → '%s' (ID: %s).",
                picking.name, picking.id,
            )

            move_vals = {
                'name': f'Return: {line.product_id.name}',
                'product_id': line.product_id.id,
                'product_uom_qty': line.pending_qty,
                'product_uom': line.product_id.uom_id.id,
                'picking_id': picking.id,
                'location_id': source_location.id,
                'location_dest_id': dest_location.id,
            }

            move = self.env['stock.move'].create(move_vals)
            _logger.debug(
                "[PENDING_COLLECTION] action_cancel: "
                "Return stock move created → ID: %s.",
                move.id,
            )

            picking.action_confirm()
            picking.action_assign()
            move.quantity = move.product_uom_qty
            picking.button_validate()

            _logger.info(
                "[PENDING_COLLECTION] action_cancel: "
                "Return picking '%s' validated. Items returned for '%s'.",
                picking.name, line.product_id.name,
            )

        self.state = 'cancelled'
        self.message_post(
            body=_('Pending collection cancelled. Items returned to stock.')
        )
        _logger.info(
            "[PENDING_COLLECTION] action_cancel: "
            "Pending collection '%s' state updated to 'cancelled'.",
            self.name,
        )
        _logger.info(
            "[PENDING_COLLECTION] action_cancel: "
            "═══════════════════════════════════════════════════════════",
        )

    # -------------------------------------------------------------------------
    # REPORT
    # -------------------------------------------------------------------------

    def action_print_label(self):
        """
        Trigger the pending collection label report for printing.

        Uses the report action defined by external ID
        'paint_pos_pending_collection.action_report_pending_collection_label'.

        Returns:
            dict: Report action dictionary from ir.actions.report.

        Logs:
            INFO – Record name when print is triggered.
        """
        self.ensure_one()
        _logger.info(
            "[PENDING_COLLECTION] action_print_label: "
            "Printing label for pending collection '%s' (ID: %s).",
            self.name, self.id,
        )
        return self.env.ref(
            'paint_pos_pending_collection.action_report_pending_collection_label'
        ).report_action(self)

    # -------------------------------------------------------------------------
    # NAME GET
    # -------------------------------------------------------------------------

    def name_get(self):
        """
        Override name_get to display a human-readable label.

        Format: '<reference> - <customer name>'
        If no customer is set, only the reference is returned.

        Returns:
            list[tuple]: List of (id, display_name) tuples.

        Logs:
            DEBUG – Display name constructed for each record.
        """
        _logger.debug(
            "[PENDING_COLLECTION] name_get: Building display names for %d record(s).",
            len(self),
        )
        result = []
        for record in self:
            name = record.name
            if record.partner_id:
                name += f' - {record.partner_id.name}'
            result.append((record.id, name))
            _logger.debug(
                "[PENDING_COLLECTION] name_get: ID %s → '%s'.",
                record.id, name,
            )
        return result