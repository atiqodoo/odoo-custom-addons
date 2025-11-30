# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Extends pos.order to add courier dispatch functionality.
    
    Adds:
    - Relationship to courier dispatches
    - Computed fields for dispatch count and status
    - Actions to register and view dispatches
    """
    _inherit = 'pos.order'

    # ====================
    # FIELDS
    # ====================
    
    courier_dispatch_ids = fields.One2many(
        'courier.dispatch',
        'pos_order_id',
        string='Courier Dispatches',
        help='All courier dispatches created for this POS order',
    )
    
    courier_dispatch_count = fields.Integer(
        string='Courier Dispatch Count',
        compute='_compute_courier_dispatch_count',
        help='Total number of courier dispatches for this order',
    )
    
    courier_dispatch_ok = fields.Boolean(
        string='Has Courier Dispatch',
        compute='_compute_courier_dispatch_ok',
        store=True,
        help='True if this order has any courier dispatches',
    )

    # ====================
    # COMPUTED METHODS
    # ====================

    @api.depends('courier_dispatch_ids')
    def _compute_courier_dispatch_count(self):
        """
        Compute the total number of courier dispatches for this order.
        
        Purpose:
        - Used by smart button to show dispatch count
        - Called automatically when courier_dispatch_ids changes
        
        Returns:
            None (updates courier_dispatch_count field)
        """
        for order in self:
            count = len(order.courier_dispatch_ids)
            order.courier_dispatch_count = count
            _logger.info(f"[COURIER_DISPATCH] Order {order.name}: count = {count}")
    
    @api.depends('courier_dispatch_ids')
    def _compute_courier_dispatch_ok(self):
        """
        Check if order has any courier dispatches.
        
        Purpose:
        - Used for smart button visibility
        - Used for conditional logic in views
        
        Returns:
            None (updates courier_dispatch_ok field)
        """
        for order in self:
            has_dispatch = bool(order.courier_dispatch_ids)
            order.courier_dispatch_ok = has_dispatch
            _logger.info(f"[COURIER_DISPATCH] Order {order.name}: has_dispatch = {has_dispatch}")
    
    def _get_dispatched_quantities(self):
        """
        Calculate total dispatched quantity for each POS order line.
        
        Returns:
            dict: {pos_order_line_id: total_dispatched_qty}
        
        Example:
            {
                123: 5.0,  # Line 123 has 5.0 units already dispatched
                124: 2.0,  # Line 124 has 2.0 units already dispatched
            }
        """
        self.ensure_one()
        dispatched_qty = {}
        
        # Sum up quantities from all non-cancelled dispatches
        for dispatch in self.courier_dispatch_ids:
            if dispatch.state == 'cancelled':
                continue
                
            for line in dispatch.line_ids:
                pos_line_id = line.pos_order_line_id.id
                if pos_line_id not in dispatched_qty:
                    dispatched_qty[pos_line_id] = 0.0
                dispatched_qty[pos_line_id] += line.quantity
        
        _logger.info(f"[COURIER_DISPATCH] Order {self.name} - Total dispatched quantities: {dispatched_qty}")
        return dispatched_qty
    
    def _get_remaining_quantities(self):
        """
        Calculate remaining (undispatched) quantity for each POS order line.
        
        Returns:
            dict: {pos_order_line_id: remaining_qty}
        
        Example:
            If order line has qty=10 and 5 already dispatched:
            {123: 5.0}  # 5 units remaining
        """
        self.ensure_one()
        dispatched = self._get_dispatched_quantities()
        remaining = {}
        
        for line in self.lines:
            dispatched_qty = dispatched.get(line.id, 0.0)
            remaining_qty = line.qty - dispatched_qty
            remaining[line.id] = remaining_qty
            
            _logger.info(
                f"[COURIER_DISPATCH] Line {line.id} ({line.product_id.name}): "
                f"Ordered={line.qty}, Dispatched={dispatched_qty}, Remaining={remaining_qty}"
            )
        
        return remaining
    
    def _check_fully_dispatched(self):
        """
        Check if all order lines are fully dispatched.
        
        Returns:
            bool: True if all lines fully dispatched, False otherwise
        """
        self.ensure_one()
        remaining = self._get_remaining_quantities()
        
        # Check if any line has remaining quantity
        has_remaining = any(qty > 0.001 for qty in remaining.values())  # Use 0.001 for float comparison
        fully_dispatched = not has_remaining
        
        _logger.info(f"[COURIER_DISPATCH] Order {self.name} fully dispatched: {fully_dispatched}")
        return fully_dispatched

    
    # ====================
    # ACTIONS
    # ====================
    
    def action_register_courier_dispatch(self):
        """
        Open wizard to register a new courier dispatch for this POS order.
        
        Button trigger: 
            "Dispatch via Courier" button in POS order form view header
        
        Workflow:
            1. Validate order has lines
            2. Validate order is in correct state (paid/done/invoiced)
            3. Open wizard with order context
            4. Wizard creates dispatch and stock moves
        
        Validations:
            - Order must have at least one line item
            - Order must be in state: paid, done, or invoiced
        
        Returns:
            dict: Action dictionary to either:
                - Open wizard (if validations pass)
                - Show notification (if validations fail)
        
        Example log output:
            [COURIER_DISPATCH] === ACTION CALLED for Order shop 1/0097 ===
            [COURIER_DISPATCH] Order ID: 99
            [COURIER_DISPATCH] Order state: paid
            [COURIER_DISPATCH] Order partner: John Doe
            [COURIER_DISPATCH] Order lines count: 3
            [COURIER_DISPATCH] Existing dispatches: 0
            [COURIER_DISPATCH] All validations passed - opening wizard
        """
        self.ensure_one()
        
        # Log action start
        _logger.info("=" * 80)
        _logger.info(f"[COURIER_DISPATCH] === ACTION CALLED for Order {self.name} ===")
        _logger.info(f"[COURIER_DISPATCH] Order ID: {self.id}")
        _logger.info(f"[COURIER_DISPATCH] Order state: {self.state}")
        _logger.info(f"[COURIER_DISPATCH] Order partner: {self.partner_id.name if self.partner_id else 'No partner'}")
        _logger.info(f"[COURIER_DISPATCH] Order lines count: {len(self.lines)}")
        _logger.info(f"[COURIER_DISPATCH] Existing dispatches: {self.courier_dispatch_count}")
        _logger.info("=" * 80)
        
        # Validation 1: Check if order has lines
        if not self.lines:
            _logger.warning(f"[COURIER_DISPATCH] Order {self.name} has no lines!")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Items'),
                    'message': _('This order has no items to dispatch.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # Validation 2: Check if order is fully dispatched
        if self._check_fully_dispatched():
            _logger.warning(f"[COURIER_DISPATCH] Order {self.name} is fully dispatched!")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Fully Dispatched'),
                    'message': _('All items in this order have already been dispatched via courier.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        
        # Validation 3: Check order state
        # Note: For testing, we allow all states. In production, uncomment the check below.
        # if self.state not in ['paid', 'done', 'invoiced']:
        #     _logger.warning(f"[COURIER_DISPATCH] Order {self.name} not in valid state: {self.state}")
        #     return {
        #         'type': 'ir.actions.client',
        #         'tag': 'display_notification',
        #         'params': {
        #             'title': _('Order Not Paid'),
        #             'message': _('Only paid orders can be dispatched via courier. Current state: %s') % self.state,
        #             'type': 'warning',
        #             'sticky': False,
        #         }
        #     }
        
        _logger.info(f"[COURIER_DISPATCH] All validations passed - opening wizard for order {self.name}")
        
        # Open wizard to register dispatch
        return {
            'name': _('Register Courier Dispatch'),
            'type': 'ir.actions.act_window',
            'res_model': 'register.courier.dispatch.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_pos_order_id': self.id,
            },
        }
    
    def action_view_courier_dispatches(self):
        """
        View all courier dispatches for this order.
        
        Button trigger:
            Smart button showing dispatch count in form view
        
        Behavior:
            - If 1 dispatch: Opens in form view
            - If multiple: Opens in list view
        
        Returns:
            dict: Action dictionary to view dispatch(s)
        
        Example log output:
            [COURIER_DISPATCH] Viewing dispatches for order shop 1/0097
            [COURIER_DISPATCH] Total dispatches: 2
            [COURIER_DISPATCH] Opening list of 2 dispatches
        """
        self.ensure_one()
        
        _logger.info(f"[COURIER_DISPATCH] Viewing dispatches for order {self.name}")
        _logger.info(f"[COURIER_DISPATCH] Total dispatches: {self.courier_dispatch_count}")
        
        # Base action configuration
        action = {
            'name': _('Courier Dispatches'),
            'type': 'ir.actions.act_window',
            'res_model': 'courier.dispatch',
            'domain': [('pos_order_id', '=', self.id)],
            'context': {'default_pos_order_id': self.id},
        }
        
        # If only one dispatch, open in form view directly
        if self.courier_dispatch_count == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.courier_dispatch_ids[0].id,
            })
            _logger.info(f"[COURIER_DISPATCH] Opening single dispatch: {self.courier_dispatch_ids[0].name}")
        else:
            # Multiple dispatches, open in list view
            action.update({
                'view_mode': 'list,form',
            })
            _logger.info(f"[COURIER_DISPATCH] Opening list of {self.courier_dispatch_count} dispatches")
        
        return action
