# -*- coding: utf-8 -*-
"""stock_valuation_layer.py

Extends stock.valuation.layer with POS negative-origin tracking and FIFO
reconciliation state fields.

Fields Added
------------
pos_negative_origin     : Boolean flag — True when this negative layer was
                          produced by a POS force-validated oversell.
pos_order_id            : Many2one to pos.order for full traceability.
reconciled_qty          : Cumulative units reconciled across all receipt /
                          adjustment events (FIFO order).
is_fully_reconciled     : Computed — True when reconciled_qty >= abs(quantity).
open_reconcile_qty      : Computed — remaining unreconciled negative units.
reconciliation_line_ids : One2many audit log records.
price_diff_move_ids     : Many2many to all price-difference account.moves
                          generated during reconciliation events.

Helper Method
-------------
_get_open_negative_layers(product_id, company_id) — returns open POS negative
layers ordered FIFO (oldest first), used by the receipt reconciliation logic.
"""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockValuationLayer(models.Model):
    """Extends stock.valuation.layer with POS oversell tracking and FIFO
    AVCO reconciliation state management.

    Standard Odoo AVCO vacuum operates on ``remaining_qty`` (built-in).
    This module introduces a parallel ``reconciled_qty`` field so that
    our FIFO reconciliation logic can advance independently of—and without
    corrupting—the standard vacuum bookkeeping.  The ``_run_avco_vacuum``
    override in stock_move.py skips layers flagged as ``pos_negative_origin``
    to prevent double-posting of price difference journal entries.
    """

    _inherit = 'stock.valuation.layer'

    # ── POS Origin Identification ─────────────────────────────────────────────

    pos_negative_origin = fields.Boolean(
        string='POS Negative Origin',
        default=False,
        index=True,
        help=(
            'Set to True when this negative layer was created by a POS '
            'force-validated outgoing picking (oversell scenario).  '
            'Governs FIFO reconciliation targeting and prevents the standard '
            'AVCO vacuum from processing the same layer twice.'
        ),
    )

    pos_order_id = fields.Many2one(
        comodel_name='pos.order',
        string='Source POS Order',
        ondelete='set null',
        index=True,
        help='The POS order that triggered force-validation and created this negative layer.',
    )

    # ── FIFO Reconciliation State ─────────────────────────────────────────────

    reconciled_qty = fields.Float(
        string='Reconciled Qty',
        default=0.0,
        digits='Product Unit of Measure',
        help=(
            'Cumulative units of this negative layer that have been matched by '
            'incoming vendor receipts or inventory adjustment gains (FIFO order).  '
            'Written by _reconcile_neg_layers_for_product() and '
            '_reconcile_neg_layers_via_adjustment().'
        ),
    )

    is_fully_reconciled = fields.Boolean(
        string='Fully Reconciled',
        compute='_compute_reconciliation_state',
        store=True,
        index=True,
        help='True when reconciled_qty >= abs(quantity).  Negative layer is fully closed.',
    )

    open_reconcile_qty = fields.Float(
        string='Open (Unreconciled) Qty',
        compute='_compute_reconciliation_state',
        store=True,
        digits='Product Unit of Measure',
        help='Remaining unreconciled negative units.  Positive number = still open.',
    )

    # ── Linked Records ────────────────────────────────────────────────────────

    reconciliation_line_ids = fields.One2many(
        comodel_name='pos.neg.reconciliation.line',
        inverse_name='neg_layer_id',
        string='Reconciliation Events',
        help='Audit log of every receipt or adjustment that partially/fully closed this layer.',
    )

    price_diff_move_ids = fields.Many2many(
        comodel_name='account.move',
        relation='svl_price_diff_move_rel',
        column1='svl_id',
        column2='move_id',
        string='Price Difference JEs',
        help=(
            'All account.move entries created to record the AVCO price difference '
            'when this negative layer was reconciled at a purchase price that '
            'differed from the original AVCO at the time of the POS sale.'
        ),
    )

    # ── Computed Fields ───────────────────────────────────────────────────────

    @api.depends('quantity', 'reconciled_qty')
    def _compute_reconciliation_state(self):
        """Derive is_fully_reconciled and open_reconcile_qty from stored values.

        Logic:
        - For positive or zero layers: always considered reconciled (not applicable).
        - For negative layers: open_qty = abs(quantity) - reconciled_qty.
          Fully reconciled when open_qty <= 0.

        Called on write to reconciled_qty or quantity.  Stored so that domain
        filters such as [('is_fully_reconciled','=',False)] hit the index.
        """
        for layer in self:
            if layer.quantity >= 0:
                layer.is_fully_reconciled = True
                layer.open_reconcile_qty = 0.0
                continue

            abs_qty = abs(layer.quantity)
            open_qty = abs_qty - layer.reconciled_qty
            layer.open_reconcile_qty = max(0.0, open_qty)
            layer.is_fully_reconciled = (layer.reconciled_qty >= abs_qty - 1e-9)

            _logger.debug(
                '[NegStock] SVL id=%d product="%s": abs_qty=%.4f reconciled=%.4f '
                'open=%.4f is_fully=%s',
                layer.id,
                layer.product_id.display_name if layer.product_id else '?',
                abs_qty,
                layer.reconciled_qty,
                layer.open_reconcile_qty,
                layer.is_fully_reconciled,
            )

    # ── Class-Level Query Helper ──────────────────────────────────────────────

    @api.model
    def _get_open_negative_layers(self, product_id, company_id=None):
        """Return all open POS negative layers for a product in FIFO order.

        A layer is considered 'open' when:
          - quantity < 0
          - pos_negative_origin is True
          - is_fully_reconciled is False

        FIFO order is enforced via ``order='create_date asc'``, matching the
        oldest oversell event to the earliest replenishment receipt.

        Args:
            product_id (int): ID of the product.product to query.
            company_id (int | None): If provided, restricts to that company.
                Useful in multi-company environments.

        Returns:
            stock.valuation.layer recordset: Open negative layers, oldest first.
        """
        domain = [
            ('product_id', '=', product_id),
            ('quantity', '<', 0),
            ('pos_negative_origin', '=', True),
            ('is_fully_reconciled', '=', False),
        ]
        if company_id:
            domain.append(('company_id', '=', company_id))

        layers = self.search(domain, order='create_date asc')

        _logger.debug(
            '[NegStock] _get_open_negative_layers: product_id=%d company_id=%s → %d layer(s)',
            product_id,
            company_id or 'any',
            len(layers),
        )
        return layers
