# -*- coding: utf-8 -*-
"""
POS Order Line Extension
Tracks both:
1. TIER 1: Extra amounts charged above pricelist
2. TIER 2: Base profit on pricelist itself (excl VAT)
Supports toggle: use quantity or count only 1 unit (applies to both tiers).
"""
from odoo import models, fields, api


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'
    
    # === TOGGLE: Applies to BOTH extra and base profit ===
    calculate_with_quantity = fields.Boolean(
        string='Calculate with Quantity',
        default=False,
        help="If off: calculate for 1 unit only. If on: multiply by quantity (applies to both extra and base profit)"
    )
    
    # === TIER 1: EXTRA AMOUNT FIELDS ===
    pricelist_price_incl = fields.Monetary(
        string='Pricelist Price (Incl VAT)',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id'
    )
    
    paid_price_per_unit = fields.Monetary(
        string='Paid Price Per Unit',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id'
    )
    
    extra_amount_per_unit = fields.Monetary(
        string='Extra Per Unit',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id'
    )
    
    total_extra_amount = fields.Monetary(
        string='Total Extra',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id'
    )
    
    product_cost = fields.Monetary(
        string='Product Cost (AVCO)',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id'
    )
    
    # === TIER 2: BASE PROFIT FIELDS ===
    pricelist_price_excl_vat = fields.Monetary(
        string='Pricelist Price (Excl VAT)',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help="Pricelist price excluding VAT for base profit calculation"
    )
    
    base_profit_per_unit = fields.Monetary(
        string='Base Profit Per Unit',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help="Base profit per unit: (Pricelist excl VAT - Purchase price)"
    )
    
    total_base_profit = fields.Monetary(
        string='Total Base Profit',
        compute='_compute_extra_and_profit',
        store=True,
        currency_field='currency_id',
        help="Total base profit (respects quantity toggle)"
    )
    
    currency_id = fields.Many2one(related='order_id.currency_id', store=True)
    
    # === ONCHANGE: Real-time update on toggle ===
    @api.onchange('calculate_with_quantity')
    def _onchange_calculate_with_quantity(self):
        self._compute_extra_and_profit()
    
    # === UNIFIED COMPUTATION: Both Extra AND Base Profit ===
    @api.depends(
        'price_subtotal_incl', 'qty', 'product_id', 'product_id.standard_price',
        'product_id.taxes_id', 'order_id.pricelist_id', 'calculate_with_quantity'
    )
    def _compute_extra_and_profit(self):
        for line in self:
            if not (line.qty and line.price_subtotal_incl and line.product_id):
                line._reset_all_fields()
                continue
            
            # === TIER 1: EXTRA AMOUNT CALCULATION ===
            
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
            
            # 4. Effective quantity (applies to both extra AND base profit)
            effective_qty = line.qty if line.calculate_with_quantity else 1.0
            
            # 5. Extra amount totals
            line.total_extra_amount = line.extra_amount_per_unit * effective_qty
            line.product_cost = line.product_id.standard_price * effective_qty
            
            # === TIER 2: BASE PROFIT CALCULATION ===
            
            # 6. Pricelist price excl VAT
            # Get VAT rate from product taxes
            taxes = line.product_id.taxes_id.filtered(lambda t: t.amount_type == 'percent')
            vat_rate = sum(taxes.mapped('amount')) / 100.0 if taxes else 0.0
            line.pricelist_price_excl_vat = line.pricelist_price_incl / (1.0 + vat_rate) if vat_rate else line.pricelist_price_incl
            
            # 7. Base profit per unit (Pricelist excl VAT - Purchase price)
            line.base_profit_per_unit = line.pricelist_price_excl_vat - line.product_id.standard_price
            
            # 8. Total base profit (uses same quantity toggle)
            line.total_base_profit = line.base_profit_per_unit * effective_qty
    
    def _reset_all_fields(self):
        """Helper to reset all computed fields (extra AND base profit)."""
        # Extra amount fields
        self.paid_price_per_unit = 0.0
        self.pricelist_price_incl = 0.0
        self.extra_amount_per_unit = 0.0
        self.total_extra_amount = 0.0
        self.product_cost = 0.0
        # Base profit fields
        self.pricelist_price_excl_vat = 0.0
        self.base_profit_per_unit = 0.0
        self.total_base_profit = 0.0
