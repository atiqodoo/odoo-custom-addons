# -*- coding: utf-8 -*-
"""stock_quant.py

Extends stock.quant._apply_inventory() to detect when an upward manual
inventory adjustment closes a POS-originated negative stock position.

Design decisions (per spec):
- The standard Odoo 'Inventory Gain' JE is left UNCHANGED:
      Dr  Stock Valuation Account
      Cr  Inventory Gain / Loss Account
  No modification to entries is made.  The module's contribution is
  purely audit trail + SVL reconciliation bookkeeping.

- All adjustments from negative → positive are treated as Gain regardless
  of whether the root cause was a scanning error or a legitimate oversell.
  (Manual COGS reversal for error cases remains the accountant's responsibility.)

- reconciled_qty on matching negative SVLs is updated so the report no
  longer shows them as open exposure.

- A pos.neg.reconciliation.line record is written for every layer touched.

- A chatter message is posted on the linked pos.order (if any) to give the
  accountant a full audit trail from the POS order screen.
"""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    """Extends stock.quant to integrate inventory adjustment gains with the
    POS negative stock reconciliation audit trail.

    The _apply_inventory() override follows the same pre-snapshot / super() /
    post-process pattern used in stock_picking._action_done() to capture the
    pre-adjustment negative qty before Odoo updates stock.
    """

    _inherit = 'stock.quant'

    def _apply_inventory(self):
        """Override inventory adjustment to reconcile open POS negative layers.

        Pre-Hook:
            For every quant being adjusted that has qty_available < 0, capture:
              - product reference
              - pre-adjustment qty_available (negative value)
              - the quant's location_id for debug context

        Standard Processing:
            super()._apply_inventory() runs unchanged, producing:
              - Updated stock.quant records
              - New stock.move (inventory adjustment type)
              - New stock.valuation.layer(s)
              - Standard 'Inventory Gain/Loss' account.move

        Post-Hook:
            For each product whose qty_available increased (and the pre-qty was
            negative), compute how many units closed the negative gap and call
            _reconcile_neg_layers_via_adjustment().

        Returns:
            Result of super()._apply_inventory().
        """
        # ── PRE-HOOK: Snapshot negative quantities before adjustment ──────────
        adjustment_snapshots = {}

        for quant in self:
            if quant.product_id.type != 'product':
                continue

            product = quant.product_id
            pre_qty = product.qty_available

            if pre_qty < 0:
                adjustment_snapshots[product.id] = {
                    'product': product,
                    'pre_qty': pre_qty,
                    'location_id': quant.location_id.id,
                    'location_name': quant.location_id.complete_name,
                    'inventory_qty': quant.inventory_quantity,
                }
                _logger.info(
                    '[NegStock] ADJUSTMENT PRE-CAPTURE | product="%s" (id=%d) | '
                    'pre_qty=%.4f | inventory_count=%.4f | location="%s"',
                    product.display_name, product.id,
                    pre_qty, quant.inventory_quantity,
                    quant.location_id.complete_name,
                )

        # ── STANDARD PROCESSING ───────────────────────────────────────────────
        result = super()._apply_inventory()

        # ── POST-HOOK: Reconcile negative layers for products that gained stock ─
        for pid, snap in adjustment_snapshots.items():
            product = snap['product']

            # Re-read post-adjustment qty (may have changed)
            post_qty = product.qty_available
            pre_qty = snap['pre_qty']

            _logger.info(
                '[NegStock] ADJUSTMENT POST | product="%s" (id=%d) | '
                'pre_qty=%.4f | post_qty=%.4f',
                product.display_name, pid, pre_qty, post_qty,
            )

            if post_qty > pre_qty:
                # Stock increased — some or all of the negative is closed
                qty_gained = post_qty - pre_qty
                units_closing_neg = min(qty_gained, abs(pre_qty))

                if units_closing_neg > 1e-9:
                    _logger.info(
                        '[NegStock] NEGATIVE CLOSURE via adjustment | '
                        'product="%s" | units_closing_negative=%.4f',
                        product.display_name, units_closing_neg,
                    )
                    self._reconcile_neg_layers_via_adjustment(product, units_closing_neg)
            else:
                _logger.debug(
                    '[NegStock] Adjustment did not increase qty for product "%s" '
                    '(post_qty=%.4f ≤ pre_qty=%.4f). No reconciliation needed.',
                    product.display_name, post_qty, pre_qty,
                )

        return result

    def _reconcile_neg_layers_via_adjustment(self, product, units_gained):
        """Mark POS negative SVLs as reconciled following an inventory adjustment gain.

        Uses the product's current standard_price as the effective reconciliation
        cost (no explicit purchase price for adjustments).  No price difference
        JE is created — the standard Odoo Inventory Gain JE already posts the
        correct entry.

        Creates pos.neg.reconciliation.line records for the reconciliation report
        and posts chatter messages on linked pos.orders.

        Args:
            product (product.product): Product whose negative stock is being closed.
            units_gained (float): Number of units transitioning from negative.

        Side Effects:
            - Writes reconciled_qty on matched SVLs.
            - Creates pos.neg.reconciliation.line records (type='adjustment').
            - Posts chatter on linked pos.orders.
        """
        SVL = self.env['stock.valuation.layer']
        neg_layers = SVL._get_open_negative_layers(
            product_id=product.id,
            company_id=self.env.company.id,
        )

        if not neg_layers:
            _logger.debug(
                '[NegStock] _reconcile_neg_layers_via_adjustment: no open POS '
                'negative layers for product "%s".  Nothing to reconcile.',
                product.display_name,
            )
            return

        current_avco = product.standard_price
        remaining = units_gained

        _logger.info(
            '[NegStock] ADJUSTMENT RECONCILE START | product="%s" | '
            'units_to_reconcile=%.4f | current_avco=%.6f | layers=%d',
            product.display_name, units_gained, current_avco, len(neg_layers),
        )

        for layer in neg_layers:
            if remaining <= 1e-9:
                break

            open_neg = abs(layer.quantity) - layer.reconciled_qty
            if open_neg <= 1e-9:
                continue

            to_reconcile = min(open_neg, remaining)
            new_reconciled = layer.reconciled_qty + to_reconcile

            layer.write({'reconciled_qty': new_reconciled})

            # Informational price diff (no JE — adjustment uses standard gain entry)
            cost_diff = current_avco - layer.unit_cost

            rec_line = self.env['pos.neg.reconciliation.line'].create({
                'neg_layer_id': layer.id,
                'source_picking_id': False,
                'reconcile_date': fields.Datetime.now(),
                'reconcile_qty': to_reconcile,
                'original_cost': layer.unit_cost,
                'incoming_cost': current_avco,
                'price_diff_move_id': False,
                'reconcile_type': 'adjustment',
                'note': (
                    f'Manual inventory adjustment gain.  '
                    f'Standard Odoo Inventory Gain JE used (no separate price diff JE).  '
                    f'AVCO at adjustment: {current_avco:.6f}  '
                    f'AVCO at original POS sale: {layer.unit_cost:.6f}  '
                    f'Informational diff/unit: {cost_diff:.6f}'
                ),
            })

            _logger.info(
                '[NegStock] ADJUSTMENT RECONCILE | layer id=%d | '
                'to_reconcile=%.4f | new_reconciled=%.4f | '
                'is_fully=%s | rec_line id=%d',
                layer.id, to_reconcile, new_reconciled,
                layer.is_fully_reconciled, rec_line.id,
            )

            # ── Post chatter on POS order for accountant audit trail ──────────
            if layer.pos_order_id:
                layer.pos_order_id.message_post(
                    body=(
                        '<b>[Negative Stock Closed via Adjustment]</b><br/>'
                        f'Product: {product.display_name}<br/>'
                        f'Units reconciled: {to_reconcile:.2f}<br/>'
                        f'AVCO at original sale: {layer.unit_cost:.4f}<br/>'
                        f'Current AVCO: {current_avco:.4f}<br/>'
                        f'Informational cost diff: {cost_diff:+.4f} / unit<br/>'
                        f'<i>Standard Inventory Gain JE used — no separate price diff JE.</i><br/>'
                        f'Reconciliation log: #{rec_line.id}'
                    )
                )
                _logger.info(
                    '[NegStock] Chatter posted on POS order %s.',
                    layer.pos_order_id.name,
                )

            remaining -= to_reconcile

        _logger.info(
            '[NegStock] ADJUSTMENT RECONCILE END | product="%s" | '
            'remaining_unmatched=%.4f',
            product.display_name, remaining,
        )
