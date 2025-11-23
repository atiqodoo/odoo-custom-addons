# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class TintWizardColorantLine(models.TransientModel):
    _name = 'tint.wizard.colorant.line'
    _description = 'Tinting Wizard Colorant Line'
    _order = 'colorant_code'

    wizard_id = fields.Many2one('tint.wizard', required=True, ondelete='cascade')
    colorant_id = fields.Many2one(
        'product.product',
        string='Colorant',
        domain="[('product_tmpl_id.is_colorant', '=', True)]",
        help='Colorant product (C1–C16)'
    )
    colorant_name = fields.Char(compute='_compute_colorant_name', store=True, readonly=True)
    colorant_code = fields.Char(related='colorant_id.product_tmpl_id.colorant_code', readonly=True, store=True)
    shots = fields.Float(string='Shots', digits=(10, 2), default=0.0)
    ml_volume = fields.Float(compute='_compute_ml_volume', store=True, digits=(10, 3))
    qty_litres = fields.Float(compute='_compute_qty_litres', store=True, digits=(10, 6))
    available_stock = fields.Float(compute='_compute_available_stock', digits=(10, 4))
    stock_warning = fields.Boolean(compute='_compute_stock_warning')
    unit_cost_excl_vat = fields.Float(related='colorant_id.standard_price', readonly=True, digits='Product Price')
    unit_cost_incl_vat = fields.Float(compute='_compute_unit_cost_incl_vat', digits='Product Price')
    line_cost_excl_vat = fields.Float(compute='_compute_line_costs', digits='Product Price')
    line_cost_incl_vat = fields.Float(compute='_compute_line_costs', digits='Product Price')

    @api.depends('shots')
    def _compute_ml_volume(self):
        """Convert shots to milliliters (1 shot = 0.616 ml)"""
        _logger.info("🔄 Computing ml_volume for colorant lines")
        for line in self:
            line.ml_volume = line.shots * 0.616
            _logger.debug(f"  Colorant {line.colorant_code}: {line.shots} shots = {line.ml_volume} ml")

    @api.depends('ml_volume')
    def _compute_qty_litres(self):
        """Convert milliliters to litres (ml ÷ 1000)"""
        _logger.info("🔄 Computing qty_litres for colorant lines")
        for line in self:
            line.qty_litres = line.ml_volume / 1000.0
            _logger.debug(f"  Colorant {line.colorant_code}: {line.ml_volume} ml = {line.qty_litres} L")

    @api.depends('colorant_id')
    def _compute_available_stock(self):
        """Get available stock for colorant in litres"""
        _logger.info("🔄 Computing available_stock for colorant lines")
        for line in self:
            line.available_stock = line.colorant_id.qty_available if line.colorant_id else 0.0
            _logger.debug(f"  Colorant {line.colorant_code}: available stock = {line.available_stock} L")

    @api.depends('qty_litres', 'available_stock')
    def _compute_stock_warning(self):
        """Check if stock is insufficient (only for lines with shots > 0)"""
        _logger.info("🔄 Computing stock_warning for colorant lines")
        for line in self:
            line.stock_warning = line.shots > 0 and line.qty_litres > line.available_stock
            if line.stock_warning:
                _logger.warning(f"  ⚠ Stock warning for {line.colorant_code}: need {line.qty_litres}L, have {line.available_stock}L")

    @api.depends('unit_cost_excl_vat')
    def _compute_unit_cost_incl_vat(self):
        """Calculate VAT-inclusive unit cost (16% VAT)"""
        _logger.info("🔄 Computing unit_cost_incl_vat for colorant lines")
        for line in self:
            line.unit_cost_incl_vat = line.unit_cost_excl_vat * 1.16
            _logger.debug(f"  Colorant {line.colorant_code}: excl={line.unit_cost_excl_vat}, incl={line.unit_cost_incl_vat}")

    @api.depends('unit_cost_excl_vat', 'qty_litres')
    def _compute_line_costs(self):
        """Calculate total line costs"""
        _logger.info("🔄 Computing line_costs for colorant lines")
        for line in self:
            line.line_cost_excl_vat = line.unit_cost_excl_vat * line.qty_litres
            line.line_cost_incl_vat = line.unit_cost_incl_vat * line.qty_litres
            _logger.debug(f"  Colorant {line.colorant_code}: line cost excl={line.line_cost_excl_vat}, incl={line.line_cost_incl_vat}")

    @api.depends('colorant_id.name')
    def _compute_colorant_name(self):
        """Compute colorant name without related+store=True to avoid translation bug"""
        _logger.info("🔄 Computing colorant_name for colorant lines")
        for line in self:
            line.colorant_name = line.colorant_id.name if line.colorant_id else ''
            _logger.debug(f"  Colorant {line.colorant_code}: name = '{line.colorant_name}'")

    @api.onchange('shots')
    def _onchange_shots(self):
        """Force immediate recompute when shots change"""
        _logger.info("🎯 Onchange triggered: shots updated")
        for line in self:
            _logger.debug(f"  Colorant {line.colorant_code}: shots changed to {line.shots}")
            # Force immediate computation
            line._compute_ml_volume()
            line._compute_qty_litres()
            line._compute_line_costs()
            
            # Also trigger parent wizard recompute
            if line.wizard_id:
                line.wizard_id._compute_totals()
                line.wizard_id._compute_warnings()

    @api.onchange('colorant_id')
    def _onchange_colorant_id(self):
        """Recompute when colorant selection changes"""
        _logger.info("🎯 Onchange triggered: colorant_id updated")
        for line in self:
            _logger.debug(f"  Colorant selection changed to: {line.colorant_id.name if line.colorant_id else 'None'}")
            line._compute_available_stock()
            line._compute_stock_warning()
            line._compute_colorant_name()
            
            if line.wizard_id:
                line.wizard_id._compute_warnings()


class TintWizard(models.TransientModel):
    _name = 'tint.wizard'
    _description = 'Paint Tinting Wizard - Single Page'

    base_variant_id = fields.Many2one('product.product', string='Base Product', required=True)
    fandeck_id = fields.Many2one('colour.fandeck', string='Fandeck', required=True)
    colour_code_id = fields.Many2one('colour.code', string='Colour Code', required=True)
    colour_name = fields.Char(related='colour_code_id.name', readonly=True)
    notes = fields.Text(string='Notes')
    colorant_line_ids = fields.One2many('tint.wizard.colorant.line', 'wizard_id', string='Colorant Lines')
    
      # ============================================================
    # NEW: FORMULA FIELDS (add these 3 fields)
    # ============================================================
    formula_id = fields.Many2one(
        'tinting.formula',
        string='Applied Formula',
        readonly=True,
        help='Formula currently applied to this wizard'
    )
    
    formula_applied = fields.Boolean(
        string='Formula Applied',
        default=False,
        help='True if a formula has been auto-filled'
    )
    
    available_formulas = fields.Integer(
        string='Available Formulas',
        compute='_compute_available_formulas',
        help='Number of formula variants available for selected colour'
    )
    # ============================================================
    # END NEW FIELDS
    # =

    total_colorant_ml = fields.Float(compute='_compute_totals', digits=(10, 3))
    total_cost_excl_vat = fields.Float(compute='_compute_totals', digits='Product Price')
    total_cost_incl_vat = fields.Float(compute='_compute_totals', digits='Product Price')
    base_cost_excl_vat = fields.Float(compute='_compute_base_cost', digits='Product Price')
    base_cost_incl_vat = fields.Float(compute='_compute_base_cost', digits='Product Price')
    colorant_cost_excl_vat = fields.Float(compute='_compute_totals', digits='Product Price')
    colorant_cost_incl_vat = fields.Float(compute='_compute_totals', digits='Product Price')

    has_stock_warnings = fields.Boolean(compute='_compute_warnings')
    stock_warning_message = fields.Html(compute='_compute_warnings')
    has_mapping_warnings = fields.Boolean(compute='_compute_warnings')
    mapping_warning_message = fields.Html(compute='_compute_warnings')

    @api.model
    def default_get(self, fields_list):
        """
        Override default_get to populate colorant lines when wizard opens
        ==================================================================
        """
        _logger.info("=" * 80)
        _logger.info("🚀 TintWizard.default_get() called - WIZARD OPENING")
        _logger.info("=" * 80)
        
        res = super(TintWizard, self).default_get(fields_list)
        
        if 'colorant_line_ids' in fields_list:
            _logger.info("  ✅ 'colorant_line_ids' requested - populating default lines...")
            
            # Get all mapped colorant products
            colorants = self.env['product.product'].search([
                ('product_tmpl_id.is_colorant', '=', True),
                ('product_tmpl_id.colorant_code', '!=', False)
            ])
            _logger.info(f"  ✅ Found {len(colorants)} mapped colorant products")
            
            # Build mapping dictionary
            code_to_product = {}
            for colorant in colorants:
                code = colorant.product_tmpl_id.colorant_code.strip().upper()
                if code and code.startswith('C'):
                    code_to_product[code] = colorant.id
            
            # Create 16 lines for C1-C16
            lines = []
            for i in range(1, 17):
                code = f'C{i}'
                product_id = code_to_product.get(code, False)
                lines.append((0, 0, {
                    'colorant_id': product_id,
                    'shots': 0.0,
                }))
            
            res['colorant_line_ids'] = lines
            _logger.info(f"  ✅ Set {len(lines)} default colorant lines")
        
        _logger.info("=" * 80)
        return res
     # ============================================================
    # NEW: FORMULA COMPUTE METHOD
    # ============================================================
    @api.depends('colour_code_id')
    def _compute_available_formulas(self):
        """
        Count available formula variants for selected color
        Shows how many saved formulas exist for this colour code
        """
        _logger.debug("🔄 Computing available formulas count...")
        for wizard in self:
            if wizard.colour_code_id:
                wizard.available_formulas = wizard.colour_code_id.formula_count
                _logger.debug(f"  Colour {wizard.colour_code_id.code}: {wizard.available_formulas} formulas available")
            else:
                wizard.available_formulas = 0
    # ============================================================
    # END NEW COMPUTE METHOD
    # ============================================================

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to ensure colorant lines exist and recompute all fields"""
        _logger.info("🚀 TintWizard.create() called - creating new wizard instance")
        wizards = super().create(vals_list)
        for wizard in wizards:
            _logger.info(f"  Setting up wizard ID: {wizard.id}")
            wizard._ensure_colorant_lines()
            wizard._force_recompute_all()
        _logger.info("✅ TintWizard creation completed")
        return wizards

    def _ensure_colorant_lines(self):
        """Ensure 16 colorant lines exist with proper mapping to C1-C16 codes"""
        _logger.info("🔄 _ensure_colorant_lines() - Setting up C1-C16 colorant lines")
        if self.colorant_line_ids:
            _logger.info("  Colorant lines already exist, skipping creation")
            return

        # Get all mapped colorant products
        colorants = self.env['product.product'].search([
            ('product_tmpl_id.is_colorant', '=', True),
            ('product_tmpl_id.colorant_code', '!=', False)
        ])
        _logger.info(f"  Found {len(colorants)} colorant products in system")

        # Create a mapping of colorant_code to product_id
        code_to_product = {}
        for colorant in colorants:
            code = colorant.product_tmpl_id.colorant_code.strip().upper()
            if code and code.startswith('C'):
                code_to_product[code] = colorant.id
                _logger.debug(f"    Mapped {code} -> {colorant.name}")

        # Create 16 lines for C1-C16
        lines = []
        for i in range(1, 17):
            code = f'C{i}'
            product_id = code_to_product.get(code, False)
            lines.append((0, 0, {
                'colorant_id': product_id,
                'shots': 0.0,
            }))
            _logger.debug(f"    Created line for {code} with product ID: {product_id}")

        self.colorant_line_ids = lines
        _logger.info("✅ Colorant lines setup completed")

    def _force_recompute_all(self):
        """Force recompute of all computed fields - ONLY use when colorant lines need updating"""
        _logger.info("🔄 _force_recompute_all() - Triggering full recomputation")
        self.ensure_one()
        
        # CRITICAL FIX: Ensure colorant lines exist BEFORE recomputing
        _logger.info("  🛡️ Ensuring colorant lines exist before recomputation...")
        self._ensure_colorant_lines()
        
        # Recompute colorant line fields
        _logger.info("  Recomputing colorant line fields...")
        for line in self.colorant_line_ids:
            # Force individual field recomputes
            line._compute_ml_volume()
            line._compute_qty_litres()
            line._compute_unit_cost_incl_vat()
            line._compute_line_costs()
            line._compute_available_stock()
            line._compute_stock_warning()
            line._compute_colorant_name()
        
        # Recompute wizard fields
        _logger.info("  Recomputing wizard fields...")
        self._compute_base_cost()
        self._compute_totals()
        self._compute_warnings()
        _logger.info("✅ Full recomputation completed")
         
    @api.onchange('base_variant_id')
    def _onchange_base_variant_id(self):
        """When base product changes, recalculate costs but preserve colorant lines"""
        _logger.info("🎯 Onchange triggered: base_variant_id updated")
        _logger.info(f"  Base product changed to: {self.base_variant_id.display_name if self.base_variant_id else 'None'}")
        
        # Check if colorant lines already have shots entered
        has_existing_shots = any(line.shots > 0 for line in self.colorant_line_ids)
        
        if has_existing_shots:
            _logger.info(f"  🛡️ Colorant shots already entered - preserving existing values")
            _logger.info(f"  💰 Recomputing base costs only...")
            
            # Recompute costs only (preserve colorant shots)
            self._compute_base_cost()
            self._compute_totals()
            self._compute_warnings()
            
            _logger.info("✅ Base cost recomputation completed (colorant lines preserved)")
            
            # Show warning that costs were updated
            if self.base_variant_id:
                return {
                    'warning': {
                        'title': _('Costs Updated'),
                        'message': _('Costs have been recalculated based on the new base product.\n\n'
                                   '✓ Colorant shots have been preserved.\n\n'
                                   'Note: Different brands may use different formulas for the same color.')
                    }
                }
        else:
            _logger.info(f"  💰 No shots entered - recomputing costs and searching for formula...")
            
            # Recompute costs
            self._compute_base_cost()
            self._compute_totals()
            self._compute_warnings()
            
            # Search for formula ONLY if no shots are entered yet
            if self.base_variant_id and self.colour_code_id:
                _logger.info("🔍 Both base and colour selected - searching for formula...")
                self._search_and_apply_formula()
            
            _logger.info("✅ Base cost recomputation completed")
            
            # Show warning if base product is selected
            if self.base_variant_id:
                return {
                    'warning': {
                        'title': _('Base Product Selected'),
                        'message': _('Base product costs have been calculated.')
                    }
                }
        
         # NEW: SEARCH AND APPLY FORMULA (if both base and colour are set)
        # ============================================================
        if self.base_variant_id and self.colour_code_id:
            _logger.info("🔍 Both base and colour selected - searching for formula...")
            self._search_and_apply_formula()
        # ============================================================
        # END NEW FORMULA SEARCH
        # ============================================================
        
        # Show warning if base product is selected
        if self.base_variant_id:
            return {
                'warning': {
                    'title': _('Costs Updated'),
                    'message': _('Costs have been recalculated based on the new base product.')
                }
            }

    @api.onchange('colour_code_id', 'fandeck_id')
    def _onchange_colour_selection(self):
        """When colour selection changes, search for matching formula"""
        _logger.info("🎯 Onchange triggered: colour_selection updated")
        _logger.info(f"  Fandeck: {self.fandeck_id.name if self.fandeck_id else 'None'}, Colour Code: {self.colour_code_id.code if self.colour_code_id else 'None'}")
        
        # Only recompute warnings (preserve colorant lines)
        _logger.info(f"  ⚠️ Recomputing warnings only (preserving colorant lines)...")
        self._compute_warnings()
        
        # Search for formula ONLY if shots are empty
        if self.base_variant_id and self.colour_code_id:
            # Check if colorant lines already have shots
            has_existing_shots = any(line.shots > 0 for line in self.colorant_line_ids)
            
            if has_existing_shots:
                _logger.info("🛡️ Colorant shots already entered - preserving existing values")
                _logger.info("  (Use Cost Summary to compare different brands with same shots)")
            else:
                _logger.info("🔍 Both base and colour selected - searching for formula...")
                self._search_and_apply_formula()

    @api.onchange('fandeck_id')
    def _onchange_fandeck_id(self):
        """Update domain for colour codes when fandeck changes"""
        _logger.info("🎯 Onchange triggered: fandeck_id updated")
        if self.colour_code_id and self.colour_code_id.fandeck_id != self.fandeck_id:
            _logger.info("  Clearing colour_code_id due to fandeck mismatch")
            self.colour_code_id = False
        return {
            'domain': {
                'colour_code_id': [('fandeck_id', '=', self.fandeck_id.id)] if self.fandeck_id else []
            }
        }

    @api.onchange('colour_code_id')
    def _onchange_colour_code_id(self):
        """Auto-set fandeck when colour code is selected"""
        _logger.info("🎯 Onchange triggered: colour_code_id updated")
        if self.colour_code_id and self.colour_code_id.fandeck_id:
            _logger.info(f"  Auto-setting fandeck to: {self.colour_code_id.fandeck_id.name}")
            self.fandeck_id = self.colour_code_id.fandeck_id
            
          
        # ============================================================
        # NEW: SEARCH AND APPLY FORMULA (if both base and colour are set)
        # ============================================================
        if self.base_variant_id and self.colour_code_id:
            _logger.info("🔍 Both base and colour selected - searching for formula...")
            self._search_and_apply_formula()
        # ============================================================
        # END NEW FORMULA SEARCH
        # ============================================================

    @api.depends('base_variant_id')
    def _compute_base_cost(self):
        """Calculate base product costs"""
        _logger.info("🔄 _compute_base_cost() - Calculating base product costs")
        for w in self:
            if w.base_variant_id:
                w.base_cost_excl_vat = w.base_variant_id.standard_price
                w.base_cost_incl_vat = w.base_variant_id.standard_price * 1.16
                _logger.debug(f"  Base product: {w.base_variant_id.display_name}, cost excl={w.base_cost_excl_vat}, incl={w.base_cost_incl_vat}")
            else:
                w.base_cost_excl_vat = w.base_cost_incl_vat = 0.0
                _logger.debug("  No base product selected, costs set to 0")

    @api.depends('colorant_line_ids.ml_volume', 'colorant_line_ids.line_cost_excl_vat', 'colorant_line_ids.line_cost_incl_vat')
    def _compute_totals(self):
        """Calculate all total costs and volumes"""
        _logger.info("🔄 _compute_totals() - Calculating wizard totals")
        for w in self:
            w.total_colorant_ml = sum(l.ml_volume for l in w.colorant_line_ids)
            w.colorant_cost_excl_vat = sum(l.line_cost_excl_vat for l in w.colorant_line_ids)
            w.colorant_cost_incl_vat = sum(l.line_cost_incl_vat for l in w.colorant_line_ids)
            w.total_cost_excl_vat = w.base_cost_excl_vat + w.colorant_cost_excl_vat
            w.total_cost_incl_vat = w.base_cost_incl_vat + w.colorant_cost_incl_vat
            
            _logger.debug(f"  Totals - ML: {w.total_colorant_ml}, Colorant Cost: {w.colorant_cost_excl_vat}/{w.colorant_cost_incl_vat}, Total: {w.total_cost_excl_vat}/{w.total_cost_incl_vat}")

    @api.depends('colorant_line_ids.stock_warning', 'colorant_line_ids.colorant_id', 'colorant_line_ids.shots', 'base_variant_id')
    def _compute_warnings(self):
        """Compute stock and mapping warnings"""
        _logger.info("🔄 _compute_warnings() - Checking for warnings")
        for w in self:
            stock_msgs = []
            
            # Check base product stock
            if w.base_variant_id and w.base_variant_id.qty_available < 1:
                stock_msgs.append(f"Base: {w.base_variant_id.display_name} (Stock: {w.base_variant_id.qty_available:.2f}L)")
                _logger.warning(f"  ⚠ Base product stock low: {w.base_variant_id.display_name}")
            
            # Check colorant stock warnings
            for line in w.colorant_line_ids.filtered('stock_warning'):
                stock_msgs.append(f"{line.colorant_name or 'Unknown'}: Need {line.qty_litres:.4f}L, Have {line.available_stock:.4f}L")
                _logger.warning(f"  ⚠ Colorant stock low: {line.colorant_name}")
            
            w.has_stock_warnings = bool(stock_msgs)
            w.stock_warning_message = ''.join([f"<div style='color:red;'>Warning: {msg}</div>" for msg in stock_msgs]) or "<div style='color:green;'>All in stock</div>"

            # Check mapping warnings
            unmapped = w.colorant_line_ids.filtered(lambda l: l.shots > 0 and not l.colorant_id)
            w.has_mapping_warnings = bool(unmapped)
            if unmapped:
                codes = ', '.join([f"C{i+1}" for i, l in enumerate(w.colorant_line_ids) if l.shots > 0 and not l.colorant_id])
                w.mapping_warning_message = f"""
                <div style="background:#fff3cd;padding:15px;border:1px solid #ffc107;border-radius:5px;">
                    <strong>Warning: Colorants Not Mapped: {codes}</strong><br/>
                    <a href="/odoo/action-paint_tinting.action_colorant_mapping_wizard" target="_blank">Click to Map Colorants</a>
                </div>
                """
                _logger.warning(f"  ⚠ Unmapped colorants: {codes}")
            else:
                w.mapping_warning_message = "<div style='color:green;'>All colorants mapped</div>"
                _logger.info("  ✅ All colorants properly mapped")

    def action_open_colorant_mapping(self):
        """Open colorant mapping wizard"""
        _logger.info("🎯 action_open_colorant_mapping() - Opening mapping wizard")
        return {
            'type': 'ir.actions.act_window',
            'name': _('Map Colorants'),
            'res_model': 'colorant.mapping.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
        
      # ============================================================
    # NEW: FORMULA AUTO-FILL METHODS
    # ============================================================
    def _search_and_apply_formula(self):
        """
        Search for matching formula and auto-fill shots
        Called when both base_variant_id and colour_code_id are set
        """
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("🔍 FORMULA SEARCH - Starting...")
        _logger.info("=" * 80)
        
        # Extract category & UOM from base product
        # Extract category, UOM, and attribute from base product
        base_category = self.base_variant_id.categ_id
        base_uom = self.base_variant_id.uom_id
        
        # Get product attribute NAME (if exists) - for cross-brand matching
       # Get product attribute NAME (if exists) - for cross-brand matching
        base_attribute_name = False
        if self.base_variant_id.product_template_attribute_value_ids:
            # Get the first attribute value and normalize its name
            attr = self.base_variant_id.product_template_attribute_value_ids[0]
            if attr:
                attr_name = str(attr.name).lower().strip()
                # Remove variant code if present (e.g., "accent base/e/b3" → "accent base")
                if '/' in attr_name:
                    attr_name = attr_name.split('/')[0].strip()
                base_attribute_name = attr_name
                
        _logger.info(f"  Base Product: {self.base_variant_id.display_name}")
        _logger.info(f"  Category: {base_category.name} (ID: {base_category.id})")
        _logger.info(f"  UOM: {base_uom.name} (ID: {base_uom.id})")
        _logger.info(f"  Attribute: {base_attribute_name if base_attribute_name else 'None'}")
        _logger.info(f"  Colour Code: {self.colour_code_id.code}")
        _logger.info(f"  Available formulas for this colour: {self.available_formulas}")
        
        # Search for formula using attribute NAME (not ID) for cross-brand matching
        matching_formula = self.colour_code_id.get_formula(
            base_category.id,
            base_uom.id,
            base_attribute_name
        )
        
        if matching_formula:
            _logger.info(f"  ✅ FORMULA FOUND: {matching_formula.name}")
            _logger.info(f"  Formula ID: {matching_formula.id}")
            _logger.info(f"  Formula contains {len(matching_formula.formula_line_ids)} colorant lines")
            _logger.info(f"  Total shots in formula: {matching_formula.total_shots}")
            return self._apply_formula(matching_formula)
        else:
            _logger.info(f"  ❌ NO MATCHING FORMULA FOUND")
            _logger.info(f"  Available formulas for {self.colour_code_id.code}: {self.available_formulas}")
            if self.available_formulas > 0:
                _logger.info(f"  💡 Other formula variants exist for this colour (different category/UOM)")
            self._clear_formula_shots()
        
        _logger.info("=" * 80)

    def _apply_formula(self, formula):
        """
        Apply formula shots to wizard colorant lines
        Updates wizard line shots based on saved formula
        """
        self.ensure_one()
        
        _logger.info("🎨 APPLYING FORMULA TO WIZARD...")
        _logger.info(f"  Formula: {formula.name}")
        
        # Build dict of shots: {colorant_code: shots}
        formula_shots = formula.get_shots_dict()
        
        _logger.info(f"  Formula contains {len(formula_shots)} colorants with shots:")
        for code, shots in formula_shots.items():
            _logger.info(f"    {code}: {shots} shots")
        
        # Apply to wizard lines
        applied_count = 0
        for wizard_line in self.colorant_line_ids:
            colorant_code = wizard_line.colorant_code
            
            if colorant_code in formula_shots:
                shots = formula_shots[colorant_code]
                wizard_line.shots = shots
                applied_count += 1
                _logger.info(f"    ✓ Applied {colorant_code}: {shots} shots")
            else:
                wizard_line.shots = 0.0
        
        # Set formula reference
        self.formula_id = formula
        self.formula_applied = True
        
        # Update usage counter
        formula.increment_usage_counter()
        
        _logger.info(f"  ✅ FORMULA APPLIED SUCCESSFULLY")
        _logger.info(f"  Applied {applied_count} colorant values")
        _logger.info(f"  You can still manually adjust shots if needed")
        
        # Show success notification
        return {
            'warning': {
                'title': '✓ Formula Applied!',
                'message': f'Loaded formula: {formula.name}\n'
                          f'Applied {applied_count} colorant shots.\n\n'
                          f'Formula has been used {formula.times_used} times.\n'
                          f'You can still manually adjust shots if needed.'
            }
        }

    def _clear_formula_shots(self):
        """
        Clear all shots when no formula found
        Resets wizard to manual entry mode
        """
        self.ensure_one()
        
        _logger.info("🔄 CLEARING FORMULA - Manual entry required")
        
        for wizard_line in self.colorant_line_ids:
            wizard_line.shots = 0.0
        
        self.formula_id = False
        self.formula_applied = False
        
        _logger.info("  ✅ All shots cleared - Ready for manual input")

    def action_view_available_formulas(self):
        """
        Show available formula variants for this colour
        Opens popup showing all formulas for selected colour code
        """
        self.ensure_one()
        
        if not self.colour_code_id:
            _logger.warning("⚠ No colour code selected - cannot view formulas")
            return
        
        _logger.info(f"📋 Opening available formulas for colour: {self.colour_code_id.code}")
        
        return {
            'type': 'ir.actions.act_window',
            'name': f'Available Formulas for {self.colour_code_id.code}',
            'res_model': 'tinting.formula',
            'view_mode': 'tree,form',
            'domain': [('colour_code_id', '=', self.colour_code_id.id)],
            'context': {
                'default_colour_code_id': self.colour_code_id.id,
                'search_default_active': 1,
            },
            'target': 'new',
        }

    def action_clear_formula(self):
        """
        Manually clear applied formula
        Button action to reset wizard and allow manual entry
        """
        self.ensure_one()
        _logger.info("🎯 User manually cleared formula")
        self._clear_formula_shots()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
    # ============================================================
    # END NEW FORMULA METHODS
    # ============================================================


    def action_create_tinted_product(self):
        """Main method: Create tinted product, BOM, and Manufacturing Order"""
        _logger.info("🚀 action_create_tinted_product() - Starting product creation process")
        self.ensure_one()
        
        # STEP 1: Validation checks
        _logger.info("📋 STEP 1: Validating inputs...")
        if not all([self.base_variant_id, self.fandeck_id, self.colour_code_id]):
            _logger.error("❌ Validation failed: Missing base product, fandeck, or colour code")
            raise ValidationError(_("Please select Base, Fandeck and Colour Code."))

        active = self.colorant_line_ids.filtered('shots')
        if not active:
            _logger.error("❌ Validation failed: No colorant shots entered")
            raise ValidationError(_("Please enter at least one colorant shot.\nCheck your LargoTint machine for the formula."))

        if active.filtered(lambda l: not l.colorant_id):
            _logger.error("❌ Validation failed: Unmapped colorants detected")
            raise ValidationError(_("Some used colorants are not mapped.\nPlease map all C1–C16 first."))

        if self.colour_code_id.fandeck_id != self.fandeck_id:
            _logger.error("❌ Validation failed: Colour code doesn't belong to selected fandeck")
            raise ValidationError(_("Colour code does not belong to selected fandeck."))

        # STEP 2: Check for existing product
        _logger.info("📋 STEP 2: Checking for existing product...")
        
        # UPDATED: Option 3 - Include colour name with code in brackets
        clean_product_name = f"{self.base_variant_id.display_name} – {self.colour_name} [{self.colour_code_id.code}]".strip()
        _logger.info(f"  Generated product name: '{clean_product_name}'")
        
        if self.env['product.template'].search([('name', '=', clean_product_name), ('is_tinted_product', '=', True)], limit=1):
            _logger.error(f"❌ Product already exists: {clean_product_name}")
            raise ValidationError(_("This tinted product already exists."))

        uom = self.base_variant_id.uom_id
        _logger.info(f"  Using UoM: {uom.name}")
        
        # STEP 3: Get or create Tinted Paint category
        _logger.info("📋 STEP 3: Setting up product category...")
        categ = self.env['product.category'].search([('name', '=', 'Tinted Paint')], limit=1)
        if not categ:
            # Create category with storable product configuration
            categ = self.env['product.category'].create({
                'name': 'Tinted Paint',
                'property_cost_method': 'fifo',  # or 'standard' based on your needs
                'property_valuation': 'real_time',
            })
            _logger.info(f"✅ Created Tinted Paint category with ID: {categ.id}")
        else:
            _logger.info(f"✅ Using existing Tinted Paint category: {categ.id}")

        # STEP 4: Debug product types available
        _logger.info("📋 STEP 4: Checking product type configuration...")
        product_type_field = self.env['product.template']._fields.get('type')
        if product_type_field:
            available_types = product_type_field.get_values(self.env)
            _logger.info(f"  Available product types: {available_types}")
        else:
            available_types = []
            _logger.warning("⚠ No 'type' field found in product.template")
        
        # Check what type the base product uses
        base_type = getattr(self.base_variant_id, 'type', 'consu')
        _logger.info(f"  Base product type: {base_type}")

        # STEP 5: Create product with DEBUG for product type issues
        _logger.info("📋 STEP 5: Creating product template...")
        
        # DEBUG: Check context and type validation
        _logger.info("🔍 DEBUG: Product Type Analysis")
        _logger.info(f"  Available types: {available_types}")
        _logger.info(f"  Base type: {base_type}")
        _logger.info(f"  Current context: {self.env.context}")
        _logger.info(f"  Has 'product' in available types: {'product' in available_types}")
        _logger.info(f"  Has 'stockable' in available types: {'stockable' in available_types}")
        
        # NUCLEAR FIX: Create product with context to skip ALL auto-naming
        product_vals = {
            'name': clean_product_name,  # Use our clean name
            'base_product_name': clean_product_name,  # Set same as name to prevent auto-naming
            'categ_id': categ.id,
            'uom_id': uom.id,
            'uom_po_id': uom.id,
            'standard_price': self.total_cost_excl_vat,
            'list_price': self.total_cost_incl_vat * 1.3,
            'is_tinted_product': True,
            'fandeck_id': self.fandeck_id.id,
            'colour_code_id': self.colour_code_id.id,
            'sale_ok': True,
            'purchase_ok': True,
            'tracking': 'lot',  # Lot tracking for inventory
            'description': f"Tinted paint: {self.base_variant_id.display_name} with {self.colour_code_id.code}",
            'default_code': f"TINT-{self.colour_code_id.code}-{fields.Datetime.now().strftime('%Y%m%d')}",
        }

        _logger.info(f"  Product values prepared, creating product template...")
        
        # DEBUG: Test product creation with detailed logging
        _logger.info("🔍 DEBUG: Testing product creation approaches...")
        
        # FIX 2: Create product with context to disable auto-naming
        try:
            # Approach A: Try 'product' type (standard Odoo)
            product_vals['type'] = 'product'
            _logger.info("  Attempting creation with type: 'product'")
            tmpl = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
            _logger.info("✅ Created product with type: 'product'")
        except ValueError as e:
            _logger.warning(f"❌ Type 'product' failed: {e}")
            try:
                # Approach B: Try 'stockable' type (some custom modules)
                product_vals['type'] = 'stockable'
                _logger.info("  Attempting creation with type: 'stockable'")
                tmpl = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                _logger.info("✅ Created product with type: 'stockable'")
            except ValueError as e2:
                _logger.warning(f"❌ Type 'stockable' failed: {e2}")
                try:
                    # Approach C: Use same type as base product
                    product_vals['type'] = base_type
                    _logger.info(f"  Attempting creation with base product type: '{base_type}'")
                    tmpl = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                    _logger.info(f"✅ Created product with base product type: '{base_type}'")
                except Exception as e3:
                    _logger.error(f"❌ All type approaches failed: {e3}")
                    # Approach D: Create without type and force update
                    del product_vals['type']
                    _logger.info("  Attempting creation without type specification")
                    tmpl = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                    _logger.warning("⚠ Created product without type specification")

        # DEBUG: Verify what type we ended up with
        _logger.info("🔍 DEBUG: Product creation result")
        if hasattr(tmpl, 'type'):
            current_type = tmpl.type
            _logger.info(f"  Product created with type: '{current_type}'")
            
            # If not storable, try to update it
            if current_type != 'product':
                _logger.warning(f"⚠ Product type is '{current_type}', not 'product'. Attempting to update...")
                try:
                    tmpl.write({'type': 'product'})
                    _logger.info("✅ Updated product type to 'product'")
                except Exception as e:
                    _logger.error(f"❌ Failed to update to 'product': {e}")
                    try:
                        tmpl.write({'type': 'stockable'})
                        _logger.info("✅ Updated product type to 'stockable'")
                    except Exception as e2:
                        _logger.error(f"❌ Failed to update to 'stockable': {e2}")
                        _logger.warning("⚠ Could not update product type to storable")
        else:
            _logger.warning("⚠ Product template has no 'type' field")

        # STEP 6: Set up inventory configuration
        _logger.info("📋 STEP 6: Configuring inventory and routes...")
        _logger.info(f"  Product tracking: {getattr(tmpl, 'tracking', 'Not set')}")
        _logger.info(f"  Product category: {tmpl.categ_id.name}")

        # Set up manufacturing route
        try:
            manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture')
            if manufacture_route:
                tmpl.write({
                    'route_ids': [(4, manufacture_route.id)]  # Add manufacturing route
                })
                _logger.info("✅ Added manufacturing route to product")
        except Exception as e:
            _logger.warning(f"⚠ Could not set manufacturing route: {e}")

        # Try to set purchase route if available
        try:
            purchase_route = self.env.ref('purchase_stock.route_warehouse0_buy')
            if purchase_route:
                tmpl.write({
                    'route_ids': [(4, purchase_route.id)]  # Add purchase route
                })
                _logger.info("✅ Added purchase route to product")
        except Exception as e:
            _logger.warning(f"⚠ Could not set purchase route: {e}")

        # STEP 7: Create BOM with exact quantities
        _logger.info("📋 STEP 7: Creating Bill of Materials...")
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': tmpl.id,
            'product_qty': 1.0,
            'product_uom_id': uom.id,
            'type': 'normal',
            'is_tinting_bom': True,
            'fandeck_id': self.fandeck_id.id,
            'colour_code_id': self.colour_code_id.id,
            'base_variant_id': self.base_variant_id.id,
            'tinting_notes': self.notes or '',
        })
        _logger.info(f"✅ Created BOM ID: {bom.id}")

        # Base product line - with cost tracking
        _logger.info("  Adding base product line to BOM...")
        self.env['mrp.bom.line'].create({
            'bom_id': bom.id,
            'product_id': self.base_variant_id.id,
            'product_qty': 1.0,
            'product_uom_id': uom.id,
            'unit_cost_excl_vat': self.base_variant_id.standard_price,  # Set cost
        })

        # Colorant lines - CRITICAL: Use exact quantities with cost tracking
        _logger.info("  Adding colorant lines to BOM...")
        for line in active:
            bom_line_vals = {
                'bom_id': bom.id,
                'product_id': line.colorant_id.id,
                'product_qty': line.qty_litres,  # Exact quantity from wizard (0.006160 L)
                'product_uom_id': line.colorant_id.uom_id.id,  # Use colorant's UoM
                'is_colorant_line': True,
                'colorant_shots': line.shots,
                'unit_cost_excl_vat': line.colorant_id.standard_price,  # Set cost
            }
            
            # Create the BOM line
            bom_line = self.env['mrp.bom.line'].create(bom_line_vals)
            _logger.info(f"    Added {line.colorant_code}: {line.shots} shots = {line.qty_litres}L")
            
            # Force recompute of computed fields
            bom_line._compute_colorant_ml()
            bom_line._compute_unit_cost_incl_vat()
            bom_line._compute_line_costs()

        # STEP 8: Create Manufacturing Order
        _logger.info("📋 STEP 8: Creating Manufacturing Order...")
        mo = self.env['mrp.production'].create({
            'product_id': tmpl.product_variant_id.id,
            'bom_id': bom.id,
            'product_qty': 1.0,
            'product_uom_id': uom.id,
            'origin': f"Tint: {self.colour_code_id.code}",
            'is_tinting_mo': True,
        })
        _logger.info(f"✅ Created MO ID: {mo.id}")
        mo.action_confirm()
        _logger.info("✅ MO confirmed")
        
        # CRITICAL: Force exact quantities in MO moves to match BOM
        _logger.info("  Setting exact quantities in MO moves...")
        for move in mo.move_raw_ids:
            # Find the corresponding BOM line
            bom_line = move.bom_line_id
            if bom_line and bom_line.is_colorant_line:
                # Set exact quantity from BOM without rounding
                exact_qty = bom_line.product_qty
                move.write({
                    'product_uom_qty': exact_qty,
                    'quantity': exact_qty,
                })
                _logger.info(f"    MO Move: {move.product_id.name} - Set exact quantity: {exact_qty} {move.product_uom.name}")
        
        # Update product costs based on BOM totals
        tmpl.write({
            'standard_price': bom.total_cost_excl_vat,
            'cost_price_excl_vat': bom.total_cost_excl_vat,
        })
        _logger.info("✅ Updated product costs from BOM")

        # STEP 9: Final verification and logging
        _logger.info("📋 STEP 9: Final verification...")
        _logger.info("🎉 === PRODUCT CREATION SUMMARY ===")
        _logger.info(f"  Product: {tmpl.name}")
        _logger.info(f"  Type: {getattr(tmpl, 'type', 'Unknown')}")
        _logger.info(f"  Tracking: {getattr(tmpl, 'tracking', 'Unknown')}")
        _logger.info(f"  Category: {tmpl.categ_id.name}")
        _logger.info(f"  Sale OK: {tmpl.sale_ok}")
        _logger.info(f"  Purchase OK: {tmpl.purchase_ok}")
        _logger.info(f"  Routes: {tmpl.route_ids.mapped('name')}")
        _logger.info(f"  BOM Lines: {len(bom.bom_line_ids)}")
        _logger.info(f"  MO Created: {mo.name}")
        _logger.info("🎉 === CREATION PROCESS COMPLETED ===")

        # Return to the created Manufacturing Order
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tinted Paint',
            'res_model': 'mrp.production',
            'res_id': mo.id,
            'view_mode': 'form',
            'target': 'current',
        }