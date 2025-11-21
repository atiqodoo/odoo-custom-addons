# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class MrpProductionDuplicateWizard(models.TransientModel):
    _name = 'mrp.production.duplicate.wizard'
    _description = 'Duplicate Tinting MO Wizard'
    
    source_mo_id = fields.Many2one(
        'mrp.production',
        string='Source MO',
        required=True,
        readonly=True
    )
    
    product_name = fields.Char(
        string='Product',
        readonly=True
    )
    
    quantity = fields.Integer(
        string='Number of Duplicates',
        required=True,
        default=1,
        help='How many identical MOs to create'
    )
    
    auto_confirm = fields.Boolean(
        string='Auto-Confirm MOs',
        default=True,
        help='Automatically confirm the duplicated MOs'
    )
    
    preview_message = fields.Html(
        string='Preview',
        compute='_compute_preview_message'
    )
    
    @api.depends('quantity', 'source_mo_id', 'product_name')
    def _compute_preview_message(self):
        """Show preview of what will be created"""
        for wizard in self:
            if wizard.source_mo_id and wizard.quantity > 0:
                wizard.preview_message = f"""
                <div style="padding: 15px; background-color: #f0f8ff; border-left: 4px solid #2196F3;">
                    <h4 style="margin-top: 0;">📋 Preview</h4>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 5px;"><strong>Product:</strong></td>
                            <td style="padding: 5px;">{wizard.product_name}</td>
                        </tr>
                        <tr>
                            <td style="padding: 5px;"><strong>Quantity per MO:</strong></td>
                            <td style="padding: 5px;">1.0 {wizard.source_mo_id.product_uom_id.name}</td>
                        </tr>
                        <tr>
                            <td style="padding: 5px;"><strong>MOs to create:</strong></td>
                            <td style="padding: 5px;">{wizard.quantity}</td>
                        </tr>
                        <tr style="background-color: #e3f2fd;">
                            <td style="padding: 5px;"><strong>Total units:</strong></td>
                            <td style="padding: 5px;"><strong>{wizard.quantity} × 1.0 = {wizard.quantity} {wizard.source_mo_id.product_uom_id.name}</strong></td>
                        </tr>
                    </table>
                    <p style="margin-bottom: 0; margin-top: 10px; color: #666;">
                        <em>Each MO will use the exact same formula and BOM.</em>
                    </p>
                </div>
                """
            else:
                wizard.preview_message = '<p>Enter quantity to see preview</p>'
    
    @api.constrains('quantity')
    def _check_quantity(self):
        """Validate quantity is reasonable"""
        for wizard in self:
            if wizard.quantity < 1:
                raise ValidationError(_('Quantity must be at least 1.'))
            if wizard.quantity > 100:
                raise ValidationError(_(
                    'Maximum 100 MOs can be created at once.\n'
                    'For larger quantities, run this wizard multiple times.'
                ))
    
    def action_duplicate_mos(self):
        """
        Create the duplicate MOs
        """
        self.ensure_one()
        
        if not self.source_mo_id.is_tinting_mo:
            raise ValidationError(_('Source MO must be a tinting Manufacturing Order.'))
        
        created_mos = self.env['mrp.production']
        
        # Create duplicates
        for i in range(self.quantity):
            new_mo = self.source_mo_id.copy({
                'origin': f"Duplicate {i+1} of {self.source_mo_id.name}",
                'source_mo_id': self.source_mo_id.id,
                'product_qty': 1.0,
                'state': 'draft',
            })
            
            # Auto-confirm if requested
            if self.auto_confirm:
                new_mo.action_confirm()
            
            created_mos |= new_mo
        
        # Show notification
        message = _(
            '✓ Successfully created %(count)s Manufacturing Order(s)\n'
            'Product: %(product)s\n'
            'Total units to produce: %(total)s %(uom)s',
            count=self.quantity,
            product=self.product_name,
            total=self.quantity,
            uom=self.source_mo_id.product_uom_id.name
        )
        
        # Return action to view created MOs
        return {
            'type': 'ir.actions.act_window',
            'name': _('Duplicated Manufacturing Orders'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_mos.ids)],
            'context': {'create': False},
            'target': 'current',
        }