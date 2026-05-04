# -*- coding: utf-8 -*-
"""pos_neg_reconciliation_line.py

Persistent audit log for every AVCO reconciliation event that partially or
fully closes a POS-originated negative stock.valuation.layer.

One record is written per (negative layer × receipt/adjustment) pair.  A single
vendor receipt may produce several records when it reconciles multiple layers
for the same product (FIFO walk).

This model is the backbone of the Negative Stock Reconciliation report.
"""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosNegReconciliationLine(models.Model):
    """Audit log record for one reconciliation event against one negative SVL.

    Created by:
      - stock_move._reconcile_neg_layers_for_product() — vendor receipt path.
      - stock_quant._reconcile_neg_layers_via_adjustment() — inventory adjustment path.

    Read by:
      - The QWeb reconciliation report (report/neg_stock_reconciliation_template.xml).
      - The Reconciliation Log list view (views/neg_stock_reconciliation_view.xml).
    """

    _name = 'pos.neg.reconciliation.line'
    _description = 'POS Negative Stock Reconciliation Log'
    _order = 'reconcile_date desc, id desc'
    _rec_name = 'display_name'

    # ── Core Relations ────────────────────────────────────────────────────────

    neg_layer_id = fields.Many2one(
        comodel_name='stock.valuation.layer',
        string='Negative SVL',
        required=True,
        ondelete='cascade',
        index=True,
        help='The negative stock.valuation.layer being partially or fully reconciled.',
    )

    pos_order_id = fields.Many2one(
        comodel_name='pos.order',
        string='POS Order',
        related='neg_layer_id.pos_order_id',
        store=True,
        index=True,
        help='Original POS order responsible for the negative stock.',
    )

    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        related='neg_layer_id.product_id',
        store=True,
        index=True,
    )

    source_picking_id = fields.Many2one(
        comodel_name='stock.picking',
        string='Source Receipt / Adjustment',
        ondelete='set null',
        index=True,
        help=(
            'Vendor receipt (incoming) or inventory adjustment picking that '
            'triggered this reconciliation event.'
        ),
    )

    # ── Timing ───────────────────────────────────────────────────────────────

    reconcile_date = fields.Datetime(
        string='Reconciliation Date',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    # ── Quantities & Costs ────────────────────────────────────────────────────

    reconcile_qty = fields.Float(
        string='Reconciled Qty',
        required=True,
        digits='Product Unit of Measure',
        help='Units reconciled in this single event (≤ open qty on the negative layer).',
    )

    original_cost = fields.Float(
        string='Cost at Sale (AVCO)',
        digits='Product Price',
        help='The unit_cost stamped on the negative SVL at time of POS force-sale.',
    )

    incoming_cost = fields.Float(
        string='Receipt / Adjustment Cost',
        digits='Product Price',
        help=(
            'Unit cost from the vendor receipt (purchase price) or the current '
            'standard_price for inventory adjustments.'
        ),
    )

    price_diff_per_unit = fields.Float(
        string='Price Diff / Unit',
        compute='_compute_price_diff',
        store=True,
        digits='Product Price',
        help='incoming_cost − original_cost.  Positive = COGS was under-stated at sale.',
    )

    price_diff_amount = fields.Float(
        string='Total Price Difference',
        compute='_compute_price_diff',
        store=True,
        digits='Account',
        help='reconcile_qty × price_diff_per_unit.  The monetary gap corrected by the JE.',
    )

    # ── Journal Entry ─────────────────────────────────────────────────────────

    price_diff_move_id = fields.Many2one(
        comodel_name='account.move',
        string='Price Diff JE',
        ondelete='set null',
        help='The account.move generated for the price difference (None for adjustments).',
    )

    # ── Classification ────────────────────────────────────────────────────────

    reconcile_type = fields.Selection(
        selection=[
            ('receipt', 'Vendor Receipt'),
            ('adjustment', 'Inventory Adjustment'),
        ],
        string='Type',
        required=True,
        default='receipt',
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='neg_layer_id.company_id',
        store=True,
    )

    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='neg_layer_id.currency_id',
        store=True,
    )

    is_fully_reconciled = fields.Boolean(
        string='Layer Fully Reconciled',
        related='neg_layer_id.is_fully_reconciled',
        store=True,
        help=(
            'Mirrors is_fully_reconciled from the parent negative SVL.  '
            'Used as a list-view decoration condition to highlight rows '
            'whose negative exposure is fully closed.'
        ),
    )

    note = fields.Text(
        string='Note',
        help='Free-text context set by the reconciliation logic for accountant review.',
    )

    display_name = fields.Char(
        string='Label',
        compute='_compute_display_name',
        store=True,
    )

    # ── Computed ──────────────────────────────────────────────────────────────

    @api.depends('reconcile_qty', 'original_cost', 'incoming_cost')
    def _compute_price_diff(self):
        """Compute per-unit and total price difference for this reconciliation event.

        A positive price_diff_amount means the goods were replenished at a higher
        cost than the AVCO recorded at the time of sale — COGS was under-stated
        and the difference is an additional expense (Dr Price Diff / Cr Stock Val).

        A negative price_diff_amount means the goods arrived cheaper — COGS was
        over-stated and a cost recovery entry is required (Dr Stock Val / Cr Price Diff).
        """
        for line in self:
            diff_unit = line.incoming_cost - line.original_cost
            line.price_diff_per_unit = diff_unit
            line.price_diff_amount = line.reconcile_qty * diff_unit
            _logger.debug(
                '[NegStock] ReconciliationLine id=%d: diff/unit=%.6f total_diff=%.4f',
                line.id or 0,
                diff_unit,
                line.price_diff_amount,
            )

    @api.depends('product_id', 'reconcile_date', 'reconcile_type', 'reconcile_qty')
    def _compute_display_name(self):
        """Build a human-readable label used in chatter links and list views."""
        type_labels = dict(self._fields['reconcile_type'].selection)
        for line in self:
            product = line.product_id.display_name or '?'
            date = (
                fields.Datetime.to_string(line.reconcile_date)[:10]
                if line.reconcile_date
                else '?'
            )
            rtype = type_labels.get(line.reconcile_type, '')
            qty = line.reconcile_qty or 0.0
            line.display_name = f'[{rtype}] {product} — {qty:.2f} u — {date}'
