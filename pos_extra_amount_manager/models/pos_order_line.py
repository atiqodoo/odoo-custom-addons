# -*- coding: utf-8 -*-
"""
POS Order Line Extension
Tracks extra amounts charged above pricelist per line.
Supports toggle: use quantity or count only 1 unit.
"""
from odoo import models, fields, api


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'
    
    # === TOGGLE: Default False, editable, triggers recompute ===
    calculate_with_quantity = fields.Boolean(
        string='Calculate with Quantity',
        default=False,  # CHANGED: default False
        help="If off: extra = per unit × 1. If on: × quantity"
    )
    
    # === PRICES ===
    pricelist_price_incl = fields.Monetary(
        string='Pricelist Price (Incl VAT)',
        compute='_compute_extra_amount',
        store=True,
        currency_field='currency_id'
    )
    
    paid_price_per_unit = fields.Monetary(
        string='Paid Price Per Unit',
        compute='_compute_extra_amount',
        store=True,
        currency_field='currency_id'
    )
    
    extra_amount_per_unit = fields.Monetary(
        string='Extra Per Unit',
        compute='_compute_extra_amount',
        store=True,
        currency_field='currency_id'
    )
    
    total_extra_amount = fields.Monetary(
        string='Total Extra',
        compute='_compute_extra_amount',
        store=True,
        currency_field='currency_id'
    )
    
    product_cost = fields.Monetary(
        string='Product Cost (AVCO)',
        compute='_compute_extra_amount',
        store=True,
        currency_field='currency_id'
    )
    
    currency_id = fields.Many2one(related='order_id.currency_id', store=True)
    
    # === ONCHANGE + DEPENDS: Real-time update on toggle ===
    @api.onchange('calculate_with_quantity')
    def _onchange_calculate_with_quantity(self):
        self._compute_extra_amount()
    
    @api.depends(
        'price_subtotal_incl', 'qty', 'product_id', 'product_id.standard_price',
        'order_id.pricelist_id', 'calculate_with_quantity'  # Added dependency
    )
    def _compute_extra_amount(self):
        for line in self:
            if not (line.qty and line.price_subtotal_incl and line.product_id):
                line._reset_extra_fields()
                continue
            
            # 1. Paid price per unit
            line.paid_price_per_unit = line.price_subtotal_incl / line.qty
            
            # 2. Pricelist price (VAT incl)
            pricelist = line.order_id.pricelist_id
            if pricelist and line.product_id:
                line.pricelist_price_incl = pricelist._get_product_price(
                    product=line.product_id,
                    quantity=1.0,
                    uom=line.product_id.uom_id,
                    date=line.order_id.date_order,
                )
            else:
                line.pricelist_price_incl = 0.0
            
            # 3. Extra per unit
            line.extra_amount_per_unit = line.paid_price_per_unit - line.pricelist_price_incl
            
            # 4. Effective quantity
            effective_qty = line.qty if line.calculate_with_quantity else 1.0
            
            # 5. Totals
            line.total_extra_amount = line.extra_amount_per_unit * effective_qty
            line.product_cost = line.product_id.standard_price * effective_qty
    
    def _reset_extra_fields(self):
        """Helper to reset all computed fields."""
        self.paid_price_per_unit = 0.0
        self.pricelist_price_incl = 0.0
        self.extra_amount_per_unit = 0.0
        self.total_extra_amount = 0.0
        self.product_cost = 0.0