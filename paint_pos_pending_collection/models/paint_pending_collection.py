# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PaintPendingCollection(models.Model):
    _name = 'paint.pending.collection'
    _description = 'POS Pending Collection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_left desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        copy=False,
        default='/',
        tracking=True,
    )
    
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        readonly=True,
        ondelete='cascade',
        tracking=True,
    )
    
    pos_reference = fields.Char(
        string='POS Receipt',
        related='pos_order_id.pos_reference',
        store=True,
        readonly=True,
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='pos_order_id.partner_id',
        store=True,
        readonly=True,
        tracking=True,
    )
    
    partner_phone = fields.Char(
        string='Phone',
        related='partner_id.phone',
        store=True,
        readonly=True,
    )
    
    partner_mobile = fields.Char(
        string='Mobile',
        related='partner_id.mobile',
        store=True,
        readonly=True,
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('partial', 'Partially Collected'),
        ('done', 'Fully Collected'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    collection_line_ids = fields.One2many(
        'paint.pending.collection.line',
        'pending_collection_id',
        string='Pending Items',
        copy=False,
    )
    
    holding_location_id = fields.Many2one(
        'stock.location',
        string='Holding Location',
        required=True,
        domain=[('usage', '=', 'internal')],
        default=lambda self: self._get_default_holding_location(),
    )
    
    date_left = fields.Datetime(
        string='Date Left',
        default=fields.Datetime.now,
        required=True,
        tracking=True,
    )
    
    date_collected = fields.Datetime(
        string='Date Fully Collected',
        readonly=True,
        tracking=True,
    )
    
    days_pending = fields.Integer(
        string='Days Pending',
        compute='_compute_days_pending',
        store=True,
    )
    
    notes = fields.Text(string='Notes')
    
    total_pending_qty = fields.Float(
        string='Total Pending Qty',
        compute='_compute_totals',
        store=True,
    )
    
    total_collected_qty = fields.Float(
        string='Total Collected Qty',
        compute='_compute_totals',
        store=True,
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    
    barcode = fields.Char(
        string='Barcode',
        compute='_compute_barcode',
        store=True,
    )
    
    @api.model
    def _get_default_holding_location(self):
        """Get default customer holding location"""
        location = self.env.ref(
            'paint_pos_pending_collection.stock_location_customer_holding',
            raise_if_not_found=False
        )
        if not location:
            # Fallback to first internal location
            location = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
        return location
    
    @api.depends('name')
    def _compute_barcode(self):
        """Generate barcode from name"""
        for record in self:
            record.barcode = record.name.replace('/', '')
    
    @api.depends('date_left', 'state')
    def _compute_days_pending(self):
        """Calculate days pending"""
        for record in self:
            if record.state in ('done', 'cancelled'):
                record.days_pending = 0
            elif record.date_left:
                delta = fields.Datetime.now() - record.date_left
                record.days_pending = delta.days
            else:
                record.days_pending = 0
    
    @api.depends('collection_line_ids.pending_qty', 'collection_line_ids.collected_qty')
    def _compute_totals(self):
        """Calculate total quantities"""
        for record in self:
            record.total_pending_qty = sum(record.collection_line_ids.mapped('pending_qty'))
            record.total_collected_qty = sum(record.collection_line_ids.mapped('collected_qty'))
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate sequence"""
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'paint.pending.collection'
                ) or '/'
        return super().create(vals_list)
    
    def action_create_stock_moves(self):
        """Create stock moves to transfer items to holding location"""
        self.ensure_one()
        
        if not self.collection_line_ids:
            raise UserError(_('No pending items to move to holding location.'))
        
        # Get source location from POS config
        source_location = self.pos_order_id.config_id.picking_type_id.default_location_src_id
        if not source_location:
            raise UserError(_('Source location not found in POS configuration.'))
        
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id.company_id', '=', self.company_id.id),
        ], limit=1)
        
        if not picking_type:
            raise UserError(_('Internal picking type not found.'))
        
        # Create picking
        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': source_location.id,
            'location_dest_id': self.holding_location_id.id,
            'origin': f'{self.pos_reference} - {self.name}',
            'move_ids_without_package': [],
        }
        
        # Create moves for each line
        for line in self.collection_line_ids:
            move_vals = {
                'name': line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.pending_qty,
                'product_uom': line.product_id.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': self.holding_location_id.id,
            }
            picking_vals['move_ids_without_package'].append((0, 0, move_vals))
        
        # Create and validate picking
        picking = self.env['stock.picking'].create(picking_vals)
        picking.action_confirm()
        picking.action_assign()
        
        # Auto-validate if all moves are available
        if all(move.state == 'assigned' for move in picking.move_ids):
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
            picking.button_validate()
        
        # Link picking to collection lines
        for line in self.collection_line_ids:
            line.stock_move_id = picking.move_ids.filtered(
                lambda m: m.product_id == line.product_id
            )[:1]
        
        # Update state
        if self.state == 'draft':
            self.state = 'partial' if self.total_collected_qty > 0 else 'draft'
        
        return picking
    
    def action_collect_items(self):
        """Open wizard to collect items"""
        self.ensure_one()
        
        return {
            'name': _('Collect Pending Items'),
            'type': 'ir.actions.act_window',
            'res_model': 'collect.pending.items.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_pending_collection_id': self.id,
            },
        }
    
    def action_cancel(self):
        """Cancel pending collection and return items to stock"""
        self.ensure_one()
        
        if self.state == 'done':
            raise UserError(_('Cannot cancel a fully collected order.'))
        
        # Reverse stock moves
        for line in self.collection_line_ids:
            if line.stock_move_id and line.pending_qty > 0:
                # Create return picking
                source_location = line.stock_move_id.location_dest_id
                dest_location = line.stock_move_id.location_id
                
                picking_type = self.env['stock.picking.type'].search([
                    ('code', '=', 'internal'),
                    ('warehouse_id.company_id', '=', self.company_id.id),
                ], limit=1)
                
                picking_vals = {
                    'picking_type_id': picking_type.id,
                    'location_id': source_location.id,
                    'location_dest_id': dest_location.id,
                    'origin': f'Return: {self.name}',
                }
                
                picking = self.env['stock.picking'].create(picking_vals)
                
                move_vals = {
                    'name': f'Return: {line.product_id.name}',
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.pending_qty,
                    'product_uom': line.product_id.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': source_location.id,
                    'location_dest_id': dest_location.id,
                }
                
                move = self.env['stock.move'].create(move_vals)
                picking.action_confirm()
                picking.action_assign()
                move.quantity = move.product_uom_qty
                picking.button_validate()
        
        self.state = 'cancelled'
        self.message_post(body=_('Pending collection cancelled. Items returned to stock.'))
    
    def action_print_label(self):
        """Print pending collection label"""
        self.ensure_one()
        return self.env.ref(
            'paint_pos_pending_collection.action_report_pending_collection_label'
        ).report_action(self)
    
    def name_get(self):
        """Custom name display"""
        result = []
        for record in self:
            name = f'{record.name}'
            if record.partner_id:
                name += f' - {record.partner_id.name}'
            result.append((record.id, name))
        return result
