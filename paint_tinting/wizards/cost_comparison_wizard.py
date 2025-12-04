# -*- coding: utf-8 -*-
"""
Cost Comparison Wizard Module
==============================

Allows users to compare costs across different paint brands using the same colorant formula.

Key Features:
- Finds similar products (same category, UOM, and attribute)
- Applies same colorant formula to all products
- Shows cost breakdown, profit, and margin for each brand
- Allows inline price editing to see profit/margin changes
- "Use This" button to switch base product in parent tint wizard

Author: ATIQ - Crown Kenya PLC / Mzaramo Paints & Wallpaper
Date: 2024
Odoo Version: 18 Enterprise

FINAL SOLUTION: Lines created in create() method after wizard exists
"""

import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CostComparisonLine(models.TransientModel):
    """
    Individual product comparison line in the cost comparison wizard.
    
    Each line represents one product variant with:
    - Cost breakdown (base + colorants)
    - Editable selling price
    - Auto-calculated profit and margin
    """
    _name = 'cost.comparison.line'
    _description = 'Cost Comparison Line'
    _order = 'total_cost_incl_vat'
    
    # ============================================
    # RELATIONSHIP FIELDS
    # ============================================
    wizard_id = fields.Many2one(
        'cost.comparison.wizard',
        string='Comparison Wizard',
        required=True,
        ondelete='cascade',
        help='Parent comparison wizard'
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=False,  # ✅ NOT required at field level (avoids constraint issues)
        help='Product variant being compared'
    )
    
    # ============================================
    # COMPUTED FIELDS - NO store=True
    # ============================================
    brand_name = fields.Char(
        string='Brand',
        compute='_compute_brand_name',
        help='Brand name extracted from product name'
    )
    
    # ============================================
    # STATUS FIELDS
    # ============================================
    is_current_product = fields.Boolean(
        string='Is Current Product',
        default=False,
        help='Indicates if this is the currently selected product in parent wizard'
    )
    
    # ============================================
    # COST FIELDS
    # ============================================
    base_cost_incl_vat = fields.Float(
        string='Base Cost (Incl. VAT)',
        digits=(16, 2),
        help='Base product cost including 16% VAT'
    )
    
    colorant_cost_incl_vat = fields.Float(
        string='Colorant Cost (Incl. VAT)',
        digits=(16, 2),
        help='Total colorant cost including 16% VAT (same formula for all products)'
    )
    
    total_cost_incl_vat = fields.Float(
        string='Total Cost (Incl. VAT)',
        digits=(16, 2),
        help='Base + Colorant cost including VAT'
    )
    
    # ============================================
    # PRICING FIELDS - EDITABLE BY USER
    # ============================================
    selling_price_incl_vat = fields.Float(
        string='Selling Price (Incl. VAT)',
        digits=(16, 2),
        help='Edit this to see how profit/margin changes'
    )
    
    # ============================================
    # PROFIT FIELDS - COMPUTED FROM PRICING
    # ============================================
    profit_amount_incl_vat = fields.Float(
        string='Profit (Incl. VAT)',
        compute='_compute_profit',
        store=True,
        digits=(16, 2),
        help='Selling Price - Total Cost'
    )
    
    profit_margin_percent = fields.Float(
        string='Profit Margin %',
        compute='_compute_profit',
        store=True,
        digits=(16, 2),
        help='(Profit / Selling Price) × 100'
    )
    
    # ============================================
    # COMPUTE METHODS
    # ============================================
    @api.depends('product_id')
    def _compute_brand_name(self):
        """
        Extract brand name from product name or brand_id field.
        
        Extraction Logic:
        1. Try product.brand_id (if product_brand module installed)
        2. Fallback: Search for known brand names in product name
        3. Extract first word after size (4ltr, 20ltr, etc.)
        
        Examples:
            "4ltr Crown Silk Vinyl" → "Crown"
            "4ltr Gamma Silk Vinyl" → "Gamma"
            "4ltr Plascon Vinyl Silk" → "Plascon"
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: Brand names for comparison lines")
        _logger.info("=" * 80)
        
        for line in self:
            if not line.product_id:
                line.brand_name = 'Unknown'
                _logger.debug("  No product set, brand = 'Unknown'")
                continue
            
            _logger.debug(f"  Processing product: {line.product_id.display_name}")
            
            # STEP 1: Try brand_id field (if product_brand module is installed)
            try:
                if hasattr(line.product_id.product_tmpl_id, 'brand_id') and \
                   line.product_id.product_tmpl_id.brand_id:
                    line.brand_name = line.product_id.product_tmpl_id.brand_id.name
                    _logger.debug(f"    ✅ Brand from brand_id: {line.brand_name}")
                    continue
            except AttributeError:
                _logger.debug("    product_brand module not installed, using fallback extraction")
            
            # STEP 2: Extract brand from product name
            product_name = line.product_id.display_name or ''
            _logger.debug(f"    Extracting brand from: {product_name}")
            
            # Known brand names to search for
            known_brands = [
                'crown', 'gamma', 'plascon', 'dulux', 'robbialac', 
                'sadolin', 'basco', 'royal', 'maroo', 'neuce', 'neucesilk'
            ]
            
            # Search for brand in product name (case-insensitive)
            name_lower = product_name.lower()
            brand_found = False
            
            for brand in known_brands:
                if brand in name_lower:
                    # Extract the brand and capitalize properly
                    line.brand_name = brand.capitalize()
                    _logger.debug(f"    ✅ Matched known brand: {line.brand_name}")
                    brand_found = True
                    break
            
            if not brand_found:
                # STEP 3: Try to extract first word after size
                # "4ltr Crown Silk" → "Crown"
                parts = product_name.split()
                if len(parts) >= 2:
                    # Skip size indicators (4ltr, 20ltr, etc.)
                    for part in parts:
                        # Skip if contains digit or is size unit
                        if not any(char.isdigit() for char in part.lower()) and \
                           part.lower() not in ['ltr', 'litre', 'l']:
                            line.brand_name = part.capitalize()
                            _logger.debug(f"    ✅ Extracted from name: {line.brand_name}")
                            brand_found = True
                            break
                
                if not brand_found:
                    line.brand_name = 'Unknown'
                    _logger.warning(f"    ⚠️ Could not extract brand, using 'Unknown'")
        
        _logger.info("=" * 80)
    
    @api.depends('selling_price_incl_vat', 'total_cost_incl_vat')
    def _compute_profit(self):
        """
        Calculate profit and margin when selling price changes.
        
        Formulas:
            Profit = Selling Price - Total Cost
            Margin = (Profit / Selling Price) × 100
        
        Example:
            Selling Price = 3,500 KES
            Total Cost = 2,800 KES
            Profit = 700 KES
            Margin = (700 / 3,500) × 100 = 20%
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: Profit for comparison lines")
        _logger.info("=" * 80)
        
        for line in self:
            _logger.debug(f"  Processing: {line.brand_name or 'Unknown'}")
            
            if line.selling_price_incl_vat and line.total_cost_incl_vat:
                # Calculate profit
                line.profit_amount_incl_vat = line.selling_price_incl_vat - line.total_cost_incl_vat
                
                # Calculate margin percentage
                if line.selling_price_incl_vat > 0:
                    line.profit_margin_percent = (
                        line.profit_amount_incl_vat / line.selling_price_incl_vat
                    ) * 100
                else:
                    line.profit_margin_percent = 0.0
                
                _logger.debug(
                    f"    {line.brand_name}: "
                    f"Selling={line.selling_price_incl_vat:.2f} KES, "
                    f"Cost={line.total_cost_incl_vat:.2f} KES, "
                    f"Profit={line.profit_amount_incl_vat:.2f} KES ({line.profit_margin_percent:.2f}%)"
                )
            else:
                line.profit_amount_incl_vat = 0.0
                line.profit_margin_percent = 0.0
                _logger.debug(f"    {line.brand_name}: No price/cost set, profit=0")
        
        _logger.info("=" * 80)
    
    # ============================================
    # ACTION METHODS
    # ============================================
    def action_use_this_product(self):
        """
        Switch the parent tint wizard to use this product as the base.
        
        Process:
        1. Update parent wizard's base_variant_id
        2. Update parent wizard's selling_price_incl_vat
        3. Close comparison wizard
        4. Reopen parent wizard to show updated values
        
        Business Logic:
        - User can compare multiple brands with same colorant formula
        - Click "Use This" to switch to different brand
        - Colorant shots are preserved
        - Only base product and selling price are updated
        """
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("🎯 ACTION: Use This Product")
        _logger.info("=" * 80)
        _logger.info(f"  Selected product: {self.product_id.display_name}")
        _logger.info(f"  Product ID: {self.product_id.id}")
        _logger.info(f"  Brand: {self.brand_name}")
        _logger.info(f"  New base cost: {self.base_cost_incl_vat:.2f} KES")
        _logger.info(f"  New total cost: {self.total_cost_incl_vat:.2f} KES")
        _logger.info(f"  Suggested selling price: {self.selling_price_incl_vat:.2f} KES")
        
        # Get parent wizard
        parent_wizard = self.wizard_id.parent_wizard_id
        if not parent_wizard:
            _logger.error("❌ ERROR: Parent tint wizard not found!")
            raise UserError("Parent tint wizard not found!")
        
        _logger.info(f"  Parent wizard ID: {parent_wizard.id}")
        _logger.info(f"  Old base product: {parent_wizard.base_variant_id.display_name}")
        _logger.info(f"  Old selling price: {parent_wizard.selling_price_incl_vat:.2f} KES")
        
        # Update parent wizard's base product and selling price
        parent_wizard.write({
            'base_variant_id': self.product_id.id,
            'selling_price_incl_vat': self.selling_price_incl_vat,
        })
        
        _logger.info(f"  ✅ SUCCESS: Parent wizard updated")
        _logger.info(f"  New base product: {parent_wizard.base_variant_id.display_name}")
        _logger.info(f"  New selling price: {parent_wizard.selling_price_incl_vat:.2f} KES")
        _logger.info(f"  💡 Note: Colorant shots have been preserved")
        _logger.info(f"  💡 Note: Costs will auto-recalculate based on new base")
        _logger.info("=" * 80)
        
        # ============================================
        # CRITICAL FIX: Reopen parent wizard to show updates
        # ============================================
        return {
            'type': 'ir.actions.act_window',
            'name': 'Paint Tinting Wizard',
            'res_model': 'tint.wizard',
            'res_id': parent_wizard.id,
            'view_mode': 'form',
            'target': 'new',  # Keep as popup
            'context': self.env.context,
        }
class CostComparisonWizard(models.TransientModel):
    """
    Main cost comparison wizard for comparing paint products across different brands.
    
    Features:
    - Searches for similar products (same category, UOM, attribute)
    - Applies same colorant formula from parent wizard
    - Calculates costs for each product
    - Shows profit/margin analysis
    - Allows inline price editing
    - Statistics summary (avg cost, lowest cost, highest profit)
    
    Usage Flow:
    1. User opens tint wizard, selects base product and enters colorant shots
    2. User clicks "Compare Costs Across Brands" button
    3. This wizard opens, showing all similar products with same colorant formula
    4. User can edit prices, see profit/margin changes
    5. User clicks "Use This" to switch to different brand
    
    FINAL SOLUTION: Lines created in create() method after wizard exists
    """
    _name = 'cost.comparison.wizard'
    _description = 'Cost Comparison Wizard'
    
    # ============================================
    # RELATIONSHIP FIELDS
    # ============================================
    parent_wizard_id = fields.Many2one(
        'tint.wizard',
        string='Parent Tint Wizard',
        required=True,
        ondelete='cascade',
        help='Reference to the tint wizard that opened this comparison'
    )
    
    # ============================================
    # COMPARISON CRITERIA
    # ============================================
    base_category_id = fields.Many2one(
        'product.category',
        string='Category',
        readonly=True,
        help='Product category (e.g., Vinyl Silk, Matt Emulsion)'
    )
    
    base_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        readonly=True,
        help='Unit of measure (e.g., 4ltr, 20ltr)'
    )
    
    base_attribute_name = fields.Char(
        string='Attribute',
        readonly=True,
        help='Normalized attribute name (e.g., "Deep Base", "Medium Base")'
    )
    
    # ============================================
    # COLORANT FORMULA - STORED AS JSON
    # ============================================
    colorant_shots_json = fields.Text(
        string='Colorant Shots (JSON)',
        help='Stored colorant shots from parent wizard for cost calculations'
    )
    
    # ============================================
    # COMPARISON LINES - One2many RELATIONSHIP
    # ============================================
    comparison_line_ids = fields.One2many(
        'cost.comparison.line',
        'wizard_id',
        string='Product Comparisons',
        help='List of similar products with cost/profit analysis'
    )
    
    # ============================================
    # STATISTICS - COMPUTED FIELDS (NO store=True)
    # ============================================
    total_products = fields.Integer(
        string='Total Products',
        compute='_compute_statistics',
        help='Number of similar products found'
    )
    
    avg_cost = fields.Float(
        string='Average Cost',
        compute='_compute_statistics',
        digits=(16, 2),
        help='Average total cost across all products'
    )
    
    lowest_cost = fields.Float(
        string='Lowest Cost',
        compute='_compute_statistics',
        digits=(16, 2),
        help='Cheapest product cost (highlighted in green in list)'
    )
    
    highest_profit = fields.Float(
        string='Highest Profit',
        compute='_compute_statistics',
        digits=(16, 2),
        help='Maximum profit achievable'
    )
    
    # ============================================
    # DEFAULT VALUES - STORE CONFIG ONLY
    # ============================================
    @api.model
    def default_get(self, fields_list):
        """
        Initialize wizard with configuration data from parent tint wizard.
        
        FINAL SOLUTION: Only stores configuration data (NO line creation).
        Lines are created in create() method after wizard exists.
        
        Process:
        1. Get parent tint wizard from context
        2. Extract base product details (category, UOM, attribute)
        3. Extract colorant shots from parent wizard and store as JSON
        4. Return configuration data (wizard creation happens next)
        
        Returns:
            dict: Default field values (NO comparison_line_ids)
        """
        _logger.info("=" * 80)
        _logger.info("🚀 DEFAULT_GET: Cost Comparison Wizard")
        _logger.info("=" * 80)
        
        res = super(CostComparisonWizard, self).default_get(fields_list)
        
        # ============================================
        # STEP 1: GET PARENT WIZARD
        # ============================================
        _logger.info("📋 STEP 1: Getting parent wizard from context")
        
        parent_wizard_id = self.env.context.get('default_parent_wizard_id') or \
                          self.env.context.get('parent_wizard_id')
        
        if not parent_wizard_id:
            _logger.error("❌ ERROR: No parent wizard specified in context!")
            raise UserError("No parent wizard specified in context!")
        
        _logger.info(f"  ✅ Parent wizard ID: {parent_wizard_id}")
        
        parent_wizard = self.env['tint.wizard'].browse(parent_wizard_id)
        if not parent_wizard.exists():
            _logger.error("❌ ERROR: Parent tint wizard not found!")
            raise UserError("Parent tint wizard not found!")
        
        # Store parent wizard reference
        res['parent_wizard_id'] = parent_wizard.id
        _logger.info(f"  ✅ Parent wizard reference stored")
        
        # ============================================
        # STEP 2: GET BASE PRODUCT DETAILS
        # ============================================
        _logger.info("📋 STEP 2: Extracting base product details")
        
        base_product = parent_wizard.base_variant_id
        if not base_product:
            _logger.error("❌ ERROR: No base product selected in parent wizard!")
            raise UserError("No base product selected in parent wizard!")
        
        _logger.info(f"  Base product: {base_product.display_name}")
        _logger.info(f"  Category: {base_product.categ_id.name} (ID: {base_product.categ_id.id})")
        _logger.info(f"  UOM: {base_product.uom_id.name} (ID: {base_product.uom_id.id})")
        
        # Store comparison criteria
        res['base_category_id'] = base_product.categ_id.id
        res['base_uom_id'] = base_product.uom_id.id
        
        # Extract normalized attribute name (strip variant codes like W2/B2)
        attribute_name = self._extract_attribute_name(base_product)
        res['base_attribute_name'] = attribute_name
        _logger.info(f"  Attribute: {attribute_name}")
        _logger.info(f"  ✅ Comparison criteria stored")
        
        # ============================================
        # STEP 3: STORE COLORANT SHOTS AS JSON
        # ============================================
        _logger.info("📋 STEP 3: Extracting colorant shots from parent")
        
        colorant_shots = {}
        for line in parent_wizard.colorant_line_ids:
            if line.shots > 0:
                colorant_shots[line.colorant_code] = {
                    'shots': line.shots,
                    'unit_cost_excl_vat': line.unit_cost_excl_vat or 0.0
                }
        
        res['colorant_shots_json'] = json.dumps(colorant_shots)
        _logger.info(f"  Colorant shots extracted: {len(colorant_shots)} colorants with shots")
        
        # Log colorant details
        if colorant_shots:
            _logger.info("  Colorant breakdown:")
            for code, data in colorant_shots.items():
                _logger.info(f"    {code}: {data['shots']} shots @ {data['unit_cost_excl_vat']:.2f} KES/L")
        else:
            _logger.warning("  ⚠️ No colorant shots found in parent wizard")
        
        _logger.info(f"  ✅ Colorant data stored as JSON")
        
        # ============================================
        # FINAL: RETURN CONFIG (NO LINES YET)
        # ============================================
        _logger.info("=" * 80)
        _logger.info("💡 FINAL SOLUTION: Config stored - lines will be created in create()")
        _logger.info("=" * 80)
        
        return res
    
    # ============================================
    # CREATE METHOD - LINE CREATION HAPPENS HERE
    # ============================================
    @api.model_create_multi
    def create(self, vals_list):
        """
        Create wizard and populate comparison lines.
        
        FINAL SOLUTION: This is where comparison lines are created.
        Wizard must exist first, then we create child line records.
        
        Process:
        1. Create wizard record (parent exists first)
        2. Call _populate_comparison_lines() to create child records
        3. Child records can now reference valid parent wizard_id
        
        Returns:
            recordset: Created wizard(s)
        """
        _logger.info("=" * 80)
        _logger.info("🚀 CREATE: Cost Comparison Wizard")
        _logger.info("=" * 80)
        
        # STEP 1: Create wizard record first
        _logger.info("📋 STEP 1: Creating wizard record...")
        wizards = super().create(vals_list)
        _logger.info(f"  ✅ Wizard record created: {len(wizards)} wizard(s)")
        
        # STEP 2: Populate comparison lines for each wizard
        _logger.info("📋 STEP 2: Populating comparison lines...")
        for wizard in wizards:
            _logger.info(f"  Processing wizard ID: {wizard.id}")
            try:
                wizard._populate_comparison_lines()
                _logger.info(f"  ✅ Comparison lines populated: {len(wizard.comparison_line_ids)} lines created")
            except Exception as e:
                _logger.error(f"  ❌ ERROR populating lines for wizard {wizard.id}: {str(e)}")
                raise
        
        _logger.info("=" * 80)
        _logger.info("✅ SUCCESS: Cost Comparison Wizard creation completed")
        _logger.info("=" * 80)
        
        return wizards
    
    # ============================================
    # POPULATE COMPARISON LINES - CORE METHOD
    # ============================================
    def _populate_comparison_lines(self):
        """
        Populate comparison lines after wizard creation.
        
        FINAL SOLUTION: This method creates comparison line records.
        Called from create() after wizard exists with valid ID.
        
        Process:
        1. Parse colorant shots from JSON
        2. Search for similar products (same category/UOM/attribute)
        3. Calculate costs for each product using colorant formula
        4. Create comparison line records directly
        """
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("🔍 POPULATE COMPARISON LINES")
        _logger.info("=" * 80)
        _logger.info(f"  Wizard ID: {self.id}")
        _logger.info(f"  Parent Wizard ID: {self.parent_wizard_id.id}")
        
        # ============================================
        # STEP 1: PARSE COLORANT SHOTS FROM JSON
        # ============================================
        _logger.info("📋 STEP 1: Parsing colorant shots from JSON")
        
        try:
            colorant_shots = json.loads(self.colorant_shots_json or '{}')
            _logger.info(f"  ✅ Parsed {len(colorant_shots)} colorants from JSON")
            
            if colorant_shots:
                _logger.info("  Colorant breakdown:")
                for code, data in colorant_shots.items():
                    _logger.info(f"    {code}: {data['shots']} shots @ {data['unit_cost_excl_vat']:.2f} KES/L")
        except Exception as e:
            _logger.error(f"  ❌ ERROR parsing JSON: {str(e)}")
            colorant_shots = {}
        
        # ============================================
        # STEP 2: SEARCH FOR SIMILAR PRODUCTS
        # ============================================
        _logger.info("=" * 80)
        _logger.info("🔍 STEP 2: Searching for similar products")
        _logger.info("=" * 80)
        _logger.info(f"  Search criteria:")
        _logger.info(f"    Category: {self.base_category_id.name} (ID: {self.base_category_id.id})")
        _logger.info(f"    UOM: {self.base_uom_id.name} (ID: {self.base_uom_id.id})")
        _logger.info(f"    Attribute: {self.base_attribute_name}")
        
        # Build search domain
        domain = [
            ('categ_id', '=', self.base_category_id.id),
            ('uom_id', '=', self.base_uom_id.id),
            ('product_tmpl_id.is_colorant', '=', False),  # Exclude colorants
            ('product_tmpl_id.is_tinted_product', '=', False),  # Exclude tinted products
        ]
        
        similar_products = self.env['product.product'].search(domain)
        _logger.info(f"  Found {len(similar_products)} products matching category/UOM")
        
        # Filter by normalized attribute name (for cross-brand matching)
        filtered_products = similar_products.filtered(
            lambda p: self._extract_attribute_name(p) == self.base_attribute_name
        )
        
        _logger.info(f"  ✅ Found {len(filtered_products)} similar products after attribute filter")
        
        if not filtered_products:
            _logger.warning("  ⚠️ No similar products found!")
            _logger.warning("    This could mean:")
            _logger.warning("      - No other brands have this product variant")
            _logger.warning("      - Attribute extraction failed")
            _logger.warning("      - Product naming inconsistent")
            return
        
        # ============================================
        # STEP 3: CALCULATE COSTS FOR EACH PRODUCT
        # ============================================
        _logger.info("=" * 80)
        _logger.info("💰 STEP 3: Calculating costs and creating lines")
        _logger.info("=" * 80)
        
        # Get current base product from parent wizard
        current_product_id = self.parent_wizard_id.base_variant_id.id
        _logger.info(f"  Current product ID: {current_product_id}")
        
        lines_created = 0
        
        for product in filtered_products:
            _logger.info(f"  Processing: {product.display_name} (ID: {product.id})")
            
            # Check if this is the current product
            is_current = (product.id == current_product_id)
            if is_current:
                _logger.info(f"    ⭐ This is the CURRENT product")
            
            # ============================================
            # CALCULATE BASE COST
            # ============================================
            base_cost_excl = product.standard_price or 0.0
            base_cost_incl = base_cost_excl * 1.16  # Add 16% VAT
            
            _logger.debug(f"    Base cost: {base_cost_excl:.2f} (excl) → {base_cost_incl:.2f} (incl VAT)")
            
            # ============================================
            # CALCULATE COLORANT COST
            # Same formula applied to all products
            # ============================================
            colorant_cost_excl = 0.0
            
            for colorant_code, data in colorant_shots.items():
                shots = data['shots']
                unit_cost = data['unit_cost_excl_vat']
                
                # Convert shots to litres
                ml_volume = shots * 0.616  # 1 shot = 0.616 ml
                qty_litres = ml_volume / 1000.0
                
                # Calculate cost for this colorant
                colorant_line_cost = qty_litres * unit_cost
                colorant_cost_excl += colorant_line_cost
                
                _logger.debug(
                    f"      {colorant_code}: {shots} shots = {ml_volume:.3f}ml = "
                    f"{qty_litres:.6f}L × {unit_cost:.2f} = {colorant_line_cost:.2f} KES"
                )
            
            colorant_cost_incl = colorant_cost_excl * 1.16  # Add 16% VAT
            _logger.debug(
                f"    Total colorant: {colorant_cost_excl:.2f} (excl) → "
                f"{colorant_cost_incl:.2f} (incl VAT)"
            )
            
            # ============================================
            # CALCULATE TOTAL COST
            # ============================================
            total_cost_incl = base_cost_incl + colorant_cost_incl
            _logger.debug(f"    TOTAL COST: {total_cost_incl:.2f} KES (incl VAT)")
            
            # ============================================
            # DEFAULT SELLING PRICE (30% MARKUP)
            # ============================================
            selling_price = total_cost_incl * 1.30
            profit = selling_price - total_cost_incl
            margin = (profit / selling_price * 100) if selling_price > 0 else 0
            
            _logger.debug(
                f"    Suggested pricing: {selling_price:.2f} KES "
                f"(Profit: {profit:.2f}, Margin: {margin:.2f}%)"
            )
            
            # ============================================
            # CREATE COMPARISON LINE DIRECTLY
            # FINAL SOLUTION: Direct record creation after wizard exists
            # ============================================
            try:
                line_vals = {
                    'wizard_id': self.id,  # ✅ Parent wizard exists now!
                    'product_id': product.id,  # ✅ Required field set
                    'is_current_product': is_current,
                    'base_cost_incl_vat': base_cost_incl,
                    'colorant_cost_incl_vat': colorant_cost_incl,
                    'total_cost_incl_vat': total_cost_incl,
                    'selling_price_incl_vat': selling_price,
                }
                
                _logger.debug(f"    Creating line with vals: {line_vals}")
                
                line = self.env['cost.comparison.line'].create(line_vals)
                lines_created += 1
                
                _logger.info(
                    f"    ✅ Line created (ID: {line.id}): "
                    f"Product={product.id}, Cost={total_cost_incl:.2f}, Price={selling_price:.2f}"
                )
                
            except Exception as e:
                _logger.error(f"    ❌ ERROR creating line: {str(e)}")
                _logger.error(f"       Line vals: {line_vals}")
                _logger.error(f"       Exception type: {type(e).__name__}")
                raise
        
        _logger.info("=" * 80)
        _logger.info(f"✅ SUCCESS: Created {lines_created} comparison lines")
        _logger.info(f"   Total lines in wizard: {len(self.comparison_line_ids)}")
        _logger.info("=" * 80)
    
    # ============================================
    # COMPUTE METHODS
    # ============================================
    @api.depends('comparison_line_ids.total_cost_incl_vat', 
                 'comparison_line_ids.profit_amount_incl_vat')
    def _compute_statistics(self):
        """
        Calculate statistics across all comparison lines.
        
        Statistics:
        - Total products found
        - Average cost
        - Lowest cost (best value)
        - Highest profit (best margin)
        
        Used in wizard header to give user quick overview.
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: Comparison statistics")
        _logger.info("=" * 80)
        
        for wizard in self:
            lines = wizard.comparison_line_ids
            
            wizard_id_str = str(wizard.id) if wizard.id else 'NewId'
            _logger.info(f"  Wizard ID: {wizard_id_str}")
            _logger.info(f"  Comparison lines: {len(lines)}")
            
            if lines:
                wizard.total_products = len(lines)
                wizard.avg_cost = sum(lines.mapped('total_cost_incl_vat')) / len(lines)
                wizard.lowest_cost = min(lines.mapped('total_cost_incl_vat'))
                wizard.highest_profit = max(lines.mapped('profit_amount_incl_vat'))
                
                _logger.info(f"    Total products: {wizard.total_products}")
                _logger.info(f"    Average cost: {wizard.avg_cost:.2f} KES")
                _logger.info(f"    Lowest cost: {wizard.lowest_cost:.2f} KES")
                _logger.info(f"    Highest profit: {wizard.highest_profit:.2f} KES")
            else:
                wizard.total_products = 0
                wizard.avg_cost = 0.0
                wizard.lowest_cost = 0.0
                wizard.highest_profit = 0.0
                _logger.warning(f"    ⚠️ No comparison lines found")
        
        _logger.info("=" * 80)
    
    # ============================================
    # HELPER METHODS
    # ============================================
    def _extract_attribute_name(self, product):
        """
        Extract normalized attribute name from product.
        
        Removes variant codes like W2/B2, W3/B3, etc. to enable cross-brand matching.
        
        Examples:
            Input:  "4ltr Crown Silk Vinyl Emulsion (Deep Base/W2/B2)"
            Output: "deep base"
            
            Input:  "4ltr Gamma Silk Vinyl Emulsion (Medium Base/W3/B3)"
            Output: "medium base"
        
        Args:
            product (product.product): Product record
            
        Returns:
            str: Normalized attribute name (lowercase, no variant codes)
        """
        display_name = product.display_name.lower()
        
        _logger.debug(f"  Extracting attribute from: {product.display_name}")
        
        # Extract text between first '(' and '/'
        # This gets the attribute name before variant code
        if '(' in display_name and '/' in display_name:
            start = display_name.find('(') + 1
            end = display_name.find('/', start)
            attribute = display_name[start:end].strip()
            
            _logger.debug(f"    ✅ Extracted attribute: '{attribute}'")
            return attribute
        
        _logger.debug(f"    ⚠️ Could not extract attribute, using 'unknown'")
        return 'unknown'