# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ConfirmDeliveryWizard(models.TransientModel):
    _name = 'confirm.delivery.wizard'
    _description = 'Confirm Delivery Wizard'

    # ====================
    # FIELDS
    # ====================

    dispatch_id = fields.Many2one(
        'courier.dispatch',
        string='Courier Dispatch',
        required=True,
        readonly=True,
    )
    
    confirmation_date = fields.Datetime(
        string='Confirmation Date',
        default=fields.Datetime.now,
        required=True,
    )
    
    condition_ok = fields.Boolean(
        string='Goods in Good Condition',
        default=True,
        help='Check if goods were received in good condition',
    )
    
    customer_signature = fields.Binary(
        string='Customer Signature',
        help='Customer signature image (optional)',
    )
    
    photo_ids = fields.Many2many(
        'ir.attachment',
        'confirm_delivery_photo_rel',
        'wizard_id',
        'attachment_id',
        string='Proof of Delivery Photos',
        help='Photos showing delivery confirmation',
    )
    
    notes = fields.Text(
        string='Notes/Comments',
        help='Any complaints, issues, or additional comments',
    )

    # ====================
    # DEFAULT_GET
    # ====================

    @api.model
    def default_get(self, fields_list):
        """Load default values"""
        _logger.info("=" * 80)
        _logger.info("[CONFIRM_DELIVERY_WIZARD] === default_get called ===")
        
        res = super(ConfirmDeliveryWizard, self).default_get(fields_list)
        
        dispatch_id = self.env.context.get('active_id')
        if dispatch_id:
            dispatch = self.env['courier.dispatch'].browse(dispatch_id)
            res['dispatch_id'] = dispatch_id
            
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Dispatch: {dispatch.name} (ID: {dispatch_id})")
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Current state: {dispatch.state}")
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Customer: {dispatch.customer_id.name if dispatch.customer_id else 'None'}")
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Courier: {dispatch.courier_name}")
        else:
            _logger.warning("[CONFIRM_DELIVERY_WIZARD] No active_id in context!")
        
        _logger.info("=" * 80)
        
        return res
    
    # ====================
    # ACTIONS
    # ====================
    
    def action_confirm(self):
        """Confirm delivery and mark dispatch as confirmed"""
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("[CONFIRM_DELIVERY_WIZARD] === action_confirm called ===")
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Dispatch: {self.dispatch_id.name}")
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Current state: {self.dispatch_id.state}")
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Confirmation date: {self.confirmation_date}")
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Goods in good condition: {self.condition_ok}")
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Has signature: {bool(self.customer_signature)}")
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Photo count: {len(self.photo_ids)}")
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Has notes: {bool(self.notes)}")
        _logger.info("=" * 80)
        
        # Validation: Check dispatch state
        if self.dispatch_id.state not in ['delivered', 'in_transit']:
            _logger.error(
                f"[CONFIRM_DELIVERY_WIZARD] Cannot confirm dispatch in state: {self.dispatch_id.state}"
            )
            raise UserError(_(
                'Cannot confirm delivery for dispatch in state: %s. '
                'Dispatch must be marked as delivered first.'
            ) % self.dispatch_id.state)
        
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] State validation passed")
        
        # Update dispatch state
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Updating dispatch {self.dispatch_id.name} to 'confirmed' state")
        self.dispatch_id.write({
            'state': 'confirmed',
            'confirmation_date': self.confirmation_date,
        })
        
        # Link photos to dispatch
        if self.photo_ids:
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Linking {len(self.photo_ids)} photos to dispatch")
            self.photo_ids.write({
                'res_model': 'courier.dispatch',
                'res_id': self.dispatch_id.id,
            })
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Photos linked successfully")
        else:
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] No photos to link")
        
        # Build message body
        message_body = _('Delivery Confirmed by Customer')
        message_details = []
        
        if not self.condition_ok:
            message_details.append(_('<strong>⚠️ Warning:</strong> Goods reported as NOT in good condition'))
            _logger.warning(
                f"[CONFIRM_DELIVERY_WIZARD] {self.dispatch_id.name} - "
                f"Customer reported goods NOT in good condition!"
            )
        else:
            message_details.append(_('✓ Goods received in good condition'))
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Goods confirmed in good condition")
        
        if self.customer_signature:
            message_details.append(_('✓ Customer signature received'))
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Customer signature captured")
        
        if self.photo_ids:
            message_details.append(_('✓ %d proof of delivery photo(s) attached') % len(self.photo_ids))
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] {len(self.photo_ids)} POD photos attached")
        
        if self.notes:
            message_details.append(_('<strong>Notes:</strong> %s') % self.notes)
            _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Notes: {self.notes[:100]}...")
        
        # Combine message
        if message_details:
            message_body += '<br/>' + '<br/>'.join(message_details)
        
        # Post message to chatter
        _logger.info(f"[CONFIRM_DELIVERY_WIZARD] Posting confirmation message to chatter")
        self.dispatch_id.message_post(
            body=message_body,
            subject=_('Delivery Confirmed'),
        )
        
        _logger.info(
            f"[CONFIRM_DELIVERY_WIZARD] === Confirmation completed successfully for {self.dispatch_id.name} ==="
        )
        _logger.info("=" * 80)
        
        # Return success notification
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Delivery Confirmed'),
                'message': _('Delivery has been confirmed for dispatch %s') % self.dispatch_id.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }