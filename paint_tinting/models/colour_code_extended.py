# -*- coding: utf-8 -*-
"""
Colour Code Extension
=====================
Extends the colour.code model from paint_colour_master module.
Adds formula relationship fields to link colour codes with saved formulas.

Module: paint_colour_master (base module)
    └── colour.code (base model)
        
Module: paint_tinting (this module)
    └── colour.code (inherited/extended here)
        └── Adds: formula_ids, formula_count, get_formula(), action_view_formulas()

This extension allows each colour code to have multiple formula variants
based on different base products (category + UOM combinations).
"""

from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class ColourCodeExtended(models.Model):
    """
    Extend colour.code from paint_colour_master module
    Add formula relationship and helper methods
    """
    _inherit = 'colour.code'

    # ============================================================
    # NEW FIELDS: FORMULA RELATIONSHIP
    # ============================================================
    formula_ids = fields.One2many(
        'tinting.formula',
        'colour_code_id',
        string='Formulas',
        help='Formula variants for this colour code (different base categories/UOMs)'
    )
    
    formula_count = fields.Integer(
        string='Formula Variants',
        compute='_compute_formula_count',
        help='Number of active formula variants for this colour'
    )

    # ============================================================
    # COMPUTE METHODS
    # ============================================================
    @api.depends('formula_ids')
    def _compute_formula_count(self):
        """
        Count active formula variants
        
        Example:
            Colour: 10B21 (Sage Green)
            ├── Formula 1: Vinyl Silk - 4L  ✓ Active
            ├── Formula 2: Vinyl Silk - 1L  ✓ Active
            └── Formula 3: Matt Emulsion - 4L  ✗ Archived
            
            formula_count = 2 (only active formulas)
        """
        _logger.debug("🔄 Computing formula counts for colour codes...")
        for record in self:
            # Count only active formulas (archived formulas excluded)
            record.formula_count = len(record.formula_ids.filtered('active'))
            _logger.debug(f"  {record.code}: {record.formula_count} active formulas")

    # ============================================================
    # HELPER METHODS - Used by Wizard
    # ============================================================
    def get_formula(self, base_category_id, base_uom_id, base_attribute_name=False):
        """
        Search for matching formula
        
        Args:
            base_category_id (int): Product category ID
            base_uom_id (int): UOM ID
            base_attribute_name (str): Attribute name (e.g., "accent base") - Optional
        """
        self.ensure_one()
        
        _logger.debug(f"🔍 Searching formula for colour: {self.code}")
        _logger.debug(f"  Looking for: category_id={base_category_id}, uom_id={base_uom_id}, attribute_name='{base_attribute_name}'")
        
        # Normalize attribute name for comparison
        search_attr_name = str(base_attribute_name).lower().strip() if base_attribute_name else False
        
        # Search for exact match by attribute NAME
        matching_formula = self.formula_ids.filtered(
            lambda f: f.base_category_id.id == base_category_id
            and f.base_uom_id.id == base_uom_id
            and f.base_attribute_name == search_attr_name
            and f.active
        )
        
        if matching_formula:
            # Should only be one due to SQL constraint, but use first just in case
            formula = matching_formula[0]
            _logger.info(f"  ✅ Found formula: {formula.name}")
            return formula
        else:
            _logger.info(f"  ❌ No formula found")
            return False
    # ============================================================
    # ACTIONS - Button Methods
    # ============================================================
    def action_view_formulas(self):
        """
        Smart button: View all formula variants for this colour
        
        Opens a filtered view showing only formulas for this colour code.
        Used on colour code form view smart button.
        
        Returns:
            dict: Window action to open formula tree/form views
        """
        self.ensure_one()
        
        _logger.info(f"📋 Opening formulas for colour: {self.code}")
        
        return {
            'type': 'ir.actions.act_window',
            'name': f'Formulas for {self.code}',
            'res_model': 'tinting.formula',
            'view_mode': 'tree,form',
            'domain': [('colour_code_id', '=', self.id)],
            'context': {
                'default_colour_code_id': self.id,
                'search_default_active': 1,  # Show active formulas by default
            },
        }