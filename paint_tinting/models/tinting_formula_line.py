# -*- coding: utf-8 -*-
"""
Tinting Formula Line Model
===========================
Individual colorant shot within a formula.
Each line represents one colorant (C1-C16) with its shot count.

Parent: tinting.formula
Child of: colour.code → tinting.formula → tinting.formula.line (this model)

Example lines in a formula:
    Formula: "10B21 - Vinyl Silk - 4L"
    ├── Line 1: C1 → 10.5 shots (6.468 ml)
    ├── Line 2: C3 → 5.0 shots (3.080 ml)
    └── Line 3: C14 → 2.5 shots (1.540 ml)
"""

from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class TintingFormulaLine(models.Model):
    """
    Tinting Formula Line - Individual Colorant Shot
    Stores one colorant's shot count within a formula
    """
    _name = 'tinting.formula.line'
    _description = 'Tinting Formula Line'
    _order = 'sequence, colorant_code'

    # ============================================================
    # PARENT RELATIONSHIP - Links to tinting.formula
    # ============================================================
    formula_id = fields.Many2one(
        'tinting.formula',
        string='Formula',
        required=True,
        ondelete='cascade',
        index=True,
        help='Parent formula this line belongs to'
    )

    # ============================================================
    # COLORANT INFORMATION
    # ============================================================
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Used for ordering (C1=1, C2=2, etc.)'
    )
    
    colorant_id = fields.Many2one(
        'product.product',
        string='Colorant',
        required=True,
        domain="[('product_tmpl_id.is_colorant', '=', True)]",
        help='Colorant product (C1-C16)'
    )
    
    colorant_code = fields.Char(
        string='Code',
        related='colorant_id.product_tmpl_id.colorant_code',
        store=True,
        readonly=True,
        help='Colorant code (C1, C2, ... C16)'
    )
    
    colorant_name = fields.Char(
        string='Colorant',
        related='colorant_id.name',
        readonly=True,
        help='Colorant product name'
    )

    # ============================================================
    # SHOT VALUES - Core Data
    # ============================================================
    shots = fields.Float(
        string='Shots',
        required=True,
        digits=(10, 2),
        help='Number of colorant shots from LargoTint machine'
    )
    
    ml_volume = fields.Float(
        string='ML',
        compute='_compute_ml_volume',
        store=True,
        digits=(10, 3),
        help='Volume in milliliters (shots × 0.616)'
    )
    
    qty_litres = fields.Float(
        string='Litres',
        compute='_compute_qty_litres',
        store=True,
        digits=(10, 6),
        help='Volume in litres (ml ÷ 1000)'
    )

    # ============================================================
    # CONSTRAINTS
    # ============================================================
    _sql_constraints = [
        ('shots_positive', 
         'CHECK(shots > 0)', 
         'Shots must be greater than zero! Only non-zero shots should be saved.')
    ]

    # ============================================================
    # COMPUTE METHODS - Automatic Conversions
    # ============================================================
    @api.depends('shots')
    def _compute_ml_volume(self):
        """
        Convert shots to milliliters
        Conversion: 1 shot = 0.616 ml (LargoTint machine specification)
        
        Example:
            10 shots × 0.616 = 6.160 ml
        """
        _logger.debug("🔄 Computing ml_volume for formula lines...")
        for line in self:
            line.ml_volume = line.shots * 0.616
            _logger.debug(f"  {line.colorant_code}: {line.shots} shots → {line.ml_volume} ml")

    @api.depends('ml_volume')
    def _compute_qty_litres(self):
        """
        Convert milliliters to litres
        Conversion: litres = ml ÷ 1000
        
        Example:
            6.160 ml ÷ 1000 = 0.006160 L
        
        Note: This is the exact quantity used in BOM lines
        """
        _logger.debug("🔄 Computing qty_litres for formula lines...")
        for line in self:
            line.qty_litres = line.ml_volume / 1000.0
            _logger.debug(f"  {line.colorant_code}: {line.ml_volume} ml → {line.qty_litres} L")