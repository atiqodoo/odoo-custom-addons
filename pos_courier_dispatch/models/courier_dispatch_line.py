# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CourierDispatchLine(models.Model):
    _name = 'courier.dispatch.line'
    _description = 'Courier Dispatch Line'
    _order = 'dispatch_id, sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    
    dispatch_id = fields.Many2one(
        'courier.dispatch',
        string='Dispatch',
        required=True,
        ondelete='cascade',
        index=True,
    )
    
    pos_order_line_id = fields.Many2one(
        'pos.order.line',
        string='POS Order Line',
        required=True,
        ondelete='restrict',
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        readonly=True,
    )
    
    product_name = fields.Char(
        string='Product Name',
        related='product_id.display_name',
        readonly=True,
    )
    
    quantity = fields.Float(
        string='Dispatch Quantity',
        required=True,
        default=0.0,
        digits='Product Unit of Measure',
    )
    
    ordered_qty = fields.Float(
        string='Ordered Quantity',
        readonly=True,
        digits='Product Unit of Measure',
        help='Original quantity from POS order',
    )
    
    price_unit = fields.Float(
        string='Unit Price',
        readonly=True,
        digits='Product Price',
    )
    
    subtotal = fields.Float(
        string='Subtotal',
        compute='_compute_subtotal',
        store=True,
        digits='Product Price',
    )
    
    weight = fields.Float(
        string='Weight (kg)',
        digits=(16, 3),
        help='Weight for courier calculation',
    )
    
    volume = fields.Float(
        string='Volume (m³)',
        digits=(16, 4),
        help='Volume for courier calculation',
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        related='dispatch_id.currency_id',
        readonly=True,
    )
    
    company_id = fields.Many2one(
        'res.company',
        related='dispatch_id.company_id',
        readonly=True,
        store=True,
    )

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        """Calculate line subtotal"""
        for line in self:
            line.subtotal = line.quantity * line.price_unit
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Auto-fill weight from product"""
        if self.product_id:
            self.weight = self.product_id.weight * self.quantity
    
    @api.onchange('quantity')
    def _onchange_quantity(self):
        """Update weight when quantity changes"""
        if self.product_id and self.quantity:
            self.weight = self.product_id.weight * self.quantity
    
    @api.constrains('quantity', 'ordered_qty')
    def _check_quantity(self):
        """Validate dispatch quantity doesn't exceed ordered quantity"""
        for line in self:
            if line.quantity > line.ordered_qty:
                raise ValidationError(_(
                    'Dispatch quantity (%.2f) cannot exceed ordered quantity (%.2f) for product %s'
                ) % (line.quantity, line.ordered_qty, line.product_id.display_name))
            
            if line.quantity < 0:
                raise ValidationError(_('Dispatch quantity cannot be negative'))
