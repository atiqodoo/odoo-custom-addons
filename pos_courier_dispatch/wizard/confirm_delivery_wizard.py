# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ConfirmDeliveryWizard(models.TransientModel):
    _name = 'confirm.delivery.wizard'
    _description = 'Confirm Delivery Wizard'

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

    @api.model
    def default_get(self, fields_list):
        """Load default values"""
        res = super(ConfirmDeliveryWizard, self).default_get(fields_list)
        
        dispatch_id = self.env.context.get('active_id')
        if dispatch_id:
            res['dispatch_id'] = dispatch_id
        
        return res
    
    def action_confirm(self):
        """Confirm delivery and mark dispatch as confirmed"""
        self.ensure_one()
        
        _logger.info(f"[CONFIRM_DELIVERY] Confirming delivery for {self.dispatch_id.name}")
        
        if self.dispatch_id.state not in ['delivered', 'in_transit']:
            raise UserError(_(
                'Cannot confirm delivery for dispatch in state: %s. '
                'Dispatch must be marked as delivered first.'
            ) % self.dispatch_id.state)
        
        # Update dispatch
        self.dispatch_id.write({
            'state': 'confirmed',
            'confirmation_date': self.confirmation_date,
        })
        
        # Link photos
        if self.photo_ids:
            self.photo_ids.write({
                'res_model': 'courier.dispatch',
                'res_id': self.dispatch_id.id,
            })
        
        # Post message with details
        message_body = _('Delivery Confirmed by Customer')
        
        if not self.condition_ok:
            message_body += _('<br/><strong>Warning:</strong> Goods reported as NOT in good condition')
        
        if self.notes:
            message_body += _('<br/><strong>Notes:</strong> %s') % self.notes
        
        self.dispatch_id.message_post(
            body=message_body,
            subject=_('Delivery Confirmed'),
        )
        
        _logger.info(f"[CONFIRM_DELIVERY] {self.dispatch_id.name} confirmed successfully")
        
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
