# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MrpProduction(models.Model):
    """
    Extension to prevent quantity changes on tinting MOs
    and enable fast duplication
    """
    _inherit = 'mrp.production'
    
    is_tinting_mo = fields.Boolean(
        string='Is Tinting MO',
        compute='_compute_is_tinting_mo',
        store=True,
        help='True if this MO uses a tinting BOM'
    )
    
    duplicate_mo_count = fields.Integer(
        string='Duplicate MO Count',
        compute='_compute_duplicate_mo_count',
        help='Number of MOs created from this one'
    )
    
    source_mo_id = fields.Many2one(
        'mrp.production',
        string='Source MO',
        help='Original MO this was duplicated from',
        copy=False,
        index=True
    )
    
    # NEW FIELD: Customer/Contact relation
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer/Contact',
        help='Customer or contact associated with this manufacturing order',
        tracking=True,
        domain="['|', ('customer_rank', '>', 0), ('supplier_rank', '>', 0)]"
    )
    
    @api.depends('bom_id', 'bom_id.is_tinting_bom')
    def _compute_is_tinting_mo(self):
        """Check if this MO is for tinting"""
        for mo in self:
            mo.is_tinting_mo = mo.bom_id and mo.bom_id.is_tinting_bom
    
    def _compute_duplicate_mo_count(self):
        """Count how many MOs were duplicated from this one"""
        for mo in self:
            mo.duplicate_mo_count = self.env['mrp.production'].search_count([
                ('source_mo_id', '=', mo.id)
            ])
    
    @api.constrains('product_qty', 'bom_id')
    def _check_tinting_mo_quantity(self):
        """
        Prevent quantity changes on tinting MOs
        Tinting formulas are precise - must always produce exactly 1.0 unit
        """
        for mo in self:
            if mo.is_tinting_mo and mo.product_qty != 1.0:
                raise UserError(_(
                    'Cannot change quantity for tinting Manufacturing Orders!\n\n'
                    'Tinting formulas are calculated for exactly 1.0 unit (%(uom)s).\n'
                    'The colorant shots are precise and cannot be scaled.\n\n'
                    '⚠ If you need more units:\n'
                    '1. Use the "Duplicate MO" button to create additional MOs\n'
                    '2. Or create new tinting orders from the wizard\n\n'
                    'Each tint must be done individually to maintain accuracy.',
                    uom=mo.product_uom_id.name
                ))
    
    def write(self, vals):
        """
        Prevent quantity changes on confirmed tinting MOs
        """
        # Check if trying to change quantity on tinting MO
        if 'product_qty' in vals:
            for mo in self:
                if mo.is_tinting_mo and mo.state != 'draft':
                    if vals['product_qty'] != mo.product_qty:
                        raise UserError(_(
                            'Cannot modify quantity on confirmed tinting Manufacturing Order!\n\n'
                            'Product: %(product)s\n'
                            'Original Quantity: %(original)s %(uom)s\n'
                            'Attempted Change: %(new)s %(uom)s\n\n'
                            '⚠ Tinting formulas are precise and locked.\n'
                            'Use the "Duplicate MO" button to create more units.',
                            product=mo.product_id.display_name,
                            original=mo.product_qty,
                            new=vals['product_qty'],
                            uom=mo.product_uom_id.name
                        ))
        
        return super().write(vals)
    
    # ================================================================
    # FAST DUPLICATION METHODS
    # ================================================================
    
    def action_open_duplicate_wizard(self):
        """
        Open wizard to duplicate this MO multiple times
        """
        self.ensure_one()
        
        if not self.is_tinting_mo:
            raise UserError(_('This action is only available for tinting Manufacturing Orders.'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Duplicate Tinting MO'),
            'res_model': 'mrp.production.duplicate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_source_mo_id': self.id,
                'default_product_name': self.product_id.display_name,
            }
        }
    
    def action_view_duplicate_mos(self):
        """
        View all MOs duplicated from this one
        """
        self.ensure_one()
        
        duplicate_mos = self.env['mrp.production'].search([
            ('source_mo_id', '=', self.id)
        ])
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Duplicate MOs'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', duplicate_mos.ids)],
            'context': {'create': False}
        }
    
    def action_duplicate_single(self):
        """
        Quick action: Duplicate this MO once
        """
        self.ensure_one()
        
        if not self.is_tinting_mo:
            raise UserError(_('This action is only available for tinting Manufacturing Orders.'))
        
        new_mo = self._duplicate_tinting_mo()
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Duplicated Tinting MO'),
            'res_model': 'mrp.production',
            'res_id': new_mo.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def _duplicate_tinting_mo(self):
        """
        Internal method: Create exact duplicate of tinting MO
        """
        self.ensure_one()
        
        # Copy the MO
        new_mo = self.copy({
            'origin': f"Copy of {self.name}",
            'source_mo_id': self.id,
            'product_qty': 1.0,  # Always 1.0 for tinting
            'state': 'draft',
        })
        
        # Confirm the new MO immediately
        new_mo.action_confirm()
        
        return new_mo