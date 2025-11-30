# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class CollectPendingItemsWizard(models.TransientModel):
    _name = 'collect.pending.items.wizard'
    _description = 'Collect Pending Items Wizard'

    pending_collection_id = fields.Many2one(
        'paint.pending.collection',
        string='Pending Collection',
        required=True,
        readonly=True,
    )
    
    line_ids = fields.One2many(
        'collect.pending.items.wizard.line',
        'wizard_id',
        string='Items to Collect',
    )
    
    collection_date = fields.Datetime(
        string='Collection Date',
        default=fields.Datetime.now,
        required=True,
    )
    
    notes = fields.Text(string='Collection Notes')
    
    @api.model
    def default_get(self, fields_list):
        """Populate wizard lines from pending collection"""
        _logger.info(f"[COLLECT_WIZARD] ════════════════════════════════════════════════")
        _logger.info(f"[COLLECT_WIZARD] === default_get called ===")
        
        res = super().default_get(fields_list)
        
        _logger.info(f"[COLLECT_WIZARD] Context: {self._context}")
        _logger.info(f"[COLLECT_WIZARD] Initial res: {res}")
        
        if 'pending_collection_id' in res and res['pending_collection_id']:
            pending = self.env['paint.pending.collection'].browse(
                res['pending_collection_id']
            )
            
            _logger.info(f"[COLLECT_WIZARD] Pending Collection: {pending.name} (ID: {pending.id})")
            _logger.info(f"[COLLECT_WIZARD] Collection has {len(pending.collection_line_ids)} lines")
            
            lines = []
            for idx, collection_line in enumerate(pending.collection_line_ids):
                if collection_line.remaining_qty > 0:
                    line_data = {
                        'collection_line_id': collection_line.id,
                        'product_id': collection_line.product_id.id,
                        'pending_qty': collection_line.remaining_qty,
                        'collect_qty': collection_line.remaining_qty,  # Default to all
                    }
                    _logger.info(f"[COLLECT_WIZARD] Line {idx + 1}: {collection_line.product_id.name} - Remaining: {collection_line.remaining_qty}")
                    _logger.info(f"[COLLECT_WIZARD] Line data: {line_data}")
                    lines.append((0, 0, line_data))
            
            res['line_ids'] = lines
            _logger.info(f"[COLLECT_WIZARD] Created {len(lines)} wizard lines")
        else:
            _logger.warning("[COLLECT_WIZARD] No pending_collection_id in context!")
        
        _logger.info(f"[COLLECT_WIZARD] Final res: {res}")
        _logger.info(f"[COLLECT_WIZARD] ════════════════════════════════════════════════")
        return res
    
    def action_confirm(self):
        """Process collection"""
        self.ensure_one()
        
        _logger.info(f"[COLLECT_WIZARD] ═══════════════════════════════════════════════")
        _logger.info(f"[COLLECT_WIZARD] === action_confirm called ===")
        _logger.info(f"[COLLECT_WIZARD] Wizard ID: {self.id}")
        _logger.info(f"[COLLECT_WIZARD] Pending Collection: {self.pending_collection_id.name}")
        
        if not self.pending_collection_id:
            _logger.error("[COLLECT_WIZARD] No pending collection linked!")
            raise UserError(_('No pending collection found.'))
        
        # CRITICAL FIX: Match by index, don't trust wizard line IDs
        _logger.info(f"[COLLECT_WIZARD] Reading FRESH data from pending collection...")
        pending = self.pending_collection_id
        collection_lines = pending.collection_line_ids.filtered(lambda l: l.remaining_qty > 0).sorted(lambda l: l.id)
        wizard_lines = self.line_ids.sorted(lambda l: l.sequence)
        
        _logger.info(f"[COLLECT_WIZARD] Pending collection has {len(collection_lines)} lines with remaining qty")
        _logger.info(f"[COLLECT_WIZARD] Wizard has {len(wizard_lines)} lines")
        _logger.info(f"[COLLECT_WIZARD] Matching lines by position/index...")
        
        # Match by index and build collection data
        items_to_collect = []
        for idx, collection_line in enumerate(collection_lines):
            # Get corresponding wizard line by index
            if idx < len(wizard_lines):
                wizard_line = wizard_lines[idx]
                collect_qty = wizard_line.collect_qty
                _logger.info(f"[COLLECT_WIZARD] Matched by index {idx}:")
                _logger.info(f"  - Collection line: {collection_line.product_id.name} (ID: {collection_line.id})")
                _logger.info(f"  - Wizard line collect_qty: {collect_qty}")
            else:
                # No wizard line, skip this item
                collect_qty = 0.0
                _logger.info(f"[COLLECT_WIZARD] No wizard line for index {idx}, skipping")
            
            _logger.info(f"[COLLECT_WIZARD] Processing collection line {collection_line.id}:")
            _logger.info(f"  - Product: {collection_line.product_id.name}")
            _logger.info(f"  - Remaining: {collection_line.remaining_qty}")
            _logger.info(f"  - Collecting (user input): {collect_qty}")
            
            # Validate
            if collect_qty < 0:
                _logger.error(f"[COLLECT_WIZARD] Negative collection quantity!")
                raise ValidationError(_('Collection quantity cannot be negative for %s.') % collection_line.product_id.name)
            
            if collect_qty > collection_line.remaining_qty:
                _logger.error(f"[COLLECT_WIZARD] Collection exceeds remaining!")
                raise ValidationError(
                    _('Collection quantity (%s) cannot exceed remaining quantity (%s) for %s.') % 
                    (collect_qty, collection_line.remaining_qty, collection_line.product_id.name)
                )
            
            # Add to collection list if qty > 0
            if collect_qty > 0:
                items_to_collect.append({
                    'collection_line_id': collection_line.id,
                    'product_id': collection_line.product_id.id,
                    'product_name': collection_line.product_id.name,
                    'collect_qty': collect_qty,
                })
                _logger.info(f"  ✓ Added to collection list")
            else:
                _logger.info(f"  ✗ Not collecting (qty=0)")
        
        _logger.info(f"[COLLECT_WIZARD] Found {len(items_to_collect)} items to collect")
        
        if not items_to_collect:
            _logger.warning("[COLLECT_WIZARD] No items selected for collection!")
            raise UserError(_('No items selected for collection.'))
        
        # Update collection lines and create stock moves
        _logger.info("[COLLECT_WIZARD] Updating collection lines and creating stock moves...")
        for item in items_to_collect:
            collection_line = self.env['paint.pending.collection.line'].browse(item['collection_line_id'])
            
            _logger.info(f"[COLLECT_WIZARD] Updating line {collection_line.id}:")
            _logger.info(f"  - Product: {item['product_name']}")
            _logger.info(f"  - Collected qty before: {collection_line.collected_qty}")
            _logger.info(f"  - Adding: {item['collect_qty']}")
            
            collection_line.collected_qty += item['collect_qty']
            
            _logger.info(f"  - Collected qty after: {collection_line.collected_qty}")
            _logger.info(f"  - Remaining: {collection_line.remaining_qty}")
            
            # Create stock move
            _logger.info(f"[COLLECT_WIZARD] Creating return stock move...")
            try:
                self._create_return_stock_move(collection_line, item['collect_qty'])
                _logger.info(f"  ✓ Stock move created")
            except Exception as e:
                _logger.error(f"  ✗ Stock move failed: {e}")
                raise
        
        # Update pending collection state
        _logger.info("[COLLECT_WIZARD] Updating pending collection state...")
        all_collected = all(
            line.remaining_qty == 0 
            for line in pending.collection_line_ids
        )
        
        total_collected = sum(item['collect_qty'] for item in items_to_collect)
        
        if all_collected:
            pending.state = 'done'
            pending.date_collected = self.collection_date
            message = _('All items collected.')
            _logger.info(f"[COLLECT_WIZARD] All items collected - state changed to 'done'")
        else:
            pending.state = 'partial'
            message = _('Partial collection: %s items collected.') % total_collected
            _logger.info(f"[COLLECT_WIZARD] Partial collection - {total_collected} items")
        
        # Add notes if provided
        if self.notes:
            message += f'\n{self.notes}'
            _logger.info(f"[COLLECT_WIZARD] Notes added: {self.notes}")
        
        pending.message_post(body=message)
        _logger.info(f"[COLLECT_WIZARD] Posted message on pending collection")
        
        _logger.info(f"[COLLECT_WIZARD] === action_confirm completed successfully ===")
        _logger.info(f"[COLLECT_WIZARD] Result: {len(items_to_collect)} products, {total_collected} total units collected")
        _logger.info(f"[COLLECT_WIZARD] ═══════════════════════════════════════════════")
        
        # Return to pending collection form
        return {
            'name': _('Pending Collection'),
            'type': 'ir.actions.act_window',
            'res_model': 'paint.pending.collection',
            'res_id': pending.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def _create_return_stock_move(self, collection_line, qty):
        """Create stock move to return items from holding location"""
        pending = self.pending_collection_id
        
        # Get destination location (original POS location)
        dest_location = pending.pos_order_id.config_id.picking_type_id.default_location_src_id
        if not dest_location:
            raise UserError(_('Cannot determine destination location.'))
        
        # Get picking type
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id.company_id', '=', pending.company_id.id),
        ], limit=1)
        
        if not picking_type:
            raise UserError(_('Internal picking type not found.'))
        
        # Create picking
        picking_vals = {
            'picking_type_id': picking_type.id,
            'location_id': pending.holding_location_id.id,
            'location_dest_id': dest_location.id,
            'origin': f'Collection: {pending.name}',
        }
        
        picking = self.env['stock.picking'].create(picking_vals)
        
        # Create move
        move_vals = {
            'name': f'Collect: {collection_line.product_id.name}',
            'product_id': collection_line.product_id.id,
            'product_uom_qty': qty,
            'product_uom': collection_line.product_id.uom_id.id,
            'picking_id': picking.id,
            'location_id': pending.holding_location_id.id,
            'location_dest_id': dest_location.id,
        }
        
        move = self.env['stock.move'].create(move_vals)
        
        # Validate picking
        picking.action_confirm()
        picking.action_assign()
        move.quantity = move.product_uom_qty
        picking.button_validate()
        
        return picking


class CollectPendingItemsWizardLine(models.TransientModel):
    _name = 'collect.pending.items.wizard.line'
    _description = 'Collect Pending Items Wizard Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one(
        'collect.pending.items.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    
    sequence = fields.Integer(string='Sequence', default=10)
    
    collection_line_id = fields.Many2one(
        'paint.pending.collection.line',
        string='Collection Line',
        readonly=True,
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        readonly=True,
    )
    
    pending_qty = fields.Float(
        string='Pending Qty',
        readonly=True,
    )
    
    collect_qty = fields.Float(
        string='Collect Now',
        default=0.0,
    )
    
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        related='product_id.uom_id',
        readonly=True,
    )
    
    tint_color_code = fields.Char(
        string='Color Code',
        related='collection_line_id.tint_color_code',
        readonly=True,
    )
    
    def _check_quantities(self):
        """Validate quantities - called manually from action_confirm"""
        for line in self:
            if line.collect_qty < 0:
                raise ValidationError(_('Collection quantity cannot be negative.'))
            if line.pending_qty and line.collect_qty > line.pending_qty:
                product_name = line.product_id.name if line.product_id else 'this product'
                raise ValidationError(
                    _('Collection quantity (%s) cannot exceed pending quantity (%s) for %s.') % 
                    (line.collect_qty, line.pending_qty, product_name)
                )
