# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class RegisterDeferredCollectionWizard(models.TransientModel):
    _name = 'register.deferred.collection.wizard'
    _description = 'Register Deferred Collection Wizard'

    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        readonly=True,
    )
    
    line_ids = fields.One2many(
        'register.deferred.collection.wizard.line',
        'wizard_id',
        string='Order Lines',
    )
    
    notes = fields.Text(string='Notes')
    
    holding_location_id = fields.Many2one(
        'stock.location',
        string='Holding Location',
        required=True,
        domain=[('usage', '=', 'internal')],
        default=lambda self: self._get_default_holding_location(),
    )
    
    @api.model
    def _get_default_holding_location(self):
        """Get default customer holding location"""
        _logger.info("[WIZARD] Getting default holding location...")
        location = self.env.ref(
            'paint_pos_pending_collection.stock_location_customer_holding',
            raise_if_not_found=False
        )
        if not location:
            location = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
        _logger.info(f"[WIZARD] Default location: {location.name if location else 'None'}")
        return location
    
    @api.model
    def default_get(self, fields_list):
        """Populate wizard lines from POS order"""
        _logger.info(f"[WIZARD] ================================================================================")
        _logger.info(f"[WIZARD] === default_get called with fields: {fields_list} ===")
        _logger.info(f"[WIZARD] ================================================================================")
        
        res = super().default_get(fields_list)
        
        _logger.info(f"[WIZARD] Context: {self._context}")
        _logger.info(f"[WIZARD] Initial res: {res}")
        
        if 'pos_order_id' in res and res['pos_order_id']:
            pos_order = self.env['pos.order'].browse(res['pos_order_id'])
            _logger.info(f"[WIZARD] POS Order: {pos_order.name} (ID: {pos_order.id})")
            _logger.info(f"[WIZARD] Order has {len(pos_order.lines)} lines")
            
            lines = []
            for idx, order_line in enumerate(pos_order.lines):
                line_data = {
                    'pos_order_line_id': order_line.id,
                    'product_id': order_line.product_id.id,
                    'ordered_qty': order_line.qty,
                    'taken_qty': order_line.qty,  # Default to all taken
                    'price_unit': order_line.price_unit,
                }
                _logger.info(f"[WIZARD] Line {idx + 1}: {order_line.product_id.name} - Qty: {order_line.qty}")
                _logger.info(f"[WIZARD] Line data: {line_data}")
                lines.append((0, 0, line_data))
            
            res['line_ids'] = lines
            _logger.info(f"[WIZARD] Created {len(lines)} wizard lines")
        else:
            _logger.warning("[WIZARD] No pos_order_id in context!")
        
        _logger.info(f"[WIZARD] Final res: {res}")
        _logger.info(f"[WIZARD] ================================================================================")
        return res
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to log what's being created"""
        _logger.info(f"[WIZARD] ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        _logger.info(f"[WIZARD] CREATE called with {len(vals_list)} record(s)")
        for idx, vals in enumerate(vals_list):
            _logger.info(f"[WIZARD] Record {idx + 1} vals: {vals}")
        _logger.info(f"[WIZARD] ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
        result = super().create(vals_list)
        _logger.info(f"[WIZARD] Created wizard ID: {result.id}")
        return result
    
    def write(self, vals):
        """Override write to log what's being saved"""
        _logger.info(f"[WIZARD] ╔═══════════════════════════════════════════════════════════════════════════╗")
        _logger.info(f"[WIZARD] ║  WRITE (SAVE) called on wizard ID: {self.id}")
        _logger.info(f"[WIZARD] ╚═══════════════════════════════════════════════════════════════════════════╝")
        _logger.info(f"[WIZARD] Values being written: {vals}")
        _logger.info(f"[WIZARD] Current state BEFORE write:")
        _logger.info(f"  - pos_order_id: {self.pos_order_id.id if self.pos_order_id else 'None'}")
        _logger.info(f"  - Number of lines: {len(self.line_ids)}")
        for idx, line in enumerate(self.line_ids):
            _logger.info(f"  - Line {idx + 1}: product={line.product_id.id if line.product_id else 'None'}, "
                        f"ordered={line.ordered_qty}, taken={line.taken_qty}")
        
        result = super().write(vals)
        
        _logger.info(f"[WIZARD] State AFTER write:")
        _logger.info(f"  - pos_order_id: {self.pos_order_id.id if self.pos_order_id else 'None'}")
        _logger.info(f"  - Number of lines: {len(self.line_ids)}")
        for idx, line in enumerate(self.line_ids):
            _logger.info(f"  - Line {idx + 1}: product={line.product_id.id if line.product_id else 'None'}, "
                        f"ordered={line.ordered_qty}, taken={line.taken_qty}")
        _logger.info(f"[WIZARD] ╚═══════════════════════════════════════════════════════════════════════════╝")
        
        return result
    
    def action_confirm(self):
        """Create pending collection record"""
        self.ensure_one()
        
        _logger.info(f"[WIZARD] === action_confirm called ===")
        _logger.info(f"[WIZARD] Wizard ID: {self.id}")
        _logger.info(f"[WIZARD] POS Order: {self.pos_order_id.name if self.pos_order_id else 'None'}")
        
        if not self.pos_order_id:
            _logger.error("[WIZARD] No POS order linked to wizard!")
            raise UserError(_('No POS order found.'))
        
        # CRITICAL FIX: Match wizard lines to POS lines by INDEX (not by ID)
        # The wizard line IDs get lost during save, but the order is preserved
        _logger.info(f"[WIZARD] Reading FRESH data from POS order...")
        _logger.info(f"[WIZARD] POS order has {len(self.pos_order_id.lines)} lines")
        _logger.info(f"[WIZARD] Wizard has {len(self.line_ids)} lines")
        
        # Sort both by sequence to ensure matching
        pos_lines = self.pos_order_id.lines.sorted(lambda l: l.id)
        wizard_lines = self.line_ids.sorted(lambda l: l.sequence)
        
        _logger.info(f"[WIZARD] Matching lines by position/index...")
        
        # Match by index
        deferred_items = []
        for idx, pos_line in enumerate(pos_lines):
            # Get corresponding wizard line by index
            if idx < len(wizard_lines):
                wizard_line = wizard_lines[idx]
                taken_qty = wizard_line.taken_qty
                _logger.info(f"[WIZARD] Matched by index {idx}:")
                _logger.info(f"  - POS line: {pos_line.product_id.name} (ID: {pos_line.id})")
                _logger.info(f"  - Wizard line taken_qty: {taken_qty}")
            else:
                # No wizard line for this POS line, assume all taken
                taken_qty = pos_line.qty
                _logger.info(f"[WIZARD] No wizard line for index {idx}, defaulting to all taken")
            
            left_qty = pos_line.qty - taken_qty
            
            _logger.info(f"[WIZARD] Processing POS line {pos_line.id}:")
            _logger.info(f"  - Product: {pos_line.product_id.name}")
            _logger.info(f"  - Ordered: {pos_line.qty}")
            _logger.info(f"  - Taken (user input): {taken_qty}")
            _logger.info(f"  - Left: {left_qty}")
            
            # Validate this specific line
            if taken_qty < 0:
                _logger.error(f"[WIZARD] Negative taken quantity for {pos_line.product_id.name}")
                raise ValidationError(_('Taken quantity cannot be negative for %s.') % pos_line.product_id.name)
            
            if taken_qty > pos_line.qty:
                _logger.error(f"[WIZARD] Taken quantity exceeds ordered for {pos_line.product_id.name}")
                raise ValidationError(
                    _('Taken quantity (%s) cannot exceed ordered quantity (%s) for %s.') % 
                    (taken_qty, pos_line.qty, pos_line.product_id.name)
                )
            
            # If items are left in store, add to deferred list
            if left_qty > 0:
                deferred_items.append({
                    'pos_order_line_id': pos_line.id,
                    'product_id': pos_line.product_id.id,
                    'product_name': pos_line.product_id.name,
                    'ordered_qty': pos_line.qty,
                    'taken_qty': taken_qty,
                    'left_qty': left_qty,
                })
                _logger.info(f"  ✓ Added to deferred items (left_qty={left_qty})")
            else:
                _logger.info(f"  ✗ Not deferred (left_qty={left_qty})")
        
        _logger.info(f"[WIZARD] Found {len(deferred_items)} items with quantity left in store")
        
        if not deferred_items:
            _logger.warning("[WIZARD] No items left in store - all taken!")
            raise UserError(_('No items are left in store. All quantities have been taken.'))
        
        # Create pending collection with FRESH data
        _logger.info("[WIZARD] Creating pending collection record...")
        collection_vals = {
            'pos_order_id': self.pos_order_id.id,
            'holding_location_id': self.holding_location_id.id,
            'notes': self.notes,
            'collection_line_ids': [],
        }
        
        # Add lines for deferred items
        for item in deferred_items:
            line_vals = {
                'pos_order_line_id': item['pos_order_line_id'],
                'product_id': item['product_id'],
                'product_uom_qty': item['ordered_qty'],
                'pending_qty': item['left_qty'],
                'description': item['product_name'],
            }
            _logger.info(f"[WIZARD] Adding collection line: {item['product_name']} - {item['left_qty']} units")
            collection_vals['collection_line_ids'].append((0, 0, line_vals))
        
        _logger.info(f"[WIZARD] Creating record with {len(deferred_items)} lines...")
        pending_collection = self.env['paint.pending.collection'].create(collection_vals)
        _logger.info(f"[WIZARD] Created pending collection: {pending_collection.name}")
        
        # Update pos order lines with taken quantities
        _logger.info("[WIZARD] Updating POS order lines with taken quantities...")
        for item in deferred_items:
            pos_line = self.env['pos.order.line'].browse(item['pos_order_line_id'])
            pos_line.taken_qty = item['taken_qty']
            _logger.info(f"[WIZARD] Updated line {pos_line.id}: taken_qty = {item['taken_qty']}")
        
        # Create stock moves
        _logger.info("[WIZARD] Creating stock moves...")
        try:
            pending_collection.action_create_stock_moves()
            _logger.info("[WIZARD] Stock moves created successfully")
        except Exception as e:
            _logger.error(f"[WIZARD] Error creating stock moves: {e}")
            raise
        
        # Post message on POS order
        total_deferred = sum(item['left_qty'] for item in deferred_items)
        message = _('Deferred collection registered: %s items left in store.') % total_deferred
        self.pos_order_id.message_post(body=message)
        _logger.info(f"[WIZARD] Posted message on POS order: {message}")
        
        _logger.info("[WIZARD] === action_confirm completed successfully ===")
        _logger.info(f"[WIZARD] Result: {len(deferred_items)} products, {total_deferred} total units deferred")
        
        # Open created record
        return {
            'name': _('Pending Collection'),
            'type': 'ir.actions.act_window',
            'res_model': 'paint.pending.collection',
            'res_id': pending_collection.id,
            'view_mode': 'form',
            'target': 'current',
        }


class RegisterDeferredCollectionWizardLine(models.TransientModel):
    _name = 'register.deferred.collection.wizard.line'
    _description = 'Register Deferred Collection Wizard Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'register.deferred.collection.wizard',
        string='Wizard',
        ondelete='cascade',
    )
    
    sequence = fields.Integer(string='Sequence', default=10)
    
    pos_order_line_id = fields.Many2one(
        'pos.order.line',
        string='POS Order Line',
        readonly=True,
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        readonly=True,
    )
    
    ordered_qty = fields.Float(
        string='Ordered Qty',
        readonly=True,
    )
    
    taken_qty = fields.Float(
        string='Taken Today',
        default=0.0,
    )
    
    left_qty = fields.Float(
        string='Left in Store',
        compute='_compute_left_qty',
        store=False,  # Don't store - always compute fresh
    )
    
    price_unit = fields.Float(
        string='Unit Price',
        readonly=True,
    )
    
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        related='product_id.uom_id',
        readonly=True,
    )
    
    @api.depends('ordered_qty', 'taken_qty')
    def _compute_left_qty(self):
        """Calculate quantity left in store"""
        _logger.info("[WIZARD_LINE] ┌─ Computing left_qty...")
        for line in self:
            # Handle None/False values
            ordered = line.ordered_qty or 0.0
            taken = line.taken_qty or 0.0
            line.left_qty = ordered - taken
            _logger.info(f"[WIZARD_LINE] │  {line.product_id.name if line.product_id else 'Product'}: "
                        f"ordered={ordered}, taken={taken}, left={line.left_qty}")
        _logger.info("[WIZARD_LINE] └─ Done computing")
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to log line creation"""
        _logger.info(f"[WIZARD_LINE] ╭─────────────────────────────────────────────────╮")
        _logger.info(f"[WIZARD_LINE] │  CREATE called with {len(vals_list)} line(s)")
        for idx, vals in enumerate(vals_list):
            _logger.info(f"[WIZARD_LINE] │  Line {idx + 1}: {vals}")
        _logger.info(f"[WIZARD_LINE] ╰─────────────────────────────────────────────────╯")
        result = super().create(vals_list)
        _logger.info(f"[WIZARD_LINE] Created {len(result)} line(s)")
        return result
    
    def write(self, vals):
        """Override write to log line updates"""
        _logger.info(f"[WIZARD_LINE] ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
        _logger.info(f"[WIZARD_LINE] ┃  WRITE called on {len(self)} line(s)")
        _logger.info(f"[WIZARD_LINE] ┃  Values: {vals}")
        for idx, line in enumerate(self):
            _logger.info(f"[WIZARD_LINE] ┃  Line {idx + 1} BEFORE: product={line.product_id.id if line.product_id else 'None'}, "
                        f"ordered={line.ordered_qty}, taken={line.taken_qty}, pos_line={line.pos_order_line_id.id if line.pos_order_line_id else 'None'}")
        _logger.info(f"[WIZARD_LINE] ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
        
        result = super().write(vals)
        
        _logger.info(f"[WIZARD_LINE] ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
        _logger.info(f"[WIZARD_LINE] ┃  AFTER WRITE:")
        for idx, line in enumerate(self):
            _logger.info(f"[WIZARD_LINE] ┃  Line {idx + 1} AFTER: product={line.product_id.id if line.product_id else 'None'}, "
                        f"ordered={line.ordered_qty}, taken={line.taken_qty}, pos_line={line.pos_order_line_id.id if line.pos_order_line_id else 'None'}")
        _logger.info(f"[WIZARD_LINE] ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
        
        return result
    
    def _check_quantities(self):
        """Validate quantities - called manually from action_confirm"""
        _logger.info("[WIZARD_LINE] Validating quantities...")
        for line in self:
            _logger.info(f"[WIZARD_LINE] Checking line: product={line.product_id.name if line.product_id else 'None'}, "
                        f"ordered={line.ordered_qty}, taken={line.taken_qty}")
            
            if line.taken_qty < 0:
                raise ValidationError(_('Taken quantity cannot be negative.'))
            
            if line.ordered_qty and line.taken_qty > line.ordered_qty:
                product_name = line.product_id.name if line.product_id else 'this product'
                raise ValidationError(
                    _('Taken quantity (%s) cannot exceed ordered quantity (%s) for %s.') % 
                    (line.taken_qty, line.ordered_qty, product_name)
                )
        _logger.info("[WIZARD_LINE] All quantities valid")
