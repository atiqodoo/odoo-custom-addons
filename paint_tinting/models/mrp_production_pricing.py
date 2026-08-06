# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockMoveForTinting(models.Model):
    """Expose BOM line tinting data on stock moves for the Tinting Pricing tab."""
    _inherit = 'stock.move'

    tinting_is_colorant = fields.Boolean(
        string='Colorant',
        related='bom_line_id.is_colorant_line',
        store=False,
        readonly=True,
    )
    tinting_shots = fields.Float(
        string='Shots',
        related='bom_line_id.colorant_shots',
        store=False,
        readonly=True,
        digits=(10, 2),
    )
    tinting_ml = fields.Float(
        string='Vol (ml)',
        related='bom_line_id.colorant_ml',
        store=False,
        readonly=True,
        digits=(10, 3),
    )
    tinting_unit_cost_incl_vat = fields.Float(
        string='Unit Cost (incl. VAT)',
        related='bom_line_id.unit_cost_incl_vat',
        store=False,
        readonly=True,
        digits='Product Price',
    )
    tinting_line_cost_incl_vat = fields.Float(
        string='Line Total (incl. VAT)',
        related='bom_line_id.cost_incl_vat',
        store=False,
        readonly=True,
        digits='Product Price',
    )


class MrpProductionPricing(models.Model):
    """Per-MO/lot selling price and cost summary for tinting orders.

    Each tinting MO (including duplicates) carries its own selling price so
    every lot can be priced independently — entered either here on the MO or
    during the initial tinting wizard.
    """
    _inherit = 'mrp.production'

    # ------------------------------------------------------------------
    # SELLING PRICE (per lot/MO)
    # ------------------------------------------------------------------
    mo_selling_price = fields.Float(
        string='Selling Price (KES incl. VAT)',
        digits='Product Price',
        tracking=True,
        copy=False,
        help='Selling price for this specific MO/lot. '
             'Each duplicate MO must have its own price set.',
    )

    mo_selling_price_set = fields.Boolean(
        string='Price Set',
        compute='_compute_mo_selling_price_set',
        store=True,
    )

    # ------------------------------------------------------------------
    # COST SUMMARY (computed from BOM lines — incl. VAT / landed costs)
    # ------------------------------------------------------------------
    mo_base_cost = fields.Float(
        string='Base Product Cost (incl. VAT)',
        compute='_compute_mo_costs',
        digits='Product Price',
    )
    mo_colorant_cost = fields.Float(
        string='Colorant Cost (incl. VAT)',
        compute='_compute_mo_costs',
        digits='Product Price',
    )
    mo_total_cost = fields.Float(
        string='Total Cost (incl. VAT)',
        compute='_compute_mo_costs',
        digits='Product Price',
    )

    # ------------------------------------------------------------------
    # PROFIT (computed)
    # ------------------------------------------------------------------
    mo_profit = fields.Float(
        string='Profit (KES)',
        compute='_compute_mo_profit',
        digits='Product Price',
    )
    mo_margin_percent = fields.Float(
        string='Margin %',
        compute='_compute_mo_profit',
        digits=(5, 2),
    )

    # ------------------------------------------------------------------
    # COMPUTES
    # ------------------------------------------------------------------
    @api.depends('mo_selling_price')
    def _compute_mo_selling_price_set(self):
        for mo in self:
            mo.mo_selling_price_set = mo.mo_selling_price > 0

    @api.depends(
        'bom_id',
        'bom_id.bom_line_ids',
        'bom_id.bom_line_ids.cost_incl_vat',
        'bom_id.bom_line_ids.is_colorant_line',
    )
    def _compute_mo_costs(self):
        for mo in self:
            if not mo.bom_id:
                mo.mo_base_cost = 0.0
                mo.mo_colorant_cost = 0.0
                mo.mo_total_cost = 0.0
                continue
            base = sum(
                l.cost_incl_vat for l in mo.bom_id.bom_line_ids
                if not l.is_colorant_line
            )
            colorant = sum(
                l.cost_incl_vat for l in mo.bom_id.bom_line_ids
                if l.is_colorant_line
            )
            mo.mo_base_cost = base
            mo.mo_colorant_cost = colorant
            mo.mo_total_cost = base + colorant

    @api.depends('mo_selling_price', 'mo_total_cost')
    def _compute_mo_profit(self):
        for mo in self:
            if mo.mo_selling_price > 0 and mo.mo_total_cost > 0:
                mo.mo_profit = mo.mo_selling_price - mo.mo_total_cost
                mo.mo_margin_percent = (mo.mo_profit / mo.mo_selling_price) * 100
            else:
                mo.mo_profit = 0.0
                mo.mo_margin_percent = 0.0
