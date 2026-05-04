# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.tools.float_utils import float_compare, float_round

_logger = logging.getLogger(__name__)

SEP = "=" * 80
SEP_THIN = "-" * 60


# ============================================================
# MODEL 1: Deferred Valuation Layer (subledger header)
# ============================================================

class PaintTintingDeferredValuation(models.Model):
    _name = 'paint.tinting.deferred.valuation'
    _description = 'Deferred Valuation Layer - Manufacturing Negative Stock'
    _order = 'date_consumed desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Component Product',
        required=True,
        readonly=True,
        index=True,
    )
    product_categ_id = fields.Many2one(
        related='product_id.categ_id',
        string='Category',
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        string='Currency',
        store=True,
    )
    mo_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        readonly=True,
        index=True,
    )
    consumption_move_id = fields.Many2one(
        'stock.move',
        string='Consumption Move',
        readonly=True,
    )
    date_consumed = fields.Datetime(
        string='Consumed On',
        required=True,
        readonly=True,
        default=fields.Datetime.now,
        index=True,
    )
    qty_consumed = fields.Float(
        string='Qty Consumed into Negative',
        required=True,
        readonly=True,
        digits='Product Unit of Measure',
        help='Quantity that consumed into zero/negative stock territory.',
    )
    qty_reconciled = fields.Float(
        string='Qty Reconciled',
        readonly=True,
        digits='Product Unit of Measure',
        default=0.0,
    )
    qty_remaining = fields.Float(
        string='Qty Remaining',
        compute='_compute_qty_remaining',
        store=True,
        digits='Product Unit of Measure',
    )
    unit_cost_frozen = fields.Float(
        string='Frozen Unit Cost',
        required=True,
        readonly=True,
        digits='Product Price',
        help=(
            'Standard price (= AVCO) frozen at the moment of manufacturing. '
            'This is the provisional cost posted to WIP. Never updated.'
        ),
    )
    total_provisional_value = fields.Monetary(
        string='Total Provisional Value',
        compute='_compute_provisional_value',
        store=True,
        currency_field='currency_id',
        help='qty_consumed x unit_cost_frozen',
    )
    # NOT stored intentionally — avoids cross-model trigger setup during init_models
    total_price_diff_posted = fields.Monetary(
        string='Total Price Difference Posted',
        compute='_compute_price_diff_posted',
        currency_field='currency_id',
        help='Sum of price differences posted through all reconciliation lines.',
    )
    price_diff_account_id = fields.Many2one(
        related='product_categ_id.property_account_creditor_price_difference_categ',
        string='Price Difference Account',
        store=True,
    )
    state = fields.Selection([
        ('pending', 'Pending'),
        ('partial', 'Partially Reconciled'),
        ('reconciled', 'Fully Reconciled'),
    ], string='State', default='pending', readonly=True, index=True)
    reconciliation_ids = fields.One2many(
        'paint.tinting.deferred.reconciliation',
        'deferred_id',
        string='Reconciliation Lines',
        readonly=True,
    )
    notes = fields.Text(string='Notes', readonly=True)

    @api.depends('qty_consumed', 'qty_reconciled')
    def _compute_qty_remaining(self):
        for rec in self:
            rec.qty_remaining = max(0.0, rec.qty_consumed - rec.qty_reconciled)

    @api.depends('qty_consumed', 'unit_cost_frozen')
    def _compute_provisional_value(self):
        for rec in self:
            rec.total_provisional_value = rec.qty_consumed * rec.unit_cost_frozen

    @api.depends('reconciliation_ids.price_difference')
    def _compute_price_diff_posted(self):
        for rec in self:
            rec.total_price_diff_posted = sum(
                rec.reconciliation_ids.mapped('price_difference')
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code(
                        'paint.tinting.deferred.valuation'
                    ) or 'PT/DV/NEW'
                )
        return super().create(vals_list)


# ============================================================
# MODEL 2: Reconciliation Line (subledger detail)
# ============================================================

class PaintTintingDeferredReconciliation(models.Model):
    _name = 'paint.tinting.deferred.reconciliation'
    _description = 'Deferred Valuation Reconciliation Line'
    _order = 'date_reconciled desc, id desc'

    deferred_id = fields.Many2one(
        'paint.tinting.deferred.valuation',
        string='Deferred Layer',
        required=True,
        ondelete='cascade',
        readonly=True,
        index=True,
    )
    product_id = fields.Many2one(
        related='deferred_id.product_id',
        store=True,
        string='Product',
    )
    mo_id = fields.Many2one(
        related='deferred_id.mo_id',
        store=True,
        string='Manufacturing Order',
    )
    receipt_move_id = fields.Many2one(
        'stock.move',
        string='Receipt Move',
        readonly=True,
    )
    picking_id = fields.Many2one(
        related='receipt_move_id.picking_id',
        string='Receipt Picking',
        store=True,
    )
    date_reconciled = fields.Datetime(
        string='Reconciled On',
        readonly=True,
        default=fields.Datetime.now,
    )
    qty_reconciled = fields.Float(
        string='Qty Reconciled',
        readonly=True,
        digits='Product Unit of Measure',
    )
    cost_at_consumption = fields.Float(
        related='deferred_id.unit_cost_frozen',
        string='Provisional Cost',
        digits='Product Price',
    )
    cost_at_receipt = fields.Float(
        string='Receipt Unit Cost',
        readonly=True,
        digits='Product Price',
    )
    price_difference = fields.Float(
        string='Price Difference',
        readonly=True,
        digits='Product Price',
        help=(
            '(cost_at_receipt - cost_at_consumption) x qty_reconciled.\n'
            'Positive = WIP was under-costed. Negative = WIP was over-costed.'
        ),
    )
    journal_entry_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='deferred_id.currency_id',
        string='Currency',
    )
    company_id = fields.Many2one(
        related='deferred_id.company_id',
        string='Company',
    )


# ============================================================
# OVERRIDE 1: stock.quant
# Bypass the Kenya eTIMS negative stock constraint
# (l10n_ke_edi_oscu_stock adds @api.constrains('quantity') that fires
#  unconditionally — we skip ALL quantity constraints via _validate_fields
#  when our manufacturing context key is present)
# ============================================================

class StockQuantPTOverride(models.Model):
    _inherit = 'stock.quant'

    def _validate_fields(self, field_names, excluded_names=()):
        # When completing a manufacturing order with negative stock components,
        # skip quantity-based constraints only. All other constraints still run.
        if (self._context.get('pt_allow_negative_manufacturing')
                and 'quantity' in set(field_names)):
            _logger.info(
                "[PT-DEFERRED][StockQuant] Quantity constraint BYPASSED "
                "for manufacturing | Products: %s",
                self.mapped('product_id.display_name'),
            )
            remaining = set(field_names) - {'quantity'}
            if remaining:
                return super()._validate_fields(remaining, excluded_names)
            return
        return super()._validate_fields(field_names, excluded_names)


# ============================================================
# OVERRIDE 2: stock.move — core interception hook
# ============================================================

class StockMovePTOverride(models.Model):
    """
    Intercepts stock.move._action_done() for two purposes:

    A) Manufacturing component consumption:
       - Snapshots on-hand before super() runs
       - After super(): if stock went negative, creates deferred valuation records
         (subledger tracking provisional cost = frozen standard_price)

    B) Purchase receipt incoming moves:
       - After super(): checks if any pending deferred records exist for
         the received product, calculates price difference, posts journal entry
         automatically to the Price Difference Account on the product category
    """
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        _logger.info(SEP)
        _logger.info(
            "[PT-DEFERRED] _action_done ENTRY | Move IDs: %s | "
            "cancel_backorder: %s",
            self.ids, cancel_backorder,
        )

        # ── A: Manufacturing component consumption moves ─────────────────
        # Criteria: move has a raw_material_production_id (MO), goes from
        # internal stock to production location, product has real-time valuation
        mfg_moves = self.filtered(
            lambda m: (
                m.raw_material_production_id
                and m.location_id.usage == 'internal'
                and m.location_dest_id.usage == 'production'
                and m.product_id.categ_id.property_valuation == 'real_time'
            )
        )

        # ── B: Purchase receipt incoming moves ───────────────────────────
        receipt_moves = self.filtered(
            lambda m: (
                m.picking_id
                and m.picking_id.picking_type_code == 'incoming'
                and m.location_id.usage == 'supplier'
                and m.location_dest_id.usage == 'internal'
                and m.product_id.categ_id.property_valuation == 'real_time'
            )
        )

        _logger.info(
            "[PT-DEFERRED] Classified | Mfg moves: %d | Receipt moves: %d",
            len(mfg_moves), len(receipt_moves),
        )

        # ── PRE-SNAPSHOT: capture on-hand quantities BEFORE super() ──────
        pre_snapshot = {}
        if mfg_moves:
            _logger.info(SEP_THIN)
            _logger.info("[PT-DEFERRED] PRE-SNAPSHOT — capturing on-hand per component")
            for move in mfg_moves:
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', move.product_id.id),
                    ('location_id', '=', move.location_id.id),
                ])
                on_hand = sum(quants.mapped('quantity'))
                pre_snapshot[move.id] = {
                    'product': move.product_id,
                    'on_hand_before': on_hand,
                    'standard_price': move.product_id.standard_price,
                    'mo': move.raw_material_production_id,
                }
                suffix = (
                    'SHORTFALL' if on_hand < move.product_uom_qty else 'OK'
                )
                _logger.info(
                    "[PT-DEFERRED] SNAP [%s] | %-40s | On Hand: %8.4f | "
                    "Demand: %8.4f | Std Price: %10.2f",
                    suffix,
                    move.product_id.display_name,
                    on_hand,
                    move.product_uom_qty,
                    move.product_id.standard_price,
                )

        # ── CHECK: receipt moves for products with pending deferred records ──
        # If we previously allowed negative stock for manufacturing, receipts
        # into still-negative stock must also bypass the Kenya constraint.
        receipt_has_pending = False
        if receipt_moves and not mfg_moves:
            receipt_product_ids = receipt_moves.mapped('product_id.id')
            company_ids = receipt_moves.mapped('company_id.id')
            pending_count = self.env['paint.tinting.deferred.valuation'].search_count([
                ('product_id', 'in', receipt_product_ids),
                ('state', 'in', ['pending', 'partial']),
                ('company_id', 'in', company_ids),
            ])
            receipt_has_pending = bool(pending_count)
            if receipt_has_pending:
                _logger.info(
                    "[PT-DEFERRED] Receipt move(s) have %d pending deferred "
                    "record(s) — negative stock bypass needed for receipt",
                    pending_count,
                )

        # ── CALL SUPER with bypass context ───────────────────────────────
        ctx = dict(self._context)
        if mfg_moves or receipt_has_pending:
            ctx['pt_allow_negative_manufacturing'] = True
            _logger.info(
                "[PT-DEFERRED] Context: pt_allow_negative_manufacturing=True "
                "(mfg=%s, receipt_pending=%s)",
                bool(mfg_moves), receipt_has_pending,
            )

        _logger.info("[PT-DEFERRED] Calling super()._action_done() ...")
        res = super(StockMovePTOverride, self.with_context(ctx))._action_done(
            cancel_backorder=cancel_backorder
        )
        _logger.info("[PT-DEFERRED] super()._action_done() completed successfully")

        # ── POST A: Create deferred records for shortfall components ──────
        if mfg_moves and pre_snapshot:
            _logger.info(SEP_THIN)
            _logger.info("[PT-DEFERRED] POST-A: Analysing manufacturing consumption")
            try:
                self._pt_create_deferred_records(mfg_moves, pre_snapshot)
            except Exception as e:
                _logger.error(
                    "[PT-DEFERRED] ERROR in _pt_create_deferred_records: %s",
                    str(e), exc_info=True,
                )

        # ── POST B: Reconcile deferred records on receipt ─────────────────
        if receipt_moves:
            _logger.info(SEP_THIN)
            _logger.info("[PT-DEFERRED] POST-B: Processing receipt reconciliation")
            try:
                self._pt_reconcile_on_receipt(receipt_moves)
            except Exception as e:
                _logger.error(
                    "[PT-DEFERRED] ERROR in _pt_reconcile_on_receipt: %s",
                    str(e), exc_info=True,
                )

        _logger.info("[PT-DEFERRED] _action_done EXIT")
        _logger.info(SEP)
        return res

    # ================================================================
    # PRIVATE: Create deferred valuation records after manufacturing
    # ================================================================

    def _pt_create_deferred_records(self, mfg_moves, pre_snapshot):
        _logger.info(SEP_THIN)
        _logger.info("[PT-DEFERRED] === CREATE DEFERRED RECORDS ===")

        created = skipped = 0

        for move in mfg_moves:
            snap = pre_snapshot.get(move.id)
            if not snap:
                _logger.warning(
                    "[PT-DEFERRED] No snapshot for move %s — skip", move.id
                )
                skipped += 1
                continue

            product = snap['product']
            on_hand_before = snap['on_hand_before']
            unit_cost_frozen = snap['standard_price']
            mo = snap['mo']
            qty_done = move.quantity

            _logger.info(
                "[PT-DEFERRED] Move %s | Product: %s | "
                "On Hand Before: %.4f | Qty Done: %.4f",
                move.id, product.display_name, on_hand_before, qty_done,
            )

            # Quantity that went into negative territory
            # available_before = max(0, on_hand_before) handles already-negative stock
            available_before = max(0.0, on_hand_before)
            qty_into_negative = max(0.0, qty_done - available_before)

            _logger.info(
                "[PT-DEFERRED] Available Before (clamped): %.4f | "
                "Qty Into Negative: %.4f",
                available_before, qty_into_negative,
            )

            if float_compare(qty_into_negative, 0.0, precision_digits=6) <= 0:
                _logger.info(
                    "[PT-DEFERRED] SKIP | Product: %s | Sufficient stock",
                    product.display_name,
                )
                skipped += 1
                continue

            price_diff_account = (
                product.categ_id.property_account_creditor_price_difference_categ
            )
            if not price_diff_account:
                _logger.warning(
                    "[PT-DEFERRED] WARNING | Product: %s | Category: %s | "
                    "Price Difference Account NOT configured — deferred record "
                    "created but price diff cannot be posted at receipt.",
                    product.display_name, product.categ_id.name,
                )

            note = (
                "MO: %s | On hand before: %.4f | Total consumed: %.4f | "
                "Available portion: %.4f | Negative portion: %.4f | "
                "Frozen std price: %.4f"
            ) % (
                mo.name, on_hand_before, qty_done,
                available_before, qty_into_negative, unit_cost_frozen,
            )

            deferred = self.env['paint.tinting.deferred.valuation'].create({
                'product_id': product.id,
                'company_id': move.company_id.id,
                'mo_id': mo.id,
                'consumption_move_id': move.id,
                'date_consumed': fields.Datetime.now(),
                'qty_consumed': qty_into_negative,
                'qty_reconciled': 0.0,
                'unit_cost_frozen': unit_cost_frozen,
                'state': 'pending',
                'notes': note,
            })
            created += 1

            _logger.info(
                "[PT-DEFERRED] CREATED | Ref: %s | Product: %s | "
                "Qty: %.4f | Frozen Cost: %.4f | Provisional Value: %.2f | "
                "Price Diff Account: %s",
                deferred.name,
                product.display_name,
                qty_into_negative,
                unit_cost_frozen,
                qty_into_negative * unit_cost_frozen,
                price_diff_account.display_name if price_diff_account else 'NOT SET',
            )

            try:
                mo.message_post(body=_(
                    "<b>Deferred Valuation Layer Created</b><br/>"
                    "Component <b>%(product)s</b> had insufficient stock.<br/>"
                    "<b>%(qty).4f</b> unit(s) consumed into negative territory.<br/>"
                    "Provisional cost: <b>%(cost).4f</b> (frozen standard price).<br/>"
                    "Provisional value: <b>%(value).2f</b><br/>"
                    "Deferred ref: <b>%(ref)s</b> — price difference will "
                    "auto-post on next receipt.",
                    product=product.display_name,
                    qty=qty_into_negative,
                    cost=unit_cost_frozen,
                    value=qty_into_negative * unit_cost_frozen,
                    ref=deferred.name,
                ))
            except Exception as e:
                _logger.warning(
                    "[PT-DEFERRED] Could not post MO chatter: %s", e
                )

        _logger.info(
            "[PT-DEFERRED] DEFERRED CREATION DONE | Created: %d | Skipped: %d",
            created, skipped,
        )

    # ================================================================
    # PRIVATE: Reconcile deferred records on goods receipt
    # ================================================================

    def _pt_reconcile_on_receipt(self, receipt_moves):
        _logger.info(SEP_THIN)
        _logger.info("[PT-DEFERRED] === RECEIPT RECONCILIATION ===")

        for move in receipt_moves:
            product = move.product_id
            _logger.info(
                "[PT-DEFERRED] Receipt move %s | Product: %s | "
                "Qty: %.4f | Picking: %s",
                move.id, product.display_name, move.quantity,
                move.picking_id.name,
            )

            # Find pending deferred records — FIFO order (oldest first)
            pending = self.env['paint.tinting.deferred.valuation'].search([
                ('product_id', '=', product.id),
                ('state', 'in', ['pending', 'partial']),
                ('company_id', '=', move.company_id.id),
            ], order='date_consumed asc, id asc')

            if not pending:
                _logger.info(
                    "[PT-DEFERRED] No pending deferred for %s — normal receipt",
                    product.display_name,
                )
                continue

            _logger.info(
                "[PT-DEFERRED] Found %d pending record(s) for %s | "
                "Total pending qty: %.4f",
                len(pending), product.display_name,
                sum(pending.mapped('qty_remaining')),
            )

            # Get receipt unit cost from the SVL created by super()
            receipt_svl = move.stock_valuation_layer_ids.filtered(
                lambda s: float_compare(s.quantity, 0.0, precision_digits=6) > 0
            )
            if not receipt_svl:
                _logger.warning(
                    "[PT-DEFERRED] No positive SVL on receipt move %s — "
                    "cannot determine actual cost. Skipping reconciliation.",
                    move.id,
                )
                continue

            receipt_unit_cost = receipt_svl[0].unit_cost
            _logger.info(
                "[PT-DEFERRED] Receipt unit cost from SVL[%s]: %.4f",
                receipt_svl[0].id, receipt_unit_cost,
            )

            receipt_qty_pool = move.quantity
            _logger.info(
                "[PT-DEFERRED] Receipt qty pool: %.4f", receipt_qty_pool
            )

            for deferred in pending:
                if float_compare(receipt_qty_pool, 0.0, precision_digits=6) <= 0:
                    _logger.info("[PT-DEFERRED] Pool exhausted — stop")
                    break

                qty_to_reconcile = min(deferred.qty_remaining, receipt_qty_pool)
                frozen_cost = deferred.unit_cost_frozen
                diff_per_unit = receipt_unit_cost - frozen_cost
                diff_total = diff_per_unit * qty_to_reconcile

                _logger.info(
                    "[PT-DEFERRED] %s | Reconciling %.4f unit(s) | "
                    "Frozen: %.4f | Receipt: %.4f | Diff/unit: %.4f | "
                    "Total diff: %.4f",
                    deferred.name, qty_to_reconcile,
                    frozen_cost, receipt_unit_cost, diff_per_unit, diff_total,
                )

                # Post journal entry if difference is material
                currency = move.company_id.currency_id
                journal_entry = False
                if float_compare(
                    abs(diff_total),
                    currency.rounding,
                    precision_rounding=currency.rounding,
                ) > 0:
                    journal_entry = self._pt_post_price_diff_entry(
                        deferred=deferred,
                        receipt_move=move,
                        qty_reconciled=qty_to_reconcile,
                        frozen_cost=frozen_cost,
                        receipt_cost=receipt_unit_cost,
                        diff_total=diff_total,
                    )
                else:
                    _logger.info(
                        "[PT-DEFERRED] Diff %.6f below rounding %s — no entry",
                        diff_total, currency.rounding,
                    )

                # Record reconciliation line
                recon = self.env['paint.tinting.deferred.reconciliation'].create({
                    'deferred_id': deferred.id,
                    'receipt_move_id': move.id,
                    'date_reconciled': fields.Datetime.now(),
                    'qty_reconciled': qty_to_reconcile,
                    'cost_at_receipt': receipt_unit_cost,
                    'price_difference': diff_total,
                    'journal_entry_id': journal_entry.id if journal_entry else False,
                })
                _logger.info(
                    "[PT-DEFERRED] Reconciliation line %s created | "
                    "Journal: %s",
                    recon.id,
                    journal_entry.name if journal_entry else 'None (below rounding)',
                )

                # Update deferred record state
                new_qty_reconciled = deferred.qty_reconciled + qty_to_reconcile
                fully_covered = float_compare(
                    new_qty_reconciled,
                    deferred.qty_consumed,
                    precision_digits=6,
                ) >= 0
                new_state = 'reconciled' if fully_covered else 'partial'

                deferred.write({
                    'qty_reconciled': new_qty_reconciled,
                    'state': new_state,
                })
                _logger.info(
                    "[PT-DEFERRED] %s updated | State: %s | "
                    "Reconciled: %.4f / %.4f",
                    deferred.name, new_state.upper(),
                    new_qty_reconciled, deferred.qty_consumed,
                )

                try:
                    if deferred.mo_id:
                        direction = (
                            "UNDER-COSTED (receipt > provisional)"
                            if diff_total > 0
                            else "OVER-COSTED (receipt < provisional)"
                        )
                        deferred.mo_id.message_post(body=_(
                            "<b>Deferred Valuation Reconciled</b><br/>"
                            "Ref: <b>%(ref)s</b> | Receipt: <b>%(picking)s</b><br/>"
                            "Product: %(product)s | Qty: %(qty).4f<br/>"
                            "Provisional: %(frozen).4f "
                            "to Receipt: %(receipt).4f<br/>"
                            "Difference: <b>%(diff).4f</b> (%(label)s)<br/>"
                            "Account: %(account)s | Entry: %(entry)s<br/>"
                            "Status: <b>%(state)s</b>",
                            ref=deferred.name,
                            picking=move.picking_id.name,
                            product=product.display_name,
                            qty=qty_to_reconcile,
                            frozen=frozen_cost,
                            receipt=receipt_unit_cost,
                            diff=diff_total,
                            label=direction,
                            account=(
                                deferred.price_diff_account_id.display_name
                                if deferred.price_diff_account_id
                                else 'N/A'
                            ),
                            entry=journal_entry.name if journal_entry else 'None',
                            state=new_state.upper(),
                        ))
                except Exception as e:
                    _logger.warning(
                        "[PT-DEFERRED] Could not post reconciliation chatter: %s",
                        e,
                    )

                receipt_qty_pool -= qty_to_reconcile

            _logger.info(
                "[PT-DEFERRED] Product %s done | "
                "Unused receipt qty: %.4f",
                product.display_name, receipt_qty_pool,
            )

    # ================================================================
    # PRIVATE: Post price difference journal entry
    # ================================================================

    def _pt_post_price_diff_entry(self, deferred, receipt_move, qty_reconciled,
                                   frozen_cost, receipt_cost, diff_total):
        """
        diff_total > 0  WIP under-costed:
            DR  Price Difference Account   (loss)
            CR  Stock Valuation Account

        diff_total < 0  WIP over-costed:
            DR  Stock Valuation Account
            CR  Price Difference Account   (gain)
        """
        _logger.info(SEP_THIN)
        _logger.info("[PT-DEFERRED] === POST PRICE DIFFERENCE JOURNAL ENTRY ===")
        _logger.info(
            "[PT-DEFERRED] Deferred: %s | Product: %s | Qty: %.4f | "
            "Frozen: %.4f | Receipt: %.4f | Diff: %.4f",
            deferred.name, deferred.product_id.display_name,
            qty_reconciled, frozen_cost, receipt_cost, diff_total,
        )

        product = deferred.product_id
        company = deferred.company_id
        currency = company.currency_id
        categ = product.categ_id

        price_diff_account = categ.property_account_creditor_price_difference_categ
        stock_val_account = categ.property_stock_valuation_account_id
        stock_journal = categ.property_stock_journal

        _logger.info(
            "[PT-DEFERRED] Accounts | Price Diff: %s | Stock Val: %s | Journal: %s",
            price_diff_account.display_name if price_diff_account else 'MISSING',
            stock_val_account.display_name if stock_val_account else 'MISSING',
            stock_journal.display_name if stock_journal else 'MISSING',
        )

        missing = []
        if not price_diff_account:
            missing.append("Price Difference Account (category: %s)" % categ.name)
        if not stock_val_account:
            missing.append("Stock Valuation Account (category: %s)" % categ.name)
        if not stock_journal:
            missing.append("Stock Journal (category: %s)" % categ.name)

        if missing:
            _logger.error(
                "[PT-DEFERRED] CANNOT POST — missing account config:\n  %s",
                "\n  ".join(missing),
            )
            return False

        abs_diff = abs(diff_total)
        diff_per_unit = receipt_cost - frozen_cost

        if diff_total > 0:
            debit_account = price_diff_account
            credit_account = stock_val_account
            direction = "UNDER-COSTED: DR Price Diff / CR Stock Val"
        else:
            debit_account = stock_val_account
            credit_account = price_diff_account
            direction = "OVER-COSTED: DR Stock Val / CR Price Diff"

        _logger.info(
            "[PT-DEFERRED] %s | Amount: %.4f", direction, abs_diff
        )

        line_name = (
            "Deferred Val Diff - %s | %.4f x %+.4f | MO: %s"
        ) % (
            product.display_name,
            qty_reconciled,
            diff_per_unit,
            deferred.mo_id.name if deferred.mo_id else 'N/A',
        )
        narration = (
            "Deferred Valuation Reconciliation\n"
            "Deferred Ref  : %s\n"
            "MO            : %s\n"
            "Product       : %s\n"
            "Receipt       : %s\n"
            "Qty Reconciled: %.4f\n"
            "Frozen Cost   : %.4f\n"
            "Receipt Cost  : %.4f\n"
            "Diff per Unit : %+.4f\n"
            "Total Diff    : %+.4f"
        ) % (
            deferred.name,
            deferred.mo_id.name if deferred.mo_id else 'N/A',
            product.display_name,
            receipt_move.picking_id.name,
            qty_reconciled,
            frozen_cost,
            receipt_cost,
            diff_per_unit,
            diff_total,
        )

        rounded_amount = float_round(abs_diff, precision_rounding=currency.rounding)

        move_vals = {
            'journal_id': stock_journal.id,
            'date': fields.Date.today(),
            'ref': "DVR: %s / %s" % (deferred.name, receipt_move.picking_id.name),
            'narration': narration,
            'company_id': company.id,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_account.id,
                    'name': line_name,
                    'debit': rounded_amount,
                    'credit': 0.0,
                    'product_id': product.id,
                }),
                (0, 0, {
                    'account_id': credit_account.id,
                    'name': line_name,
                    'debit': 0.0,
                    'credit': rounded_amount,
                    'product_id': product.id,
                }),
            ],
        }

        try:
            account_move = self.env['account.move'].create(move_vals)
            account_move.action_post()
            _logger.info(
                "[PT-DEFERRED] POSTED | Name: %s | Amount: %.4f | "
                "DR: %s | CR: %s",
                account_move.name, rounded_amount,
                debit_account.code, credit_account.code,
            )
            return account_move
        except Exception as e:
            _logger.error(
                "[PT-DEFERRED] FAILED to post journal entry: %s",
                str(e), exc_info=True,
            )
            return False
