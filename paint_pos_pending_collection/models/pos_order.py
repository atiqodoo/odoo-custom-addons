# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    pending_collection_ok = fields.Boolean(
        string='Has Pending Collection',
        compute='_compute_pending_collection_ok',
        store=True,
    )
    
    pending_collection_count = fields.Integer(
        string='Pending Collection Count',
        compute='_compute_pending_collection_count',
    )
    
    pending_collection_ids = fields.One2many(
        'paint.pending.collection',
        'pos_order_id',
        string='Pending Collections',
    )
    
    @api.depends('pending_collection_ids')
    def _compute_pending_collection_ok(self):
        """Check if order has any pending collections"""
        for order in self:
            order.pending_collection_ok = bool(order.pending_collection_ids)
            _logger.info(f"[PENDING_COLLECTION] Order {order.name}: pending_collection_ok = {order.pending_collection_ok}")
    
    @api.depends('pending_collection_ids')
    def _compute_pending_collection_count(self):
        """Count pending collections"""
        for order in self:
            order.pending_collection_count = len(order.pending_collection_ids)
            _logger.info(f"[PENDING_COLLECTION] Order {order.name}: count = {order.pending_collection_count}")
    
    def action_register_deferred_collection(self):
        """Open wizard to register deferred collection"""
        self.ensure_one()
        
        _logger.info(f"[PENDING_COLLECTION] === ACTION CALLED for Order {self.name} ===")
        _logger.info(f"[PENDING_COLLECTION] Order state: {self.state}")
        _logger.info(f"[PENDING_COLLECTION] Order lines count: {len(self.lines)}")
        
        if not self.lines:
            _logger.warning(f"[PENDING_COLLECTION] Order {self.name} has no lines!")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Items'),
                    'message': _('This order has no items to defer.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # CRITICAL CHECK 1: Block if active pending collections exist (draft or partial)
        active_collections = self.env['paint.pending.collection'].search([
            ('pos_order_id', '=', self.id),
            ('state', 'in', ['draft', 'partial'])
        ])
        
        _logger.info(f"[PENDING_COLLECTION] Checking for existing active pending collections...")
        _logger.info(f"[PENDING_COLLECTION] Found {len(active_collections)} active pending collection(s)")
        
        if active_collections:
            collection_names = ', '.join(active_collections.mapped('name'))
            _logger.warning(f"[PENDING_COLLECTION] Blocking wizard - active collections: {collection_names}")
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Pending Collections Already Exist'),
                    'message': _('This order already has active pending collection(s): %s. '
                               'Please use the "Pending Collections" smart button to view and manage them. '
                               'You cannot create new pending collections while existing ones are active.') % collection_names,
                    'type': 'warning',
                    'sticky': True,
                }
            }
        
        # CRITICAL CHECK 2: Block if ANY collection is fully done (no second deferrals allowed)
        done_collections = self.env['paint.pending.collection'].search([
            ('pos_order_id', '=', self.id),
            ('state', '=', 'done')
        ])
        
        _logger.info(f"[PENDING_COLLECTION] Checking for fully collected pending collections...")
        _logger.info(f"[PENDING_COLLECTION] Found {len(done_collections)} fully collected pending collection(s)")
        
        if done_collections:
            collection_names = ', '.join(done_collections.mapped('name'))
            _logger.warning(f"[PENDING_COLLECTION] Blocking wizard - collection already completed: {collection_names}")
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Order Already Has Completed Collection'),
                    'message': _('This order has already been fully collected. '
                               'Pending collection %s has been completed. '
                               'You cannot create a second deferred collection from the same POS order. '
                               'Each POS order can only have ONE deferred collection cycle.') % collection_names,
                    'type': 'warning',
                    'sticky': True,
                }
            }
        
        _logger.info(f"[PENDING_COLLECTION] All checks passed - opening wizard for order {self.name}")
        
        return {
            'name': _('Register Deferred Collection'),
            'type': 'ir.actions.act_window',
            'res_model': 'register.deferred.collection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_pos_order_id': self.id,
            },
        }
    
    def action_view_pending_collections(self):
        """View pending collections for this order"""
        self.ensure_one()
        
        _logger.info(f"[PENDING_COLLECTION] Viewing collections for order {self.name}")
        
        action = {
            'name': _('Pending Collections'),
            'type': 'ir.actions.act_window',
            'res_model': 'paint.pending.collection',
            'domain': [('pos_order_id', '=', self.id)],
            'context': {'default_pos_order_id': self.id},
        }
        
        if self.pending_collection_count == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.pending_collection_ids[0].id,
            })
        else:
            action.update({
                'view_mode': 'list,form',
            })
        
        return action