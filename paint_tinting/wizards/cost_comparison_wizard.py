# -*- coding: utf-8 -*-
"""
Cost Comparison Wizard Module with Volume Scaling
===================================================

Allows users to compare costs across different paint brands using the same colorant formula.
Supports volume scaling to translate formulas between different package sizes.

Key Features:
- Finds similar products (same category, UOM, and attribute)
- Applies same colorant formula to all products
- Shows cost breakdown, profit, and margin for each brand
- Allows inline price editing to see profit/margin changes
- "Use This" button to switch base product in parent tint wizard
- NEW: Volume scaling - translate formula to different package sizes
- NEW: Search products in target UOM with scaled colorant shots
- NEW: One-click update of parent wizard with scaled formula

Author: ATIQ - Crown Kenya PLC / Mzaramo Paints & Wallpaper
Date: 2024
Odoo Version: 18 Enterprise

FINAL SOLUTION: Lines created in create() method after wizard exists
Volume Scaling: Complete package translation with real product costs
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
        _logger.info(f"  Processing {len(self)} line(s)")
        
        for line in self:
            line_id_str = f"Line ID: {line.id}" if line.id else "New Line"
            _logger.debug(f"  {line_id_str}")
            
            if not line.product_id:
                line.brand_name = 'Unknown'
                _logger.debug(f"    No product set, brand = 'Unknown'")
                continue
            
            _logger.debug(f"    Processing product: {line.product_id.display_name} (ID: {line.product_id.id})")
            
            # STEP 1: Try brand_id field (if product_brand module is installed)
            try:
                if hasattr(line.product_id.product_tmpl_id, 'brand_id') and \
                   line.product_id.product_tmpl_id.brand_id:
                    line.brand_name = line.product_id.product_tmpl_id.brand_id.name
                    _logger.debug(f"      ✅ Brand from brand_id field: {line.brand_name}")
                    continue
            except AttributeError:
                _logger.debug(f"      product_brand module not installed, using fallback extraction")
            
            # STEP 2: Extract brand from product name
            product_name = line.product_id.display_name or ''
            _logger.debug(f"      Extracting brand from name: '{product_name}'")
            
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
                    _logger.debug(f"      ✅ Matched known brand: {line.brand_name}")
                    brand_found = True
                    break
            
            if not brand_found:
                # STEP 3: Try to extract first word after size
                # "4ltr Crown Silk" → "Crown"
                parts = product_name.split()
                _logger.debug(f"      No known brand found, parsing name parts: {parts}")
                
                if len(parts) >= 2:
                    # Skip size indicators (4ltr, 20ltr, etc.)
                    for part in parts:
                        # Skip if contains digit or is size unit
                        if not any(char.isdigit() for char in part.lower()) and \
                           part.lower() not in ['ltr', 'litre', 'l', 'litres']:
                            line.brand_name = part.capitalize()
                            _logger.debug(f"      ✅ Extracted from name parts: {line.brand_name}")
                            brand_found = True
                            break
                
                if not brand_found:
                    line.brand_name = 'Unknown'
                    _logger.warning(f"      ⚠️ Could not extract brand, using 'Unknown'")
        
        _logger.info("=" * 80)
        _logger.info(f"✅ Brand name computation completed for {len(self)} line(s)")
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
        _logger.info(f"  Processing {len(self)} line(s)")
        
        for line in self:
            line_id_str = f"Line ID: {line.id}" if line.id else "New Line"
            brand = line.brand_name or 'Unknown'
            _logger.debug(f"  {line_id_str} - {brand}")
            
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
                    f"    Selling Price: {line.selling_price_incl_vat:.2f} KES"
                )
                _logger.debug(
                    f"    Total Cost: {line.total_cost_incl_vat:.2f} KES"
                )
                _logger.debug(
                    f"    Profit: {line.profit_amount_incl_vat:.2f} KES ({line.profit_margin_percent:.2f}%)"
                )
            else:
                line.profit_amount_incl_vat = 0.0
                line.profit_margin_percent = 0.0
                _logger.debug(f"    No price/cost set, profit=0")
        
        _logger.info("=" * 80)
        _logger.info(f"✅ Profit computation completed for {len(self)} line(s)")
        _logger.info("=" * 80)
    
    # ============================================
    # ACTION METHODS
    # ============================================
    def action_use_this_product(self):
        """
        Switch the parent tint wizard to use this product as the base.
        ENHANCED: Now handles volume scaling - updates colorant shots if scaled.
        
        Process:
        1. Get parent wizard
        2. Disable formula auto-fill (prevent overwriting scaled shots)
        3. Update base_variant_id and selling_price_incl_vat
        4. IF SCALED: Update colorant line shots with scaled values
        5. Force recomputation of all costs
        6. Invalidate cache
        7. Reopen parent wizard to show updated values
        
        Business Logic:
        - User can compare multiple brands with same colorant formula
        - Click "Use This" to switch to different brand
        - If volume was scaled (e.g., 4L → 20L), shots are updated accordingly
        - Colorant shots are preserved if no scaling
        - Only base product and selling price are updated if no scaling
        """
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("🎯 ACTION: Use This Product")
        _logger.info("=" * 80)
        _logger.info(f"  Selected line ID: {self.id}")
        _logger.info(f"  Selected product: {self.product_id.display_name}")
        _logger.info(f"  Product ID: {self.product_id.id}")
        _logger.info(f"  Brand: {self.brand_name}")
        _logger.info(f"  Product UOM: {self.product_id.uom_id.name}")
        _logger.info(f"  Base cost: {self.base_cost_incl_vat:.2f} KES")
        _logger.info(f"  Colorant cost: {self.colorant_cost_incl_vat:.2f} KES")
        _logger.info(f"  Total cost: {self.total_cost_incl_vat:.2f} KES")
        _logger.info(f"  Suggested selling price: {self.selling_price_incl_vat:.2f} KES")
        
        # ============================================
        # STEP 1: GET PARENT WIZARD
        # ============================================
        _logger.info("📋 STEP 1: Getting parent wizard...")
        
        parent_wizard = self.wizard_id.parent_wizard_id
        if not parent_wizard.exists():
            _logger.error("❌ ERROR: Parent tint wizard not found or expired!")
            raise UserError(
                "Parent tint wizard has expired or not found!\n\n"
                "Please close this window and start over."
            )
        
        _logger.info(f"  ✅ Parent wizard found: ID {parent_wizard.id}")
        _logger.info(f"  Old base product: {parent_wizard.base_variant_id.display_name}")
        _logger.info(f"  Old base UOM: {parent_wizard.base_variant_id.uom_id.name}")
        _logger.info(f"  Old selling price: {parent_wizard.selling_price_incl_vat:.2f} KES")
        
        # ============================================
        # STEP 2: CHECK IF VOLUME SCALING WAS USED
        # ============================================
        _logger.info("📋 STEP 2: Checking for volume scaling...")
        
        is_scaled = self.wizard_id.show_scaled_products and self.wizard_id.scale_factor != 1.0
        
        if is_scaled:
            _logger.info(f"  🔄 VOLUME SCALING ACTIVE!")
            _logger.info(f"  Source UOM: {self.wizard_id.source_uom_id.name} ({self.wizard_id.source_volume_litres:.2f}L)")
            _logger.info(f"  Target UOM: {self.wizard_id.target_uom_id.name} ({self.wizard_id.target_volume_litres:.2f}L)")
            _logger.info(f"  Scale Factor: {self.wizard_id.scale_factor:.4f}×")
            _logger.info(f"  Colorant shots WILL BE SCALED")
        else:
            _logger.info(f"  ✅ No scaling - using original colorant shots")
            _logger.info(f"  Only base product and price will be updated")
        
        # ============================================
        # STEP 3: DISABLE FORMULA AUTO-FILL
        # ============================================
        _logger.info("📋 STEP 3: Disabling formula auto-fill to preserve shots...")
        
        parent_wizard.formula_applied = False
        parent_wizard.formula_id = False
        _logger.info(f"  ✅ Formula flags cleared (prevents auto-overwrite)")
        
        # ============================================
        # STEP 4: UPDATE BASE PRODUCT AND SELLING PRICE
        # ============================================
        _logger.info("📋 STEP 4: Updating base product and selling price...")
        
        try:
            parent_wizard.with_context(skip_formula_search=True).write({
                'base_variant_id': self.product_id.id,
                'selling_price_incl_vat': self.selling_price_incl_vat,
                'selling_price_manually_set': True,
            })
            _logger.info(f"  ✅ Base product updated to: {self.product_id.display_name}")
            _logger.info(f"  ✅ Selling price updated to: {self.selling_price_incl_vat:.2f} KES")
            _logger.info(f"  ✅ Price marked as manually set")
        except Exception as e:
            _logger.error(f"  ❌ ERROR updating parent wizard: {str(e)}")
            raise UserError(f"Failed to update parent wizard: {str(e)}")
        
        # ============================================
        # STEP 5: UPDATE COLORANT SHOTS IF SCALED
        # ============================================
        if is_scaled:
            _logger.info("=" * 80)
            _logger.info("📋 STEP 5: APPLYING SCALED COLORANT SHOTS")
            _logger.info("=" * 80)
            
            try:
                # Get scaled shots from comparison wizard
                scaled_shots = json.loads(self.wizard_id.scaled_colorant_shots_json or '{}')
                _logger.info(f"  Parsed {len(scaled_shots)} scaled colorant entries from JSON")
                
                if not scaled_shots:
                    _logger.warning(f"  ⚠️ No scaled shots found in JSON!")
                else:
                    _logger.info(f"  Scaled colorant shots:")
                    for code, data in scaled_shots.items():
                        _logger.info(f"    {code}: {data['shots']:.2f} shots")
                
                # Update parent wizard's colorant lines with forced recomputation
                lines_updated = 0
                for line in parent_wizard.colorant_line_ids:
                    if line.colorant_code in scaled_shots:
                        old_shots = line.shots
                        new_shots = scaled_shots[line.colorant_code]['shots']
                        
                        _logger.info(f"  Processing {line.colorant_code}...")
                        _logger.info(f"    Old shots: {old_shots:.2f}")
                        _logger.info(f"    New shots: {new_shots:.2f}")
                        _logger.info(f"    Change: {new_shots - old_shots:+.2f} shots")
                        
                        # Write new shots value
                        line.write({'shots': new_shots})
                        _logger.debug(f"    ✅ Shots written to database")
                        
                        # ✅ FORCE RECOMPUTATION (critical for UI refresh!)
                        _logger.debug(f"    🔄 Forcing field recomputation...")
                        line._compute_ml_volume()
                        line._compute_qty_litres()
                        line._compute_unit_cost_incl_vat()
                        line._compute_line_costs()
                        line._compute_available_stock()
                        line._compute_stock_warning()
                        _logger.debug(f"    ✅ All fields recomputed")
                        
                        _logger.info(f"    ✅ {line.colorant_code} updated: {old_shots:.2f} → {new_shots:.2f} shots")
                        lines_updated += 1
                
                _logger.info("=" * 80)
                _logger.info(f"✅ SCALING COMPLETE: Updated {lines_updated} colorant line(s)")
                _logger.info("=" * 80)
                
            except json.JSONDecodeError as e:
                _logger.error(f"  ❌ ERROR parsing scaled shots JSON: {str(e)}")
                raise UserError(f"Failed to parse scaled colorant shots: {str(e)}")
            except Exception as e:
                _logger.error(f"  ❌ ERROR updating colorant shots: {str(e)}")
                _logger.error(f"  Exception type: {type(e).__name__}")
                import traceback
                _logger.error(f"  Traceback:\n{traceback.format_exc()}")
                raise UserError(f"Failed to update colorant shots: {str(e)}")
        else:
            _logger.info("📋 STEP 5: Skipped (no scaling applied)")
        
        # ============================================
        # STEP 6: FORCE PARENT WIZARD RECOMPUTATION
        # ============================================
        _logger.info("=" * 80)
        _logger.info("📋 STEP 6: Forcing parent wizard recomputation...")
        _logger.info("=" * 80)
        
        try:
            _logger.debug("  Calling _compute_base_cost()...")
            parent_wizard._compute_base_cost()
            _logger.debug(f"    Base cost: {parent_wizard.base_cost_incl_vat:.2f} KES")
            
            _logger.debug("  Calling _compute_totals()...")
            parent_wizard._compute_totals()
            _logger.debug(f"    Total colorant ML: {parent_wizard.total_colorant_ml:.2f} ml")
            _logger.debug(f"    Total cost: {parent_wizard.total_cost_incl_vat:.2f} KES")
            
            _logger.debug("  Calling _compute_warnings()...")
            parent_wizard._compute_warnings()
            _logger.debug(f"    Stock warnings: {parent_wizard.has_stock_warnings}")
            
            _logger.info("  ✅ All parent wizard fields recomputed")
        except Exception as e:
            _logger.error(f"  ❌ ERROR during recomputation: {str(e)}")
            import traceback
            _logger.error(f"  Traceback:\n{traceback.format_exc()}")
            # Don't raise - allow wizard to reopen even if compute fails
        
        # ============================================
        # STEP 7: INVALIDATE CACHE AND REOPEN
        # ============================================
        _logger.info("📋 STEP 7: Invalidating cache and reopening parent wizard...")
        
        try:
            parent_wizard.invalidate_recordset()
            _logger.info("  ✅ Cache invalidated (ensures fresh data)")
        except Exception as e:
            _logger.warning(f"  ⚠️ Cache invalidation warning: {str(e)}")
        
        # ============================================
        # FINAL SUMMARY
        # ============================================
        _logger.info("=" * 80)
        _logger.info("✅ ACTION COMPLETED SUCCESSFULLY")
        _logger.info("=" * 80)
        _logger.info(f"  Final state:")
        _logger.info(f"    Base Product: {parent_wizard.base_variant_id.display_name}")
        _logger.info(f"    Base UOM: {parent_wizard.base_variant_id.uom_id.name}")
        _logger.info(f"    Base Cost: {parent_wizard.base_cost_incl_vat:.2f} KES")
        _logger.info(f"    Colorant Cost: {parent_wizard.colorant_cost_incl_vat:.2f} KES")
        _logger.info(f"    Total Cost: {parent_wizard.total_cost_incl_vat:.2f} KES")
        _logger.info(f"    Selling Price: {parent_wizard.selling_price_incl_vat:.2f} KES")
        _logger.info(f"    Profit: {parent_wizard.profit_amount_incl_vat:.2f} KES")
        
        if is_scaled:
            _logger.info(f"    🔄 Volume scaled: {self.wizard_id.source_volume_litres:.0f}L → {self.wizard_id.target_volume_litres:.0f}L ({self.wizard_id.scale_factor:.2f}×)")
            _logger.info(f"    🎨 Colorant shots scaled accordingly")
        
        _logger.info("=" * 80)
        _logger.info("🔄 Reopening parent wizard with updated values...")
        _logger.info("=" * 80)
        
        # ============================================
        # REOPEN PARENT WIZARD TO SHOW UPDATES
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
    ENHANCED: Now supports volume scaling to translate formulas between package sizes.
    
    Features:
    - Searches for similar products (same category, UOM, attribute)
    - Applies same colorant formula from parent wizard
    - Calculates costs for each product
    - Shows profit/margin analysis
    - Allows inline price editing
    - Statistics summary (avg cost, lowest cost, highest profit)
    - NEW: Volume scaling - translate to different package sizes
    - NEW: Automatic shot scaling based on volume ratio
    - NEW: Search products in target UOM
    - NEW: One-click update with scaled formula
    
    Usage Flow:
    1. User opens tint wizard, selects base product and enters colorant shots
    2. User clicks "Compare Costs Across Brands" button
    3. This wizard opens, showing all similar products with same colorant formula
    4. OPTIONAL: User enables scaling and enters target volume (e.g., 20L)
    5. System finds products in target UOM and scales colorant shots
    6. User can edit prices, see profit/margin changes
    7. User clicks "Use This" to switch to different brand (with scaled shots if enabled)
    
    ARCHITECTURE: Lines created in create() method after wizard exists
    """
    _name = 'cost.comparison.wizard'
    _description = 'Cost Comparison Wizard with Volume Scaling'
    
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
    # COMPARISON CRITERIA (ORIGINAL)
    # ============================================
    base_category_id = fields.Many2one(
        'product.category',
        string='Category',
        readonly=True,
        help='Product category (e.g., Vinyl Silk, Matt Emulsion)'
    )
    
    base_attribute_name = fields.Char(
        string='Attribute',
        readonly=True,
        help='Normalized attribute name (e.g., "Deep Base", "Medium Base")'
    )
    
    # ============================================
    # COLORANT FORMULA - STORED AS JSON (ORIGINAL)
    # ============================================
    colorant_shots_json = fields.Text(
        string='Original Colorant Shots (JSON)',
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
    # NEW: VOLUME SCALING FIELDS
    # ============================================
    
    # Source (current) volume tracking
    source_uom_id = fields.Many2one(
        'uom.uom',
        string='Source UOM',
        readonly=True,
        help='Current product UOM from parent wizard (e.g., 4L)'
    )
    
    source_volume_litres = fields.Float(
        string='Source Volume (Litres)',
        compute='_compute_source_volume',
        digits=(16, 4),
        help='Current product volume converted to litres'
    )
    
    # Target volume inputs
    show_scaled_products = fields.Boolean(
        string='Show Different Volume',
        default=False,
        help='Enable to compare products in different package size (volume scaling)'
    )
    
    target_volume_litres = fields.Float(
        string='Target Volume (Litres)',
        default=0.0,
        digits=(16, 4),
        help='Enter desired volume in litres to see products in that size'
    )
    
    target_uom_id = fields.Many2one(
        'uom.uom',
        string='Target UOM',
        compute='_compute_target_uom',
        help='UOM record found based on target volume (e.g., 20L)'
    )
    
    # Scaling calculations
    scale_factor = fields.Float(
        string='Scale Factor',
        compute='_compute_scale_factor',
        digits=(16, 6),
        help='Multiplier for shots: (target ÷ source). Example: 20L ÷ 4L = 5×'
    )
    
    shots_per_litre = fields.Float(
        string='Shots per Litre',
        compute='_compute_shots_per_litre',
        digits=(16, 6),
        help='Rate of colorant shots per litre (used for scaling calculations)'
    )
    
    # Scaled colorant shots (stored as JSON)
    scaled_colorant_shots_json = fields.Text(
        string='Scaled Colorant Shots (JSON)',
        compute='_compute_scaled_shots',
        help='Colorant shots scaled to target volume (target_shots = original_shots × scale_factor)'
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
        
        ARCHITECTURE: Only stores configuration data (NO line creation).
        Lines are created in create() method after wizard exists.
        
        ENHANCED: Now also extracts source UOM for scaling calculations.
        
        Process:
        1. Get parent tint wizard from context
        2. Extract base product details (category, UOM, attribute)
        3. Extract colorant shots from parent wizard and store as JSON
        4. NEW: Store source UOM for scaling
        5. NEW: Set default target volume to same as source (no scaling initially)
        6. Return configuration data (wizard creation happens next)
        
        Returns:
            dict: Default field values (NO comparison_line_ids)
        """
        _logger.info("=" * 80)
        _logger.info("🚀 DEFAULT_GET: Cost Comparison Wizard Initialization")
        _logger.info("=" * 80)
        _logger.info("  Calling super().default_get()...")
        
        res = super(CostComparisonWizard, self).default_get(fields_list)
        _logger.debug(f"  Super default fields: {list(res.keys())}")
        
        # ============================================
        # STEP 1: GET PARENT WIZARD
        # ============================================
        _logger.info("📋 STEP 1: Getting parent wizard from context...")
        
        parent_wizard_id = self.env.context.get('default_parent_wizard_id') or \
                          self.env.context.get('parent_wizard_id')
        
        _logger.debug(f"  Context keys: {list(self.env.context.keys())}")
        _logger.debug(f"  parent_wizard_id from context: {parent_wizard_id}")
        
        if not parent_wizard_id:
            _logger.error("❌ ERROR: No parent wizard specified in context!")
            _logger.error("  Available context keys:")
            for key, value in self.env.context.items():
                _logger.error(f"    {key}: {value}")
            raise UserError("No parent wizard specified in context!")
        
        _logger.info(f"  ✅ Parent wizard ID from context: {parent_wizard_id}")
        
        parent_wizard = self.env['tint.wizard'].browse(parent_wizard_id)
        if not parent_wizard.exists():
            _logger.error(f"❌ ERROR: Parent tint wizard ID {parent_wizard_id} not found!")
            raise UserError(f"Parent tint wizard (ID: {parent_wizard_id}) not found!")
        
        # Store parent wizard reference
        res['parent_wizard_id'] = parent_wizard.id
        _logger.info(f"  ✅ Parent wizard exists and is valid")
        _logger.info(f"  Parent wizard reference stored in result dict")
        
        # ============================================
        # STEP 2: GET BASE PRODUCT DETAILS
        # ============================================
        _logger.info("=" * 80)
        _logger.info("📋 STEP 2: Extracting base product details...")
        _logger.info("=" * 80)
        
        base_product = parent_wizard.base_variant_id
        if not base_product:
            _logger.error("❌ ERROR: No base product selected in parent wizard!")
            raise UserError("No base product selected in parent wizard!")
        
        _logger.info(f"  Base product: {base_product.display_name} (ID: {base_product.id})")
        _logger.info(f"  Category: {base_product.categ_id.name} (ID: {base_product.categ_id.id})")
        _logger.info(f"  UOM: {base_product.uom_id.name} (ID: {base_product.uom_id.id})")
        
        # Store comparison criteria
        res['base_category_id'] = base_product.categ_id.id
        
        # NEW: Store source UOM for scaling
        res['source_uom_id'] = base_product.uom_id.id
        _logger.info(f"  ✅ Source UOM stored: {base_product.uom_id.name}")
        
        # Extract normalized attribute name (strip variant codes like W2/B2)
        attribute_name = self._extract_attribute_name(base_product)
        res['base_attribute_name'] = attribute_name
        _logger.info(f"  Attribute: '{attribute_name}'")
        _logger.info(f"  ✅ Comparison criteria stored")
        
        # ============================================
        # STEP 3: STORE COLORANT SHOTS AS JSON
        # ============================================
        _logger.info("=" * 80)
        _logger.info("📋 STEP 3: Extracting colorant shots from parent wizard...")
        _logger.info("=" * 80)
        
        colorant_shots = {}
        colorant_line_count = len(parent_wizard.colorant_line_ids)
        _logger.info(f"  Total colorant lines in parent: {colorant_line_count}")
        
        for line in parent_wizard.colorant_line_ids:
            if line.shots > 0:
                colorant_shots[line.colorant_code] = {
                    'shots': line.shots,
                    'unit_cost_excl_vat': line.unit_cost_excl_vat or 0.0
                }
                _logger.debug(
                    f"    {line.colorant_code}: {line.shots:.2f} shots @ "
                    f"{line.unit_cost_excl_vat:.2f} KES/L"
                )
        
        res['colorant_shots_json'] = json.dumps(colorant_shots)
        _logger.info(f"  ✅ Extracted {len(colorant_shots)} colorants with shots > 0")
        
        if not colorant_shots:
            _logger.warning("  ⚠️ WARNING: No colorant shots found in parent wizard!")
            _logger.warning("  User may not have entered any colorant values yet")
        
        # ============================================
        # STEP 4: SET DEFAULT TARGET VOLUME (NEW)
        # ============================================
        _logger.info("=" * 80)
        _logger.info("📋 STEP 4: Setting default target volume...")
        _logger.info("=" * 80)
        
        try:
            # Convert source UOM to litres
            reference_uom = self.env.ref('uom.product_uom_litre')
            source_volume = base_product.uom_id._compute_quantity(
                1.0,
                reference_uom,
                round=False
            )
            res['target_volume_litres'] = source_volume
            
            _logger.info(f"  Source UOM: {base_product.uom_id.name}")
            _logger.info(f"  Converted to litres: {source_volume:.4f}L")
            _logger.info(f"  ✅ Default target volume set to source volume (no scaling)")
        except Exception as e:
            _logger.error(f"  ❌ ERROR converting UOM to litres: {str(e)}")
            res['target_volume_litres'] = 0.0
            _logger.warning(f"  Setting target_volume_litres to 0.0 as fallback")
        
        # ============================================
        # STEP 5: SET SCALING DISABLED BY DEFAULT (NEW)
        # ============================================
        res['show_scaled_products'] = False
        _logger.info(f"  ✅ Volume scaling disabled by default (show_scaled_products=False)")
        
        # ============================================
        # FINAL: RETURN CONFIG (NO LINES YET)
        # ============================================
        _logger.info("=" * 80)
        _logger.info("💡 CONFIGURATION COMPLETE")
        _logger.info("=" * 80)
        _logger.info("  Fields stored in result dict:")
        for key, value in res.items():
            if key == 'colorant_shots_json':
                _logger.info(f"    {key}: <JSON with {len(colorant_shots)} colorants>")
            else:
                _logger.info(f"    {key}: {value}")
        
        _logger.info("=" * 80)
        _logger.info("💡 Comparison lines will be created in create() method")
        _logger.info("=" * 80)
        
        return res
    
    # ============================================
    # CREATE METHOD - LINE CREATION HAPPENS HERE
    # ============================================
    @api.model_create_multi
    def create(self, vals_list):
        """
        Create wizard and populate comparison lines.
        
        ARCHITECTURE: This is where comparison lines are created.
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
        _logger.info(f"  Creating {len(vals_list)} wizard(s)...")
        
        for i, vals in enumerate(vals_list, 1):
            _logger.debug(f"  Wizard {i} vals keys: {list(vals.keys())}")
        
        # STEP 1: Create wizard record first
        _logger.info("📋 STEP 1: Creating wizard record(s)...")
        wizards = super().create(vals_list)
        _logger.info(f"  ✅ Created {len(wizards)} wizard record(s)")
        
        for wizard in wizards:
            _logger.info(f"    Wizard ID: {wizard.id}")
            _logger.info(f"    Parent wizard ID: {wizard.parent_wizard_id.id}")
            _logger.info(f"    Source UOM: {wizard.source_uom_id.name if wizard.source_uom_id else 'None'}")
            _logger.info(f"    Scaling enabled: {wizard.show_scaled_products}")
        
        # STEP 2: Populate comparison lines for each wizard
        _logger.info("=" * 80)
        _logger.info("📋 STEP 2: Populating comparison lines...")
        _logger.info("=" * 80)
        
        for wizard in wizards:
            _logger.info(f"  Processing wizard ID: {wizard.id}...")
            try:
                wizard._populate_comparison_lines()
                line_count = len(wizard.comparison_line_ids)
                _logger.info(f"  ✅ Populated {line_count} comparison line(s)")
            except Exception as e:
                _logger.error(f"  ❌ ERROR populating lines for wizard {wizard.id}:")
                _logger.error(f"     {str(e)}")
                _logger.error(f"     Exception type: {type(e).__name__}")
                import traceback
                _logger.error(f"     Traceback:\n{traceback.format_exc()}")
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
        ENHANCED: Now supports volume scaling - searches target UOM and uses scaled shots.
        
        ARCHITECTURE: This method creates comparison line records.
        Called from create() after wizard exists with valid ID.
        
        Process:
        1. Determine which UOM to search (source or target)
        2. Determine which shots to use (original or scaled)
        3. Parse colorant shots from JSON
        4. Search for similar products (same category/UOM/attribute)
        5. Calculate costs for each product using colorant formula
        6. Create comparison line records directly
        
        NEW LOGIC:
        - If show_scaled_products=True: Search target UOM, use scaled shots
        - If show_scaled_products=False: Search source UOM, use original shots
        """
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("🔍 POPULATE COMPARISON LINES")
        _logger.info("=" * 80)
        _logger.info(f"  Wizard ID: {self.id}")
        _logger.info(f"  Parent Wizard ID: {self.parent_wizard_id.id}")
        
        # ============================================
        # STEP 1: DETERMINE UOM AND SHOTS TO USE
        # ============================================
        _logger.info("=" * 80)
        _logger.info("📋 STEP 1: Determining search criteria (UOM and shots)...")
        _logger.info("=" * 80)
        
        if self.show_scaled_products and self.target_uom_id:
            # User wants different volume - search target UOM with scaled shots
            search_uom_id = self.target_uom_id.id
            search_uom_name = self.target_uom_id.name
            colorant_shots_json = self.scaled_colorant_shots_json or '{}'
            
            _logger.info(f"  🔄 VOLUME SCALING ACTIVE")
            _logger.info(f"  Source UOM: {self.source_uom_id.name} ({self.source_volume_litres:.2f}L)")
            _logger.info(f"  Target UOM: {search_uom_name} ({self.target_volume_litres:.2f}L)")
            _logger.info(f"  Scale Factor: {self.scale_factor:.4f}×")
            _logger.info(f"  Using SCALED colorant shots")
        else:
            # Normal comparison - search source UOM with original shots
            search_uom_id = self.source_uom_id.id
            search_uom_name = self.source_uom_id.name
            colorant_shots_json = self.colorant_shots_json or '{}'
            
            _logger.info(f"  ✅ NO SCALING - Using original values")
            _logger.info(f"  Search UOM: {search_uom_name}")
            _logger.info(f"  Using ORIGINAL colorant shots")
        
        # ============================================
        # STEP 2: PARSE COLORANT SHOTS FROM JSON
        # ============================================
        _logger.info("=" * 80)
        _logger.info("📋 STEP 2: Parsing colorant shots from JSON...")
        _logger.info("=" * 80)
        
        try:
            colorant_shots = json.loads(colorant_shots_json)
            _logger.info(f"  ✅ Parsed {len(colorant_shots)} colorant entries from JSON")
            
            if colorant_shots:
                _logger.info("  Colorant breakdown:")
                for code, data in colorant_shots.items():
                    _logger.info(f"    {code}: {data['shots']:.2f} shots @ {data['unit_cost_excl_vat']:.2f} KES/L")
            else:
                _logger.warning("  ⚠️ WARNING: No colorant shots found in JSON!")
        except json.JSONDecodeError as e:
            _logger.error(f"  ❌ ERROR parsing JSON: {str(e)}")
            _logger.error(f"  JSON content: {colorant_shots_json[:200]}...")
            colorant_shots = {}
        except Exception as e:
            _logger.error(f"  ❌ ERROR: {str(e)}")
            colorant_shots = {}
        
        # ============================================
        # STEP 3: SEARCH FOR SIMILAR PRODUCTS
        # ============================================
        _logger.info("=" * 80)
        _logger.info("🔍 STEP 3: Searching for similar products...")
        _logger.info("=" * 80)
        _logger.info(f"  Search criteria:")
        _logger.info(f"    Category: {self.base_category_id.name} (ID: {self.base_category_id.id})")
        _logger.info(f"    UOM: {search_uom_name} (ID: {search_uom_id})")
        _logger.info(f"    Attribute: '{self.base_attribute_name}'")
        
        # Build search domain
        domain = [
            ('categ_id', '=', self.base_category_id.id),
            ('uom_id', '=', search_uom_id),  # ✅ Use determined UOM (source or target)
            ('product_tmpl_id.is_colorant', '=', False),
            ('product_tmpl_id.is_tinted_product', '=', False),
        ]
        
        _logger.debug(f"  Search domain: {domain}")
        
        similar_products = self.env['product.product'].search(domain)
        _logger.info(f"  Found {len(similar_products)} products matching category/UOM")
        
        if similar_products:
            _logger.debug("  Products found:")
            for prod in similar_products:
                _logger.debug(f"    - {prod.display_name} (ID: {prod.id})")
        
        # Filter by normalized attribute name (for cross-brand matching)
        _logger.info(f"  Filtering by attribute: '{self.base_attribute_name}'...")
        
        filtered_products = similar_products.filtered(
            lambda p: self._extract_attribute_name(p) == self.base_attribute_name
        )
        
        _logger.info(f"  ✅ Found {len(filtered_products)} products after attribute filter")
        
        if not filtered_products:
            _logger.warning("=" * 80)
            _logger.warning("⚠️ NO SIMILAR PRODUCTS FOUND!")
            _logger.warning("=" * 80)
            _logger.warning("  Possible reasons:")
            _logger.warning(f"    1. No other brands have {search_uom_name} products in {self.base_category_id.name}")
            _logger.warning(f"    2. Attribute extraction failed (looking for: '{self.base_attribute_name}')")
            _logger.warning("    3. Product naming is inconsistent")
            _logger.warning("    4. Products not properly categorized")
            _logger.warning("=" * 80)
            return
        
        if filtered_products:
            _logger.info("  Filtered products:")
            for prod in filtered_products:
                _logger.info(f"    ✓ {prod.display_name}")
        
        # ============================================
        # STEP 4: CALCULATE COSTS FOR EACH PRODUCT
        # ============================================
        _logger.info("=" * 80)
        _logger.info("💰 STEP 4: Calculating costs and creating comparison lines...")
        _logger.info("=" * 80)
        
        # Get current base product from parent wizard
        current_product_id = self.parent_wizard_id.base_variant_id.id
        _logger.info(f"  Current product ID: {current_product_id}")
        
        lines_created = 0
        total_processing_time = 0
        
        for idx, product in enumerate(filtered_products, 1):
            _logger.info(f"  [{idx}/{len(filtered_products)}] Processing: {product.display_name} (ID: {product.id})")
            
            import time
            start_time = time.time()
            
            # Check if this is the current product
            is_current = (product.id == current_product_id)
            if is_current:
                _logger.info(f"    ⭐ This is the CURRENT product in parent wizard")
            
            # ============================================
            # CALCULATE BASE COST
            # ============================================
            base_cost_excl = product.standard_price or 0.0
            base_cost_incl = base_cost_excl * 1.16  # Add 16% VAT
            
            _logger.debug(f"    Base cost: {base_cost_excl:.2f} KES (excl) → {base_cost_incl:.2f} KES (incl VAT)")
            
            # ============================================
            # CALCULATE COLORANT COST
            # Same formula applied to all products
            # ============================================
            colorant_cost_excl = 0.0
            colorant_details = []
            
            for colorant_code, data in colorant_shots.items():
                shots = data['shots']
                unit_cost = data['unit_cost_excl_vat']
                
                # Convert shots to litres
                ml_volume = shots * 0.616  # 1 shot = 0.616 ml
                qty_litres = ml_volume / 1000.0
                
                # Calculate cost for this colorant
                colorant_line_cost = qty_litres * unit_cost
                colorant_cost_excl += colorant_line_cost
                
                colorant_details.append({
                    'code': colorant_code,
                    'shots': shots,
                    'ml': ml_volume,
                    'litres': qty_litres,
                    'cost': colorant_line_cost
                })
                
                _logger.debug(
                    f"      {colorant_code}: {shots:.2f} shots = {ml_volume:.3f}ml = "
                    f"{qty_litres:.6f}L × {unit_cost:.2f} = {colorant_line_cost:.2f} KES"
                )
            
            colorant_cost_incl = colorant_cost_excl * 1.16  # Add 16% VAT
            _logger.debug(
                f"    Total colorant: {colorant_cost_excl:.2f} KES (excl) → "
                f"{colorant_cost_incl:.2f} KES (incl VAT)"
            )
            
            # ============================================
            # CALCULATE TOTAL COST
            # ============================================
            total_cost_incl = base_cost_incl + colorant_cost_incl
            _logger.info(f"    💰 TOTAL COST: {total_cost_incl:.2f} KES (incl VAT)")
            
            # ============================================
            # DEFAULT SELLING PRICE (30% MARKUP)
            # ============================================
            selling_price = total_cost_incl * 1.30
            profit = selling_price - total_cost_incl
            margin = (profit / selling_price * 100) if selling_price > 0 else 0
            
            _logger.debug(
                f"    Suggested pricing: {selling_price:.2f} KES "
                f"(Profit: {profit:.2f} KES, Margin: {margin:.2f}%)"
            )
            
            # ============================================
            # CREATE COMPARISON LINE DIRECTLY
            # ============================================
            try:
                line_vals = {
                    'wizard_id': self.id,
                    'product_id': product.id,
                    'is_current_product': is_current,
                    'base_cost_incl_vat': base_cost_incl,
                    'colorant_cost_incl_vat': colorant_cost_incl,
                    'total_cost_incl_vat': total_cost_incl,
                    'selling_price_incl_vat': selling_price,
                }
                
                _logger.debug(f"    Creating comparison line...")
                _logger.debug(f"      wizard_id: {line_vals['wizard_id']}")
                _logger.debug(f"      product_id: {line_vals['product_id']}")
                _logger.debug(f"      total_cost: {line_vals['total_cost_incl_vat']:.2f}")
                
                line = self.env['cost.comparison.line'].create(line_vals)
                lines_created += 1
                
                elapsed = time.time() - start_time
                total_processing_time += elapsed
                
                _logger.info(
                    f"    ✅ Line created (ID: {line.id}) in {elapsed:.3f}s: "
                    f"Cost={total_cost_incl:.2f} KES, Price={selling_price:.2f} KES"
                )
                
            except Exception as e:
                _logger.error(f"    ❌ ERROR creating comparison line:")
                _logger.error(f"       {str(e)}")
                _logger.error(f"       Exception type: {type(e).__name__}")
                _logger.error(f"       Line vals: {line_vals}")
                import traceback
                _logger.error(f"       Traceback:\n{traceback.format_exc()}")
                raise
        
        # ============================================
        # FINAL SUMMARY
        # ============================================
        _logger.info("=" * 80)
        _logger.info("✅ SUCCESS: Comparison lines populated")
        _logger.info("=" * 80)
        _logger.info(f"  Lines created: {lines_created}")
        _logger.info(f"  Total lines in wizard: {len(self.comparison_line_ids)}")
        _logger.info(f"  Total processing time: {total_processing_time:.3f}s")
        _logger.info(f"  Average time per line: {total_processing_time/lines_created:.3f}s")
        
        if self.show_scaled_products:
            _logger.info(f"  🔄 Volume scaling was ACTIVE")
            _logger.info(f"     Searched UOM: {search_uom_name}")
            _logger.info(f"     Scale factor: {self.scale_factor:.4f}×")
        else:
            _logger.info(f"  ✅ No scaling applied - used original UOM and shots")
        
        _logger.info("=" * 80)
    
    # ============================================
    # NEW: VOLUME SCALING COMPUTE METHODS
    # ============================================
    
    @api.depends('source_uom_id')
    def _compute_source_volume(self):
        """
        Convert source UOM to litres.
        
        Example:
            Source UOM: 4L
            Converted: 4.0 litres
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: Source volume in litres")
        _logger.info("=" * 80)
        
        for wizard in self:
            wizard_id_str = f"Wizard ID: {wizard.id}" if wizard.id else "New Wizard"
            _logger.debug(f"  {wizard_id_str}")
            
            if wizard.source_uom_id:
                try:
                    reference_uom = self.env.ref('uom.product_uom_litre')
                    volume = wizard.source_uom_id._compute_quantity(
                        1.0,
                        reference_uom,
                        round=False
                    )
                    wizard.source_volume_litres = volume
                    _logger.info(f"    Source UOM: {wizard.source_uom_id.name} → {volume:.4f} litres")
                except Exception as e:
                    _logger.error(f"    ❌ ERROR converting UOM: {str(e)}")
                    wizard.source_volume_litres = 0.0
            else:
                wizard.source_volume_litres = 0.0
                _logger.debug(f"    No source UOM set, volume = 0")
        
        _logger.info("=" * 80)
    
    @api.depends('target_volume_litres')
    def _compute_target_uom(self):
        """
        Find UOM record that matches target volume.
        
        Search Logic:
        1. Try exact match with volume (e.g., "20L", "20ltr")
        2. Try rounded integer match
        3. Fallback to litre reference UOM
        
        Example:
            User enters: 20.0 litres
            System searches: "20L", "20ltr", "20 Litres"
            Finds: UOM record for "20L"
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: Target UOM from volume")
        _logger.info("=" * 80)
        
        for wizard in self:
            wizard_id_str = f"Wizard ID: {wizard.id}" if wizard.id else "New Wizard"
            _logger.debug(f"  {wizard_id_str}")
            
            if wizard.target_volume_litres > 0:
                volume_int = int(wizard.target_volume_litres)
                _logger.info(f"    Target volume: {wizard.target_volume_litres:.2f}L → Searching for UOM...")
                
                # Try common naming patterns
                search_terms = [
                    f"{volume_int}L",
                    f"{volume_int}ltr",
                    f"{volume_int} Litres",
                    f"{volume_int} litres",
                    f"{volume_int}LTR",
                ]
                
                _logger.debug(f"    Search terms: {search_terms}")
                
                found = False
                for term in search_terms:
                    uom = self.env['uom.uom'].search([
                        ('name', 'ilike', term)
                    ], limit=1)
                    
                    if uom:
                        wizard.target_uom_id = uom
                        _logger.info(f"    ✅ Found UOM: {uom.name} (ID: {uom.id}) using search term '{term}'")
                        found = True
                        break
                
                if not found:
                    # Fallback: use litres as reference
                    wizard.target_uom_id = self.env.ref('uom.product_uom_litre')
                    _logger.warning(f"    ⚠️ No matching UOM found, using reference 'Litres'")
            else:
                wizard.target_uom_id = False
                _logger.debug(f"    Target volume not set, no UOM")
        
        _logger.info("=" * 80)
    
    @api.depends('source_volume_litres', 'target_volume_litres')
    def _compute_scale_factor(self):
        """
        Calculate scaling multiplier.
        
        Formula: Scale Factor = Target Volume ÷ Source Volume
        
        Examples:
            4L → 20L: 20 ÷ 4 = 5.0× (upscaling)
            20L → 4L: 4 ÷ 20 = 0.2× (downscaling)
            4L → 4L: 4 ÷ 4 = 1.0× (no scaling)
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: Scale factor")
        _logger.info("=" * 80)
        
        for wizard in self:
            wizard_id_str = f"Wizard ID: {wizard.id}" if wizard.id else "New Wizard"
            _logger.debug(f"  {wizard_id_str}")
            
            if wizard.source_volume_litres > 0 and wizard.target_volume_litres > 0:
                wizard.scale_factor = wizard.target_volume_litres / wizard.source_volume_litres
                
                _logger.info(f"    Source: {wizard.source_volume_litres:.2f}L")
                _logger.info(f"    Target: {wizard.target_volume_litres:.2f}L")
                _logger.info(f"    Scale Factor: {wizard.scale_factor:.6f}×")
                
                if wizard.scale_factor > 1:
                    _logger.info(f"    🔼 UPSCALING ({wizard.scale_factor:.2f}× larger)")
                elif wizard.scale_factor < 1:
                    _logger.info(f"    🔽 DOWNSCALING ({wizard.scale_factor:.2f}× smaller)")
                else:
                    _logger.info(f"    ➡️ NO SCALING (same volume)")
            else:
                wizard.scale_factor = 1.0
                _logger.debug(f"    Invalid volumes, scale factor = 1.0 (no scaling)")
        
        _logger.info("=" * 80)
    
    @api.depends('colorant_shots_json', 'source_volume_litres')
    def _compute_shots_per_litre(self):
        """
        Calculate shots per litre rate from original formula.
        
        Formula: Shots per Litre = Total Shots ÷ Source Volume
        
        Example:
            Source: 4L product
            Total shots: 15 shots (C1=10, C3=5)
            Rate: 15 ÷ 4 = 3.75 shots per litre
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: Shots per litre rate")
        _logger.info("=" * 80)
        
        for wizard in self:
            wizard_id_str = f"Wizard ID: {wizard.id}" if wizard.id else "New Wizard"
            _logger.debug(f"  {wizard_id_str}")
            
            try:
                colorant_shots = json.loads(wizard.colorant_shots_json or '{}')
                total_shots = sum(data['shots'] for data in colorant_shots.values())
                
                if wizard.source_volume_litres > 0 and total_shots > 0:
                    wizard.shots_per_litre = total_shots / wizard.source_volume_litres
                    _logger.info(f"    Total shots: {total_shots:.2f}")
                    _logger.info(f"    Source volume: {wizard.source_volume_litres:.2f}L")
                    _logger.info(f"    Rate: {wizard.shots_per_litre:.6f} shots/litre")
                else:
                    wizard.shots_per_litre = 0.0
                    _logger.debug(f"    Cannot calculate rate (volume or shots = 0)")
            except Exception as e:
                _logger.error(f"    ❌ ERROR: {str(e)}")
                wizard.shots_per_litre = 0.0
        
        _logger.info("=" * 80)
    
    @api.depends('colorant_shots_json', 'scale_factor')
    def _compute_scaled_shots(self):
        """
        Scale colorant shots based on volume change.
        
        Process:
        1. Parse original shots from JSON
        2. Multiply each shot value by scale factor
        3. Store scaled shots as JSON
        
        Formula: Scaled Shots = Original Shots × Scale Factor
        
        Example:
            Original: C1=10 shots, C3=5 shots (for 4L)
            Scale: 5× (4L → 20L)
            Scaled: C1=50 shots, C3=25 shots (for 20L)
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: Scaled colorant shots")
        _logger.info("=" * 80)
        
        for wizard in self:
            wizard_id_str = f"Wizard ID: {wizard.id}" if wizard.id else "New Wizard"
            _logger.debug(f"  {wizard_id_str}")
            
            try:
                original_shots = json.loads(wizard.colorant_shots_json or '{}')
                scaled_shots = {}
                
                _logger.info(f"    Scale factor: {wizard.scale_factor:.6f}×")
                _logger.info(f"    Original colorant shots: {len(original_shots)}")
                
                for code, data in original_shots.items():
                    original_shot_value = data['shots']
                    scaled_shot_value = original_shot_value * wizard.scale_factor
                    
                    scaled_shots[code] = {
                        'shots': scaled_shot_value,
                        'unit_cost_excl_vat': data['unit_cost_excl_vat']
                    }
                    
                    _logger.debug(
                        f"      {code}: {original_shot_value:.2f} → {scaled_shot_value:.2f} shots "
                        f"({original_shot_value:.2f} × {wizard.scale_factor:.4f})"
                    )
                
                wizard.scaled_colorant_shots_json = json.dumps(scaled_shots)
                _logger.info(f"    ✅ Scaled {len(scaled_shots)} colorant entries")
                
            except json.JSONDecodeError as e:
                _logger.error(f"    ❌ JSON decode error: {str(e)}")
                wizard.scaled_colorant_shots_json = '{}'
            except Exception as e:
                _logger.error(f"    ❌ ERROR scaling shots: {str(e)}")
                wizard.scaled_colorant_shots_json = '{}'
        
        _logger.info("=" * 80)
    
    # ============================================
    # NEW: REFRESH ACTION METHOD
    # ============================================
    def action_refresh_comparison(self):
        """
        Refresh comparison lines when scaling parameters change.
        
        Process:
        1. Delete existing comparison lines
        2. Repopulate with new search criteria (target UOM, scaled shots)
        3. Reopen wizard to show updated results
        
        Use Cases:
        - User changes target volume
        - User toggles scaling on/off
        - User wants to see updated products
        """
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("🔄 ACTION: Refresh Comparison")
        _logger.info("=" * 80)
        _logger.info(f"  Wizard ID: {self.id}")
        _logger.info(f"  Current comparison lines: {len(self.comparison_line_ids)}")
        
        # Delete existing lines
        _logger.info("  Deleting existing comparison lines...")
        line_ids = self.comparison_line_ids.ids
        self.comparison_line_ids.unlink()
        _logger.info(f"  ✅ Deleted {len(line_ids)} line(s)")
        
        # Repopulate with new UOM and scaled shots
        _logger.info("  Repopulating with current settings...")
        _logger.info(f"    Scaling enabled: {self.show_scaled_products}")
        if self.show_scaled_products:
            _logger.info(f"    Target volume: {self.target_volume_litres:.2f}L")
            if self.target_uom_id:
                _logger.info(f"    Target UOM: {self.target_uom_id.name}")
            _logger.info(f"    Scale factor: {self.scale_factor:.4f}×")
        
        self._populate_comparison_lines()
        
        _logger.info("=" * 80)
        _logger.info(f"✅ Refresh completed: {len(self.comparison_line_ids)} line(s) created")
        _logger.info("=" * 80)
        
        # ============================================
        # FIX: Reopen wizard to show updated lines
        # ============================================
        
        if len(self.comparison_line_ids) == 0:
            # No products found - show warning and reopen
            _logger.warning("  ⚠️ No products found for selected criteria")
            
            # Reopen wizard (stays open, shows warning)
            return {
                'type': 'ir.actions.act_window',
                'name': 'Cost Comparison & Volume Scaling',
                'res_model': 'cost.comparison.wizard',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
                'context': dict(self.env.context, 
                            default_show_notification=True,
                            notification_type='warning',
                            notification_title='No Products Found',
                            notification_message=f'No products found for {self.target_uom_id.name if self.target_uom_id else "target UOM"} '
                                                f'in {self.base_category_id.name} category with attribute "{self.base_attribute_name}".')
            }
        
        # Products found - reopen wizard to show them
        _logger.info(f"  🎉 Reopening wizard with {len(self.comparison_line_ids)} product(s)")
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cost Comparison & Volume Scaling',
            'res_model': 'cost.comparison.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context,
                        default_show_notification=True,
                        notification_type='success',
                        notification_title='Products Refreshed',
                        notification_message=f'Found {len(self.comparison_line_ids)} product(s) for comparison.')
        }
            
    # ============================================
    # COMPUTE METHODS (EXISTING)
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
            
            wizard_id_str = f"Wizard ID: {wizard.id}" if wizard.id else "New Wizard"
            _logger.debug(f"  {wizard_id_str}")
            _logger.info(f"  Comparison lines: {len(lines)}")
            
            if lines:
                costs = lines.mapped('total_cost_incl_vat')
                profits = lines.mapped('profit_amount_incl_vat')
                
                wizard.total_products = len(lines)
                wizard.avg_cost = sum(costs) / len(costs)
                wizard.lowest_cost = min(costs)
                wizard.highest_profit = max(profits)
                
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
            
            Input:  "20L Plascon Vinyl Silk (Pastel Base)"
            Output: "pastel base"
        
        Args:
            product (product.product): Product record
            
        Returns:
            str: Normalized attribute name (lowercase, no variant codes)
        """
        display_name = product.display_name.lower()
        
        _logger.debug(f"    Extracting attribute from: '{product.display_name}'")
        
        # Extract text between first '(' and '/'
        # This gets the attribute name before variant code
        if '(' in display_name and '/' in display_name:
            start = display_name.find('(') + 1
            end = display_name.find('/', start)
            attribute = display_name[start:end].strip()
            
            _logger.debug(f"      ✅ Extracted attribute: '{attribute}'")
            return attribute
        
        # If no '/', try to extract everything in parentheses
        if '(' in display_name and ')' in display_name:
            start = display_name.find('(') + 1
            end = display_name.find(')')
            attribute = display_name[start:end].strip()
            
            _logger.debug(f"      ✅ Extracted attribute (no variant code): '{attribute}'")
            return attribute
        
        _logger.debug(f"      ⚠️ Could not extract attribute, using 'unknown'")
        return 'unknown'