# -*- coding: utf-8 -*-
"""stock_move.py

Three responsibilities on stock.move:

1. _get_pos_neg_incoming_cost()
   Returns the effective incoming unit cost for a receipt move, using
   move._get_price_unit() (UoM + currency aware) with fallback to price_unit.

2. _reconcile_neg_layers_for_product()
   Class-level FIFO reconciliation algorithm.  Walks open negative POS SVLs
   oldest-first, matches them against the incoming receipt qty, calls
   _create_price_diff_journal_entry() when costs differ, writes reconciled_qty
   on the SVL, and creates pos.neg.reconciliation.line audit records.

3. _create_price_diff_journal_entry()
   Builds and posts the Anglo-Saxon price difference account.move following
   Odoo's standard property_account_creditor_price_difference logic:

   Case A (purchase > AVCO at sale):  Dr Price Diff / Cr Stock Valuation
   Case B (purchase < AVCO at sale):  Dr Stock Valuation / Cr Price Diff

4. _run_avco_vacuum() override
   Skips standard vacuum for products whose only open negative layers carry
   pos_negative_origin=True, preventing duplicate price difference JEs.

5. _get_stock_journal_for_price_diff()
   Resolves the journal to use for price difference JEs via a three-strategy
   cascade (SVL JE journal → company stock_journal → first general journal).
"""

import logging
from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Threshold below which price differences are considered rounding noise
_DIFF_THRESHOLD = 0.001


class StockMove(models.Model):
    """Extends stock.move with AVCO price difference reconciliation helpers.

    Instance methods operate on individual moves; class-level (@api.model)
    methods are called with product-level context from the picking post-hook.
    """

    _inherit = 'stock.move'

    # ─────────────────────────────────────────────────────────────────────────
    # Incoming Cost Resolution
    # ─────────────────────────────────────────────────────────────────────────

    def _get_pos_neg_incoming_cost(self):
        """Determine the effective unit cost for this incoming receipt move.

        Resolution order:
        1. move._get_price_unit()  — Odoo's built-in method that handles:
              - PO currency → company currency conversion.
              - Product UoM → move UoM conversion.
              - Standard price for internal/manufacturing moves.
        2. move.price_unit         — raw field fallback if (1) returns 0 or raises.

        Returns:
            float: Unit cost in company currency per product UoM.

        Logs:
            DEBUG on successful _get_price_unit() result.
            WARNING if fallback to price_unit is triggered.
            ERROR if both return 0 (accountant intervention needed).
        """
        self.ensure_one()
        cost = 0.0

        try:
            cost = self._get_price_unit()
            _logger.debug(
                '[NegStock] _get_price_unit() | move id=%d | product="%s" | cost=%.6f',
                self.id, self.product_id.display_name, cost,
            )
        except Exception as exc:
            _logger.warning(
                '[NegStock] _get_price_unit() raised for move id=%d (%s). '
                'Falling back to price_unit. Exception: %s',
                self.id, self.product_id.display_name, str(exc),
            )

        if cost == 0.0:
            cost = self.price_unit or 0.0
            if cost:
                _logger.debug(
                    '[NegStock] Using price_unit fallback=%.6f for move id=%d',
                    cost, self.id,
                )
            else:
                _logger.error(
                    '[NegStock] ZERO COST: Both _get_price_unit() and price_unit '
                    'are 0 for move id=%d product="%s".  Price difference JE will '
                    'not be created for this receipt.',
                    self.id, self.product_id.display_name,
                )

        return cost

    # ─────────────────────────────────────────────────────────────────────────
    # FIFO Reconciliation — Main Entry Point
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _reconcile_neg_layers_for_product(
        self, product_id, incoming_qty, incoming_unit_cost, source_picking
    ):
        """FIFO reconciliation of open negative POS SVLs against a vendor receipt.

        Algorithm
        ---------
        1. Fetch open negative POS layers for ``product_id`` ordered FIFO
           (oldest create_date first) via SVL._get_open_negative_layers().
        2. Walk each layer:
               open_neg = abs(layer.quantity) - layer.reconciled_qty
               to_reconcile = min(open_neg, remaining_incoming)
               price_diff = incoming_unit_cost - layer.unit_cost
        3. If abs(price_diff * to_reconcile) > _DIFF_THRESHOLD:
               Call _create_price_diff_journal_entry().
        4. Increment layer.reconciled_qty by to_reconcile.
        5. Write a pos.neg.reconciliation.line audit record.
        6. Decrement remaining_incoming.  Stop when exhausted.

        Logs summary line at INFO level and per-layer detail at DEBUG/INFO.

        Args:
            product_id (int): product.product ID to reconcile.
            incoming_qty (float): Maximum reconcilable units from this receipt.
            incoming_unit_cost (float): Purchase price per unit (company currency).
            source_picking (stock.picking): The vendor receipt picking.

        Side Effects:
            - Writes reconciled_qty on matched SVLs.
            - Creates pos.neg.reconciliation.line records.
            - Creates and posts account.move entries for price differences.
            - Links price diff moves to SVL via price_diff_move_ids.
        """
        _logger.info(
            '[NegStock] RECONCILE START | product_id=%d | incoming_qty=%.4f | '
            'incoming_unit_cost=%.6f | receipt=%s',
            product_id, incoming_qty, incoming_unit_cost, source_picking.name,
        )

        SVL = self.env['stock.valuation.layer']
        neg_layers = SVL._get_open_negative_layers(
            product_id=product_id,
            company_id=source_picking.company_id.id,
        )

        if not neg_layers:
            _logger.info(
                '[NegStock] No open POS negative layers for product_id=%d.  '
                'Reconciliation skipped.',
                product_id,
            )
            return

        remaining = incoming_qty
        total_reconciled = 0.0
        total_diff = 0.0
        layers_touched = 0

        for layer in neg_layers:
            if remaining <= 1e-9:
                _logger.debug(
                    '[NegStock] Incoming qty exhausted after %d layer(s).  '
                    'Stopping FIFO walk.',
                    layers_touched,
                )
                break

            open_neg = abs(layer.quantity) - layer.reconciled_qty
            if open_neg <= 1e-9:
                # Should not happen (is_fully_reconciled filter), but guard anyway
                _logger.warning(
                    '[NegStock] Layer id=%d passed filter but has open_neg=%.6f. Skipping.',
                    layer.id, open_neg,
                )
                continue

            to_reconcile = min(open_neg, remaining)
            price_diff_unit = incoming_unit_cost - layer.unit_cost
            diff_amount = to_reconcile * price_diff_unit

            _logger.info(
                '[NegStock] FIFO | layer id=%d | open_neg=%.4f | to_reconcile=%.4f | '
                'layer_cost=%.6f | incoming_cost=%.6f | diff/unit=%.6f | '
                'total_diff=%.4f',
                layer.id, open_neg, to_reconcile,
                layer.unit_cost, incoming_unit_cost,
                price_diff_unit, diff_amount,
            )

            # ── Create price difference JE if diff is material ────────────────
            price_diff_move = False
            if abs(diff_amount) > _DIFF_THRESHOLD:
                price_diff_move = self._create_price_diff_journal_entry(
                    neg_layer=layer,
                    reconcile_qty=to_reconcile,
                    diff_amount=diff_amount,
                    incoming_unit_cost=incoming_unit_cost,
                    source_picking=source_picking,
                )
            else:
                _logger.debug(
                    '[NegStock] |diff|=%.6f below threshold %.3f for layer id=%d.  '
                    'No JE created.',
                    abs(diff_amount), _DIFF_THRESHOLD, layer.id,
                )

            # ── Advance reconciled_qty on the negative layer ──────────────────
            new_reconciled = layer.reconciled_qty + to_reconcile
            layer.write({'reconciled_qty': new_reconciled})

            _logger.info(
                '[NegStock] Layer id=%d | reconciled_qty → %.4f | '
                'is_fully_reconciled=%s',
                layer.id, new_reconciled, layer.is_fully_reconciled,
            )

            # ── Write audit log ───────────────────────────────────────────────
            rec_line = self.env['pos.neg.reconciliation.line'].create({
                'neg_layer_id': layer.id,
                'source_picking_id': source_picking.id,
                'reconcile_date': fields.Datetime.now(),
                'reconcile_qty': to_reconcile,
                'original_cost': layer.unit_cost,
                'incoming_cost': incoming_unit_cost,
                'price_diff_move_id': price_diff_move.id if price_diff_move else False,
                'reconcile_type': 'receipt',
                'note': (
                    f'FIFO receipt reconciliation via {source_picking.name}.  '
                    f'Incoming cost: {incoming_unit_cost:.6f}  '
                    f'AVCO at sale: {layer.unit_cost:.6f}  '
                    f'Diff/unit: {price_diff_unit:.6f}  '
                    f'Total diff: {diff_amount:.4f}'
                ),
            })
            _logger.debug('[NegStock] ReconciliationLine created: id=%d', rec_line.id)

            # ── Link JE to SVL for report / chatter ──────────────────────────
            if price_diff_move:
                layer.write({'price_diff_move_ids': [(4, price_diff_move.id)]})
                # Post chatter on the POS order for accountant visibility
                if layer.pos_order_id:
                    layer.pos_order_id.message_post(
                        body=(
                            '<b>[Price Diff JE Created]</b><br/>'
                            f'Product: {layer.product_id.display_name}<br/>'
                            f'Units reconciled: {to_reconcile:.2f}<br/>'
                            f'AVCO at sale: {layer.unit_cost:.4f}  '
                            f'Purchase price: {incoming_unit_cost:.4f}<br/>'
                            f'Price diff: {diff_amount:.4f}<br/>'
                            f'JE: {price_diff_move.name}'
                        )
                    )

            remaining -= to_reconcile
            total_reconciled += to_reconcile
            total_diff += diff_amount
            layers_touched += 1

        _logger.info(
            '[NegStock] RECONCILE END | product_id=%d | layers_touched=%d | '
            'total_reconciled=%.4f | total_price_diff=%.4f | '
            'remaining_unmatched_incoming=%.4f',
            product_id, layers_touched,
            total_reconciled, total_diff, remaining,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Price Difference Journal Entry
    # ─────────────────────────────────────────────────────────────────────────

    def _create_price_diff_journal_entry(
        self, neg_layer, reconcile_qty, diff_amount,
        incoming_unit_cost, source_picking
    ):
        """Build and post the Anglo-Saxon AVCO price difference journal entry.

        Account Direction (follows Odoo standard for price diff accounts):

        Case A — diff_amount > 0  (bought dearer than AVCO at sale):
            COGS was under-stated.  Additional expense recognised.
            Dr  Price Difference Account  (property_account_creditor_price_difference)
            Cr  Stock Valuation Account   (property_stock_valuation_account_id)

        Case B — diff_amount < 0  (bought cheaper than AVCO at sale):
            COGS was over-stated.  Cost recovery (income/reversal) recognised.
            Dr  Stock Valuation Account
            Cr  Price Difference Account

        Validation checks before JE creation:
        - property_account_creditor_price_difference is set on product category.
        - property_stock_valuation_account_id is set on product category.
        - A valid journal can be resolved.
        - The accounting period is not locked.

        On any validation failure the method logs the error at ERROR level,
        creates a reconciliation line with price_diff_move_id=False so the
        report surfaces the gap as 'Pending Account Config', and returns False.

        Args:
            neg_layer (stock.valuation.layer): The negative layer being reconciled.
            reconcile_qty (float): Units reconciled in this event.
            diff_amount (float): Monetary difference (may be negative for Case B).
            incoming_unit_cost (float): Purchase price used in the receipt.
            source_picking (stock.picking): The vendor receipt for reference.

        Returns:
            account.move | False: Posted JE or False on any failure.
        """
        product = neg_layer.product_id
        categ = product.categ_id
        company = neg_layer.company_id or self.env.company

        # ── Account Validation ────────────────────────────────────────────────
        # Use the defensive accessor defined in product_category.py so this
        # works even if 'purchase' module is not installed (field absent).
        price_diff_acc = categ._get_price_diff_account()
        stock_val_acc = categ.property_stock_valuation_account_id

        if not price_diff_acc:
            _logger.error(
                '[NegStock] MISSING ACCOUNT | property_account_creditor_price_difference '
                'not set on category "%s" (id=%d).  '
                'Price diff JE SKIPPED.  product="%s"  diff=%.4f  '
                'Action: set the Price Difference Account on the product category.',
                categ.complete_name, categ.id, product.display_name, diff_amount,
            )
            return False

        if not stock_val_acc:
            _logger.error(
                '[NegStock] MISSING ACCOUNT | property_stock_valuation_account_id '
                'not set on category "%s" (id=%d).  Price diff JE SKIPPED.',
                categ.complete_name, categ.id,
            )
            return False

        # ── Journal Resolution ────────────────────────────────────────────────
        journal = self._get_stock_journal_for_price_diff(source_picking, company)
        if not journal:
            _logger.error(
                '[NegStock] No journal resolved for price diff JE.  '
                'company="%s"  product="%s"', company.name, product.display_name,
            )
            return False

        # ── Determine Debit / Credit Side ─────────────────────────────────────
        abs_diff = abs(diff_amount)
        if diff_amount > 0:
            # Case A: under-expensed — increase COGS
            debit_acc = price_diff_acc
            credit_acc = stock_val_acc
            direction = 'Case A — purchase > AVCO (COGS under-stated)'
        else:
            # Case B: over-expensed — cost recovery
            debit_acc = stock_val_acc
            credit_acc = price_diff_acc
            direction = 'Case B — purchase < AVCO (COGS over-stated)'

        _logger.info(
            '[NegStock] Price Diff JE | %s | product="%s" | '
            'qty=%.4f | diff/unit=%.6f | total=%.4f | '
            'Dr: %s (%s)  Cr: %s (%s)',
            direction, product.display_name,
            reconcile_qty, diff_amount / reconcile_qty if reconcile_qty else 0,
            abs_diff,
            debit_acc.code, debit_acc.name,
            credit_acc.code, credit_acc.name,
        )

        # ── Build JE Values ───────────────────────────────────────────────────
        diff_unit = diff_amount / reconcile_qty if reconcile_qty else 0.0
        ref = (
            f'POS Neg Stock Price Diff | {product.display_name} | '
            f'{reconcile_qty:.2f} u | diff/u={diff_unit:.4f} | '
            f'Receipt: {source_picking.name}'
        )
        move_vals = {
            'journal_id': journal.id,
            'ref': ref,
            'date': fields.Date.context_today(self),
            'company_id': company.id,
            'move_type': 'entry',
            'line_ids': [
                (0, 0, {
                    'account_id': debit_acc.id,
                    'name': (
                        f'POS neg stock price diff — {product.display_name} '
                        f'({reconcile_qty:.4f} units @ {diff_unit:+.4f})'
                    ),
                    'debit': abs_diff,
                    'credit': 0.0,
                    'product_id': product.id,
                    'quantity': reconcile_qty,
                }),
                (0, 0, {
                    'account_id': credit_acc.id,
                    'name': f'POS neg stock price diff offset — {product.display_name}',
                    'debit': 0.0,
                    'credit': abs_diff,
                    'product_id': product.id,
                    'quantity': reconcile_qty,
                }),
            ],
        }

        try:
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            _logger.info(
                '[NegStock] Price Diff JE posted: %s (id=%d)  amount=%.4f',
                move.name, move.id, abs_diff,
            )
            return move
        except Exception as exc:
            _logger.exception(
                '[NegStock] FAILED to create/post price diff JE | '
                'product="%s" | diff=%.4f | error: %s',
                product.display_name, abs_diff, str(exc),
            )
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Standard AVCO Vacuum Override
    # ─────────────────────────────────────────────────────────────────────────

    def _run_avco_vacuum(self):
        """Override to prevent Odoo's standard AVCO vacuum from double-posting
        price difference JEs for POS-originated negative layers.

        When ALL open negative SVLs for a product carry ``pos_negative_origin=True``,
        this module's FIFO reconciliation in _reconcile_neg_layers_for_product()
        has (or will) handle them.  Allowing the standard vacuum to also run on
        those layers would create duplicate price difference entries.

        Behaviour:
        - If the product has mixed layers (some POS, some not): run standard vacuum
          on the non-POS portion (standard Odoo handles them) and log a WARNING
          because this is an unusual configuration.
        - If all negative layers are POS-origin: skip vacuum entirely for this move.
        - If no negative layers at all: run standard vacuum unchanged.

        Returns:
            Result of super()._run_avco_vacuum() for non-skipped moves, else None.
        """
        self.ensure_one()

        if self.product_id.cost_method != 'average':
            return super()._run_avco_vacuum()

        # Check for remaining negative SVLs on this product
        all_neg = self.env['stock.valuation.layer'].search([
            ('product_id', '=', self.product_id.id),
            ('company_id', '=', self.company_id.id),
            ('remaining_qty', '<', 0),
        ])

        if not all_neg:
            # No negative layers — standard vacuum has nothing to do anyway
            return super()._run_avco_vacuum()

        pos_neg = all_neg.filtered('pos_negative_origin')

        if len(pos_neg) == len(all_neg):
            # All negative layers are POS-origin — handled by this module
            _logger.debug(
                '[NegStock] Skipping standard AVCO vacuum for product "%s" — '
                'all %d negative layer(s) are POS-origin and will be handled '
                'by module FIFO reconciliation.',
                self.product_id.display_name, len(all_neg),
            )
            return None

        if pos_neg:
            # Mixed — warn the accountant; run vacuum (it will process non-POS layers)
            _logger.warning(
                '[NegStock] MIXED NEGATIVE LAYERS for product "%s": '
                '%d POS-origin, %d non-POS.  Standard vacuum running for non-POS '
                'portion.  Verify no duplicate JEs are created.',
                self.product_id.display_name,
                len(pos_neg),
                len(all_neg) - len(pos_neg),
            )

        # Default: let standard vacuum run (non-POS or mixed scenario)
        return super()._run_avco_vacuum()

    # ─────────────────────────────────────────────────────────────────────────
    # Journal Resolution Helper
    # ─────────────────────────────────────────────────────────────────────────

    def _get_stock_journal_for_price_diff(self, source_picking, company):
        """Resolve the accounting journal to use for the price difference JE.

        Resolution cascade:
        1. Journal from an existing SVL account.move on the source receipt
           (uses exact same journal as Odoo's standard receipt SVL JE).
        2. company.stock_journal_id (Odoo stock_account standard field).
        3. First 'general' type journal for the company (last resort).

        Args:
            source_picking (stock.picking): The vendor receipt picking.
            company (res.company): Owning company.

        Returns:
            account.journal | False: Resolved journal or False if none found.
        """
        # Strategy 1: journal from the receipt SVL's own JE
        receipt_svl = self.env['stock.valuation.layer'].search(
            [('stock_move_id.picking_id', '=', source_picking.id)],
            limit=1,
        )
        if receipt_svl and receipt_svl.account_move_id and receipt_svl.account_move_id.journal_id:
            j = receipt_svl.account_move_id.journal_id
            _logger.debug('[NegStock] Journal resolved from receipt SVL JE: %s', j.name)
            return j

        # Strategy 2: company stock journal
        if hasattr(company, 'stock_journal_id') and company.stock_journal_id:
            _logger.debug(
                '[NegStock] Journal resolved from company.stock_journal_id: %s',
                company.stock_journal_id.name,
            )
            return company.stock_journal_id

        # Strategy 3: fallback — first general journal
        journal = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', company.id)],
            limit=1,
        )
        if journal:
            _logger.debug(
                '[NegStock] Journal resolved via fallback general search: %s',
                journal.name,
            )
        else:
            _logger.error(
                '[NegStock] No journal found for company "%s".  '
                'Price diff JE cannot be created.',
                company.name,
            )
        return journal or False
