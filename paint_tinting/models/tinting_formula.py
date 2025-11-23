# -*- coding: utf-8 -*-
"""
Tinting Formula Model
=====================
Stores proven colorant shot formulas for specific color + base product combinations.
Formulas are automatically created when Manufacturing Orders are marked as "Done".

Hierarchy:
    colour.code (parent)
    └── tinting.formula (this model)
        └── tinting.formula.line (colorant shots)

Example:
    Colour: 10B21 (Sage Green)
    ├── Formula 1: Vinyl Silk - 4L (C1: 10 shots, C3: 5 shots)
    ├── Formula 2: Vinyl Silk - 1L (C1: 2.5 shots, C3: 1.25 shots)
    └── Formula 3: Matt Emulsion - 4L (C1: 12 shots, C2: 3 shots)
"""

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class TintingFormula(models.Model):
    """
    Tinting Formula Storage Model
    Stores colorant shot formulas for reuse in tinting wizard
    """
    _name = 'tinting.formula'
    _description = 'Tinting Formula'
    _order = 'colour_code_id, base_category_id, base_uom_id'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # ============================================================
    # PARENT RELATIONSHIP - Links to colour.code
    # ============================================================
    colour_code_id = fields.Many2one(
        'colour.code',
        string='Colour Code',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
        help='Parent colour code this formula belongs to (e.g., 10B21, 16C33)'
    )
    
    fandeck_id = fields.Many2one(
        'colour.fandeck',
        string='Fandeck',
        related='colour_code_id.fandeck_id',
        store=True,
        readonly=True,
        help='Fandeck from colour code (e.g., BS4800, RAL)'
    )
    
    colour_name = fields.Char(
        string='Colour Name',
        related='colour_code_id.name',
        store=True,
        readonly=True,
        help='Colour name from colour code (e.g., "Sage Green")'
    )

    # ============================================================
    # FORMULA IDENTITY - Makes formula unique
    # ============================================================
    name = fields.Char(
        string='Formula Name',
        compute='_compute_name',
        store=True,
        help='Auto-generated: ColorCode - Category - UOM (e.g., "10B21 - Vinyl Silk - 4L")'
    )
    
    base_category_id = fields.Many2one(
        'product.category',
        string='Base Category',
        required=True,
        index=True,
        tracking=True,
        help='Product category of base paint (e.g., "Vinyl Silk", "Matt Emulsion")'
    )
    
    base_uom_id = fields.Many2one(
        'uom.uom',
        string='Base UOM',
        required=True,
        index=True,
        tracking=True,
        help='Unit of measure (e.g., 1L, 4L, 20L)'
    )
    
    base_attribute_id = fields.Many2one(
        'product.template.attribute.value',
        string='Base Attribute',
        required=False,
        tracking=True,
        help='Base product attribute (e.g., Pastel Base, Deep Base, Accent Base)'
    )
    
    base_attribute_name = fields.Char(
        string='Attribute Name',
        compute='_compute_base_attribute_name',
        store=True,
        index=True,
        readonly=True,
        help='Attribute name for display and matching'
    )
    @api.depends('base_attribute_id.name')
    def _compute_base_attribute_name(self):
        """
        Store normalized attribute name for matching across product templates
        Strips variant codes (e.g., "accent base/e/b3" → "accent base")
        """
        for record in self:
            if record.base_attribute_id:
                # Get the attribute value name
                attr_name = str(record.base_attribute_id.name).lower().strip()
                
                # Remove variant code if present (anything after "/")
                # Examples: "accent base/e/b3" → "accent base"
                #           "deep base" → "deep base"
                if '/' in attr_name:
                    attr_name = attr_name.split('/')[0].strip()
                
                record.base_attribute_name = attr_name
            else:
                record.base_attribute_name = False
    # ============================================================
    # FORMULA LINES - Colorant shots (C1-C16)
    # ============================================================
    formula_line_ids = fields.One2many(
        'tinting.formula.line',
        'formula_id',
        string='Colorant Shots',
        help='Individual colorant shots for this formula (only non-zero shots)'
    )

    # ============================================================
    # COMPUTED TOTALS
    # ============================================================
    total_shots = fields.Float(
        string='Total Shots',
        compute='_compute_totals',
        store=True,
        digits=(10, 2),
        help='Sum of all colorant shots'
    )
    
    total_ml = fields.Float(
        string='Total ML',
        compute='_compute_totals',
        store=True,
        digits=(10, 3),
        help='Total colorant volume in milliliters'
    )
    
    total_litres = fields.Float(
        string='Total Litres',
        compute='_compute_totals',
        store=True,
        digits=(10, 6),
        help='Total colorant volume in litres'
    )

    # ============================================================
    # METADATA & TRACEABILITY
    # ============================================================
    source_mo_id = fields.Many2one(
        'mrp.production',
        string='Source MO',
        help='Manufacturing Order that created/updated this formula',
        tracking=True
    )
    
    source_bom_id = fields.Many2one(
        'mrp.bom',
        string='Source BOM',
        help='Bill of Materials that created/updated this formula',
        tracking=True
    )
    
    created_date = fields.Datetime(
        string='Created On',
        default=fields.Datetime.now,
        readonly=True,
        help='Timestamp when formula was first created'
    )
    
    created_by_id = fields.Many2one(
        'res.users',
        string='Created By',
        default=lambda self: self.env.user,
        readonly=True,
        help='User who created this formula'
    )

    # ============================================================
    # USAGE TRACKING - Analytics
    # ============================================================
    times_used = fields.Integer(
        string='Times Applied',
        default=0,
        readonly=True,
        help='Number of times this formula has been used in tinting wizard'
    )
    
    last_used_date = fields.Datetime(
        string='Last Used',
        readonly=True,
        help='Last time this formula was applied in wizard'
    )

    # ============================================================
    # STATUS & NOTES
    # ============================================================
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Uncheck to archive formula (hidden from searches)'
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Validated'),
        ('approved', 'Approved')
    ], string='Status', default='validated', tracking=True,
       help='Draft: New/testing | Validated: Auto-saved from MO | Approved: Verified by manager')
    
    notes = fields.Text(
        string='Notes',
        help='Additional notes, special instructions, or adjustments made'
    )

    # ============================================================
    # SQL CONSTRAINTS
    # ============================================================
    _sql_constraints = [
        ('unique_formula_variant',
         'unique(colour_code_id, base_category_id, base_uom_id, base_attribute_name)',
         'A formula already exists for this colour + category + UOM + attribute combination!')
    ]

    # ============================================================
    # COMPUTE METHODS
    # ============================================================
    @api.depends('colour_code_id.code', 'base_category_id.name', 'base_uom_id.name', 'base_attribute_name')
    def _compute_name(self):
        """
        Auto-generate formula name from components
        Format: "ColorCode - Category - UOM - Attribute" or "ColorCode - Category - UOM"
        Example: "10B21 - Vinyl Silk - 4L - Pastel Base"
        Example: "10B21 - Vinyl Silk - 4L" (if no attribute)
        """
        _logger.debug("🔄 Computing formula names...")
        for record in self:
            colour = record.colour_code_id.code or 'Unknown'
            category = record.base_category_id.name or 'Unknown'
            uom = record.base_uom_id.name or 'Unknown'
            
            # Add attribute if present
            if record.base_attribute_name:
                record.name = f"{colour} - {category} - {uom} - {record.base_attribute_name}"
            else:
                record.name = f"{colour} - {category} - {uom}"
            
            _logger.debug(f"  Formula name: {record.name}")
            
            
    @api.depends('formula_line_ids.shots', 'formula_line_ids.ml_volume', 'formula_line_ids.qty_litres')
    def _compute_totals(self):
        """
        Calculate total shots and volumes from formula lines
        Triggered whenever colorant shots change
        """
        _logger.debug("🔄 Computing formula totals...")
        for record in self:
            record.total_shots = sum(line.shots for line in record.formula_line_ids)
            record.total_ml = sum(line.ml_volume for line in record.formula_line_ids)
            record.total_litres = sum(line.qty_litres for line in record.formula_line_ids)
            _logger.debug(f"  {record.name}: {record.total_shots} shots = {record.total_ml} ml")

    # ============================================================
    # HELPER METHODS - Used by Wizard
    # ============================================================
    def get_shots_dict(self):
        """
        Return shots as dictionary for easy application in wizard
        Returns: {'C1': 10.5, 'C2': 5.0, ...}
        
        Usage in wizard:
            formula_shots = formula.get_shots_dict()
            for wizard_line in self.colorant_line_ids:
                if wizard_line.colorant_code in formula_shots:
                    wizard_line.shots = formula_shots[wizard_line.colorant_code]
        """
        self.ensure_one()
        shots_dict = {
            line.colorant_code: line.shots
            for line in self.formula_line_ids
            if line.colorant_code
        }
        _logger.debug(f"📋 Formula {self.name} shots dict: {shots_dict}")
        return shots_dict

    def increment_usage_counter(self):
        """
        Increment usage counter when formula is applied in wizard
        Tracks formula popularity and last use date
        """
        self.ensure_one()
        _logger.info(f"📊 Incrementing usage counter for: {self.name}")
        self.write({
            'times_used': self.times_used + 1,
            'last_used_date': fields.Datetime.now()
        })
        _logger.info(f"  Total uses: {self.times_used + 1}")

    def compare_with_bom(self, bom_id):
        """
        Compare formula shots with BOM colorant lines
        Returns: dict with differences
        
        Used during auto-save to detect if formula changed
        
        Returns example:
        {
            'C1': {'formula': 10.0, 'bom': 10.5, 'diff': 0.5},
            'C3': {'formula': 5.0, 'bom': 5.0, 'diff': 0.0}
        }
        """
        self.ensure_one()
        _logger.debug(f"🔍 Comparing formula {self.name} with BOM {bom_id}...")
        
        bom = self.env['mrp.bom'].browse(bom_id)
        
        # Get current formula shots
        formula_shots = self.get_shots_dict()
        
        # Get BOM shots
        bom_shots = {}
        for line in bom.bom_line_ids.filtered('is_colorant_line'):
            code = line.product_id.product_tmpl_id.colorant_code
            if code and line.colorant_shots > 0:
                bom_shots[code] = line.colorant_shots
        
        # Find differences
        differences = {}
        all_codes = set(formula_shots.keys()) | set(bom_shots.keys())
        
        for code in all_codes:
            formula_val = formula_shots.get(code, 0.0)
            bom_val = bom_shots.get(code, 0.0)
            if formula_val != bom_val:
                differences[code] = {
                    'formula': formula_val,
                    'bom': bom_val,
                    'diff': bom_val - formula_val
                }
                _logger.debug(f"  {code}: formula={formula_val}, bom={bom_val}, diff={bom_val - formula_val}")
        
        return differences

    # ============================================================
    # ACTIONS - Button Methods
    # ============================================================
    def action_approve(self):
        """Mark formula as approved (manager action)"""
        _logger.info(f"✅ Approving formula: {self.name}")
        self.write({'state': 'approved'})

    def action_reset_to_draft(self):
        """Reset formula to draft for editing"""
        _logger.info(f"📝 Resetting formula to draft: {self.name}")
        self.write({'state': 'draft'})