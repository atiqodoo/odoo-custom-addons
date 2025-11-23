# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


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
    
      # ============================================================
    # NEW: FORMULA TRACKING FIELDS
    # ============================================================
    formula_id = fields.Many2one(
        'tinting.formula',
        string='Saved Formula',
        help='Formula that was created/updated from this MO',
        copy=False,
        readonly=True,
        tracking=True
    )
    
    has_formula = fields.Boolean(
        string='Has Saved Formula',
        compute='_compute_has_formula',
        help='True if a formula exists for this color+category+UOM'
    )
    
    can_save_formula = fields.Boolean(
        string='Can Save Formula',
        compute='_compute_can_save_formula',
        help='True if MO is done and is a tinting MO'
    )
    # ============================================================
    # END NEW FIELDS
    # ============================================================
    
    @api.depends('bom_id', 'bom_id.is_tinting_bom')
    def _compute_is_tinting_mo(self):
        """Check if this MO is for tinting"""
        for mo in self:
            mo.is_tinting_mo = mo.bom_id and mo.bom_id.is_tinting_bom
     # ============================================================
    @api.depends('bom_id.colour_code_id', 'bom_id.base_variant_id')
    def _compute_has_formula(self):
        """
        Check if formula already exists for this combination
        Used to show indicators on MO form
        """
        _logger.debug("🔄 Computing has_formula for MOs...")
        for mo in self:
            if mo.is_tinting_mo and mo.bom_id:
                colour_code = mo.bom_id.colour_code_id
                base_variant = mo.bom_id.base_variant_id
                
                if colour_code and base_variant:
                    base_category = base_variant.categ_id
                    base_uom = mo.bom_id.pack_size_uom_id or base_variant.uom_id
                    
                    # Check if formula exists
                    existing = self.env['tinting.formula'].search([
                        ('colour_code_id', '=', colour_code.id),
                        ('base_category_id', '=', base_category.id),
                        ('base_uom_id', '=', base_uom.id)
                    ], limit=1)
                    mo.has_formula = bool(existing)
                    _logger.debug(f"  MO {mo.name}: has_formula = {mo.has_formula}")
                else:
                    mo.has_formula = False
            else:
                mo.has_formula = False
    
    @api.depends('state', 'is_tinting_mo')
    def _compute_can_save_formula(self):
        """
        Check if MO can save formula (done state + tinting)
        Used for button visibility/enabling
        """
        _logger.debug("🔄 Computing can_save_formula for MOs...")
        for mo in self:
            mo.can_save_formula = mo.is_tinting_mo and mo.state == 'done'
            _logger.debug(f"  MO {mo.name}: can_save_formula = {mo.can_save_formula}")
    # ============================================================
    # END NEW COMPUTE METHODS
    # ============================================================
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
    # NEW: FORMULA AUTO-SAVE METHODS
    # ================================================================
    def button_mark_done(self):
        """
        Override to auto-save tinting formulas when MO is completed
        
        Workflow:
        1. Call original button_mark_done() to complete MO
        2. For each tinting MO, try to auto-save formula
        3. If error, log but don't block MO completion
        """
        _logger.info("=" * 80)
        _logger.info("🎯 BUTTON_MARK_DONE CALLED - Completing Manufacturing Orders")
        _logger.info("=" * 80)
        
        # Call original method first to complete the MO
        res = super(MrpProduction, self).button_mark_done()
        
        _logger.info("✅ Original button_mark_done() completed successfully")
        
        # Auto-save formulas for tinting MOs
        for mo in self:
            if mo.is_tinting_mo and mo.bom_id:
                _logger.info(f"📋 Processing tinting MO: {mo.name}")
                try:
                    mo._auto_save_tinting_formula()
                except Exception as e:
                    # Log error but don't block MO completion
                    _logger.error("=" * 80)
                    _logger.error(f"❌ FORMULA AUTO-SAVE FAILED for MO {mo.name}")
                    _logger.error(f"Error: {e}")
                    _logger.error("=" * 80)
                    _logger.error("⚠️ MO completion successful but formula not saved")
                    _logger.error("You can manually save formula later if needed")
            else:
                _logger.debug(f"  Skipping non-tinting MO: {mo.name}")
        
        _logger.info("=" * 80)
        return res
    
    def _auto_save_tinting_formula(self):
        """
        Automatically create/update formula when tinting MO is completed
        
        Logic:
        1. Extract colour code, base product from BOM
        2. Get colorant shots from BOM lines
        3. Check if formula already exists
        4. Create new or update existing formula
        5. Link formula to MO for traceability
        """
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info(f"🎨 AUTO-SAVE FORMULA - MO: {self.name}")
        _logger.info("=" * 80)
        
        # ============================================================
        # STEP 1: VALIDATE DATA
        # ============================================================
        _logger.info("📋 STEP 1: Validating data...")
        
        colour_code = self.bom_id.colour_code_id
        base_product = self.bom_id.base_variant_id
        
        if not colour_code or not base_product:
            _logger.warning("❌ Missing colour code or base product - Cannot save formula")
            _logger.warning(f"  Colour code: {colour_code.code if colour_code else 'MISSING'}")
            _logger.warning(f"  Base product: {base_product.name if base_product else 'MISSING'}")
            return False
        
        base_category = base_product.categ_id
        base_uom = self.bom_id.pack_size_uom_id or base_product.uom_id
        
        # Get product attribute name and ID (if exists)
        # Get product attribute name and ID (if exists)
        base_attribute_name = False
        base_attribute_id = False
        if base_product.product_template_attribute_value_ids:
            attr = base_product.product_template_attribute_value_ids[0]
            if attr:
                attr_name = str(attr.name).lower().strip()
                # Remove variant code if present (e.g., "accent base/e/b3" → "accent base")
                if '/' in attr_name:
                    attr_name = attr_name.split('/')[0].strip()
                base_attribute_name = attr_name
                base_attribute_id = attr.id
        
        _logger.info(f"  ✅ Colour Code: {colour_code.code} - {colour_code.name}")
        _logger.info(f"  ✅ Base Product: {base_product.name}")
        _logger.info(f"  ✅ Category: {base_category.name} (ID: {base_category.id})")
        _logger.info(f"  ✅ UOM: {base_uom.name} (ID: {base_uom.id})")
        _logger.info(f"  ✅ Attribute: {base_attribute_name if base_attribute_name else 'None'}")
        
        # ============================================================
        # STEP 2: EXTRACT COLORANT SHOTS FROM BOM
        # ============================================================
        _logger.info("📋 STEP 2: Extracting colorant shots from BOM...")
        
        colorant_lines = self.bom_id.bom_line_ids.filtered('is_colorant_line')
        
        if not colorant_lines:
            _logger.warning("❌ No colorant lines in BOM - Nothing to save")
            return False
        
        _logger.info(f"  Found {len(colorant_lines)} colorant lines in BOM")
        
        # Build formula line values
        formula_line_vals = []
        for bom_line in colorant_lines:
            if bom_line.colorant_shots > 0:  # Only save non-zero shots
                colorant_code = bom_line.product_id.product_tmpl_id.colorant_code
                # Extract number from C1, C2, etc. for sequence
                sequence = int(colorant_code[1:]) if colorant_code and len(colorant_code) > 1 else 999
                
                formula_line_vals.append((0, 0, {
                    'colorant_id': bom_line.product_id.id,
                    'shots': bom_line.colorant_shots,
                    'sequence': sequence,
                }))
                _logger.info(f"    ✓ {colorant_code}: {bom_line.colorant_shots} shots")
        
        if not formula_line_vals:
            _logger.warning("❌ No non-zero colorant shots - Nothing to save")
            return False
        
        _logger.info(f"  ✅ Prepared {len(formula_line_vals)} colorant lines for formula")
        
        # ============================================================
        # STEP 3: CHECK FOR EXISTING FORMULA
        # ============================================================
        _logger.info("📋 STEP 3: Checking for existing formula...")
        
        existing_formula = self.env['tinting.formula'].search([
            ('colour_code_id', '=', colour_code.id),
            ('base_category_id', '=', base_category.id),
            ('base_uom_id', '=', base_uom.id),
            ('base_attribute_name', '=', base_attribute_name)
        ], limit=1)
        
        # ============================================================
        # STEP 4: CREATE OR UPDATE FORMULA
        # ============================================================
        if existing_formula:
            _logger.info(f"  ℹ️  FORMULA EXISTS: {existing_formula.name} (ID: {existing_formula.id})")
            _logger.info(f"  Checking if formula needs update...")
            
            # Compare shots to detect changes
            if self._formula_has_changed(existing_formula, formula_line_vals):
                _logger.info(f"  🔄 FORMULA CHANGED - Updating...")
                
                # Delete old lines
                existing_formula.formula_line_ids.unlink()
                
                # Update formula with new lines
                existing_formula.write({
                    'formula_line_ids': formula_line_vals,
                    'source_mo_id': self.id,
                    'source_bom_id': self.bom_id.id,
                })
                
                # Log change in chatter
                existing_formula.message_post(
                    body=f"Formula updated from MO <a href='#id={self.id}&model=mrp.production'>{self.name}</a>",
                    subject="Formula Updated"
                )
                
                # Link formula to MO
                self.formula_id = existing_formula
                
                _logger.info(f"  ✅ FORMULA UPDATED: {existing_formula.name}")
                _logger.info(f"  Updated {len(formula_line_vals)} colorant lines")
            else:
                _logger.info(f"  ✓ FORMULA UNCHANGED - No update needed")
                _logger.info(f"  Existing formula matches BOM exactly")
                # Still link formula to MO for traceability
                self.formula_id = existing_formula
        
        else:
            _logger.info(f"  ➕ NO EXISTING FORMULA - Creating new...")
            
           # Create new formula
            formula_vals = {
                'colour_code_id': colour_code.id,
                'base_category_id': base_category.id,
                'base_uom_id': base_uom.id,
                'formula_line_ids': formula_line_vals,
                'source_mo_id': self.id,
                'source_bom_id': self.bom_id.id,
                'state': 'validated',
                'notes': f'Auto-created from MO {self.name}',
            }
            
            # Add attribute if present (store both ID and name)
            if base_attribute_id:
                formula_vals['base_attribute_id'] = base_attribute_id
            
            new_formula = self.env['tinting.formula'].create(formula_vals)
            
            # Link formula to MO
            self.formula_id = new_formula
            
            _logger.info(f"  ✅ FORMULA CREATED: {new_formula.name} (ID: {new_formula.id})")
            _logger.info(f"  Created with {len(formula_line_vals)} colorant lines")
            
           
        
        _logger.info("=" * 80)
        _logger.info("✅ FORMULA AUTO-SAVE COMPLETED SUCCESSFULLY")
        _logger.info("=" * 80)
        return True
    
    def _formula_has_changed(self, formula, new_line_vals):
        """
        Compare existing formula with new shots
        Returns True if different
        
        Args:
            formula: existing tinting.formula record
            new_line_vals: list of (0, 0, {...}) tuples with new shots
        
        Returns:
            bool: True if shots are different
        """
        _logger.debug("🔍 Comparing formula shots...")
        
        # Extract current shots as dict: {colorant_id: shots}
        current_shots = {
            line.colorant_id.id: line.shots
            for line in formula.formula_line_ids
        }
        
        # Extract new shots from vals
        new_shots = {
            val[2]['colorant_id']: val[2]['shots']
            for val in new_line_vals
        }
        
        # Log comparison
        _logger.debug(f"  Current formula shots: {current_shots}")
        _logger.debug(f"  New BOM shots: {new_shots}")
        
        # Compare
        is_different = current_shots != new_shots
        
        if is_different:
            _logger.debug("  ❌ Shots are DIFFERENT - Update needed")
        else:
            _logger.debug("  ✓ Shots are IDENTICAL - No update needed")
        
        return is_different
    # ================================================================
    # END NEW FORMULA AUTO-SAVE METHODS
    # ================================================================
    
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