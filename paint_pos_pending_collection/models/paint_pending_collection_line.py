# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PaintPendingCollectionLine(models.Model):
    _name = 'paint.pending.collection.line'
    _description = 'Pending Collection Line'
    _order = 'pending_collection_id, sequence, id'

    pending_collection_id = fields.Many2one(
        'paint.pending.collection',
        string='Pending Collection',
        required=True,
        ondelete='cascade',
        index=True,
    )
    
    sequence = fields.Integer(string='Sequence', default=10)
    
    pos_order_line_id = fields.Many2one(
        'pos.order.line',
        string='POS Order Line',
        ondelete='restrict',
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        domain=[('sale_ok', '=', True)],
    )
    
    product_uom_qty = fields.Float(
        string='Original Qty',
        required=True,
        default=1.0,
    )
    
    pending_qty = fields.Float(
        string='Pending Qty',
        required=True,
        default=1.0,
    )
    
    collected_qty = fields.Float(
        string='Collected Qty',
        default=0.0,
        readonly=True,
    )
    
    remaining_qty = fields.Float(
        string='Remaining Qty',
        compute='_compute_remaining_qty',
        store=True,
    )
    
    tint_color_code = fields.Char(
        string='Tint Color Code',
        help='Color code for tinted products',
    )
    
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lot/Serial Number',
        domain="[('product_id', '=', product_id)]",
    )
    
    description = fields.Text(string='Description')
    
    stock_move_id = fields.Many2one(
        'stock.move',
        string='Stock Move',
        readonly=True,
        help='Stock move that transferred item to holding location',
    )
    
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='product_id.uom_id',
        readonly=True,
    )
    
    state = fields.Selection(
        related='pending_collection_id.state',
        string='Status',
        store=True,
        readonly=True,
    )
    
    @api.depends('pending_qty', 'collected_qty')
    def _compute_remaining_qty(self):
        """Calculate remaining quantity"""
        for line in self:
            line.remaining_qty = line.pending_qty - line.collected_qty
    
    @api.constrains('pending_qty', 'collected_qty')
    def _check_quantities(self):
        """Validate quantities"""
        for line in self:
            if line.pending_qty < 0:
                raise ValidationError(_('Pending quantity cannot be negative.'))
            if line.collected_qty < 0:
                raise ValidationError(_('Collected quantity cannot be negative.'))
            if line.collected_qty > line.pending_qty:
                raise ValidationError(
                    _('Collected quantity cannot exceed pending quantity.')
                )
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Update description from product"""
        if self.product_id:
            self.description = self.product_id.display_name
    
    def name_get(self):
        """Custom name display"""
        result = []
        for line in self:
            name = f'{line.product_id.name}'
            if line.tint_color_code:
                name += f' - {line.tint_color_code}'
            if line.remaining_qty:
                name += f' ({line.remaining_qty} {line.product_uom_id.name})'
            result.append((line.id, name))
        return result
