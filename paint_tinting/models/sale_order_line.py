# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import json
import logging


_logger = logging.getLogger(__name__)
_logger.info("=== DIAGNOSTIC: sale_order.py LOADED SUCCESSFULLY ===")


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    has_exactly_one_tinted_line = fields.Boolean(
        string="Has Exactly One Tinted Line",
        compute='_compute_has_exactly_one_tinted_line',
        store=False,
    )

    @api.depends('order_line.is_tinted_product_line')
    def _compute_has_exactly_one_tinted_line(self):
        for order in self:
            tinted_lines = order.order_line.filtered('is_tinted_product_line')
            order.has_exactly_one_tinted_line = len(tinted_lines) == 1

    def action_create_tinted_product_from_line(self):
        """
        Create tinted product, BOM, and MO from the single tinted order line.
        ENHANCED: 
        - Mirrors exact fallback logic from tint_wizard with comprehensive logging
        - After MO creation, replaces base product with tinted product in sale order
        - Preserves selling price from quotation generator
        """
        self.ensure_one()
        
        _logger.info("=" * 100)
        _logger.info("🚀 QUOTATION → PRODUCT CREATION - START")
        _logger.info("=" * 100)
        _logger.info(f"  Sale Order: {self.name} (ID: {self.id})")
        _logger.info(f"  Customer: {self.partner_id.name}")
        
        # ============================================
        # STEP 1: VALIDATE SINGLE TINTED LINE
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 1: VALIDATION - Single Tinted Line Check")
        _logger.info("=" * 100)
        
        tinted_lines = self.order_line.filtered('is_tinted_product_line')
        _logger.info(f"  Found {len(tinted_lines)} tinted line(s) in order")
        
        if len(tinted_lines) != 1:
            _logger.error("❌ VALIDATION FAILED: Not exactly one tinted line!")
            _logger.error(f"  Expected: 1 tinted line")
            _logger.error(f"  Found: {len(tinted_lines)} tinted line(s)")
            raise UserError(_(
                "This action requires exactly one tinted product line in the order.\n\n"
                "Current state: %d tinted line(s) found.\n"
                "Please ensure other comparison lines are deleted and only one remains."
            ) % len(tinted_lines))
        
        line = tinted_lines[0]
        _logger.info(f"  ✅ Using tinted line ID: {line.id}")
        _logger.info(f"  Product from line: {line.product_id.display_name}")
        _logger.info(f"  Quantity: {line.product_uom_qty}")
        _logger.info(f"  Price Unit (from quotation): {line.price_unit} KES")
        _logger.info(f"  Line Total: {line.price_total} KES")
        
        # Store original price for later verification
        original_selling_price = line.price_unit
        _logger.info(f"  💰 ORIGINAL SELLING PRICE STORED: {original_selling_price} KES")
        
        # ============================================
        # STEP 2: VALIDATE REQUIRED METADATA
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 2: METADATA VALIDATION")
        _logger.info("=" * 100)
        
        required_fields = {
            'base_product_id': 'Base Product',
            'base_product_uom_id': 'Base Product UOM',
            'tinting_formula_json': 'Tinting Formula',
            'colour_code_id': 'Colour Code',
            'fandeck_id': 'Fandeck',
            'base_category_id': 'Base Category'
        }
        
        missing = []
        for field, label in required_fields.items():
            value = getattr(line, field, None)
            if value:
                if field == 'tinting_formula_json':
                    _logger.info(f"  ✅ {label}: Present (JSON length: {len(value)})")
                else:
                    _logger.info(f"  ✅ {label}: {value.display_name if hasattr(value, 'display_name') else value}")
            else:
                _logger.error(f"  ❌ {label}: MISSING!")
                missing.append(label)
        
        if missing:
            _logger.error("=" * 100)
            _logger.error("❌ METADATA VALIDATION FAILED")
            _logger.error(f"  Missing fields: {', '.join(missing)}")
            _logger.error("=" * 100)
            raise UserError(_("Missing tinting metadata on order line: %s") % ', '.join(missing))
        
        _logger.info("  ✅ All required metadata present")
        
        # ============================================
        # STEP 3: PARSE AND VALIDATE FORMULA
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 3: FORMULA PARSING")
        _logger.info("=" * 100)
        
        try:
            formula_shots = json.loads(line.tinting_formula_json or '{}')
            _logger.info(f"  ✅ JSON parsed successfully")
            _logger.info(f"  Colorant entries: {len(formula_shots)}")
            
            if not formula_shots:
                _logger.error("  ❌ Formula is EMPTY!")
                raise ValueError("Empty formula - no colorant shots found")
            
            # Log each colorant
            for code, data in formula_shots.items():
                _logger.info(f"    {code}: {data['shots']:.2f} shots @ {data['unit_cost_excl_vat']:.2f} KES/L")
                
        except json.JSONDecodeError as e:
            _logger.error("=" * 100)
            _logger.error("❌ JSON PARSING FAILED")
            _logger.error(f"  Error: {str(e)}")
            _logger.error(f"  JSON content (first 200 chars): {line.tinting_formula_json[:200]}")
            _logger.error("=" * 100)
            raise UserError(_("Invalid tinting formula on order line: %s") % str(e))
        except Exception as e:
            _logger.error(f"❌ Unexpected error parsing formula: {str(e)}")
            raise UserError(_("Error processing tinting formula: %s") % str(e))
        
        # ============================================
        # STEP 4: PREPARE PRODUCT NAME
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 4: PRODUCT NAME GENERATION")
        _logger.info("=" * 100)
        
        clean_product_name = f"{line.base_product_id.display_name} – {line.colour_code_id.name} [{line.colour_code_id.code}]".strip()
        _logger.info(f"  Generated name: '{clean_product_name}'")
        
        # Check for existing product
        _logger.info(f"  Checking for existing product...")
        existing = self.env['product.template'].search([
            ('name', '=', clean_product_name),
            ('is_tinted_product', '=', True)
        ], limit=1)
        
        if existing:
            _logger.error("=" * 100)
            _logger.error("❌ PRODUCT ALREADY EXISTS")
            _logger.error(f"  Product: {existing.name}")
            _logger.error(f"  Product ID: {existing.id}")
            _logger.error("=" * 100)
            raise UserError(_("This tinted product already exists: %s (ID: %s)") % (existing.name, existing.id))
        
        _logger.info(f"  ✅ Product name is unique")
        
        uom = line.base_product_uom_id
        _logger.info(f"  Using UoM: {uom.name} (ID: {uom.id})")
        
        # ============================================
        # STEP 5: CATEGORY SETUP
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 5: PRODUCT CATEGORY SETUP")
        _logger.info("=" * 100)
        
        categ = self.env['product.category'].search([('name', '=', 'Tinted Paint')], limit=1)
        if categ:
            _logger.info(f"  ✅ Using existing category: Tinted Paint (ID: {categ.id})")
            _logger.info(f"     Cost Method: {categ.property_cost_method}")
            _logger.info(f"     Valuation: {categ.property_valuation}")
        else:
            _logger.info(f"  Category 'Tinted Paint' not found - creating...")
            categ = self.env['product.category'].create({
                'name': 'Tinted Paint',
                'property_cost_method': 'fifo',
                'property_valuation': 'real_time',
            })
            _logger.info(f"  ✅ Created category: Tinted Paint (ID: {categ.id})")
        
        # ============================================
        # STEP 6: COST CALCULATIONS
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 6: COST CALCULATIONS")
        _logger.info("=" * 100)
        
        total_cost_excl_vat = line.quoted_cost_at_creation / 1.16
        _logger.info(f"  Quoted Cost (Incl VAT): {line.quoted_cost_at_creation:.2f} KES")
        _logger.info(f"  Calculated Cost (Excl VAT): {total_cost_excl_vat:.2f} KES")
        _logger.info(f"  Base Cost (Incl VAT): {line.quoted_base_cost:.2f} KES")
        _logger.info(f"  Colorant Cost (Incl VAT): {line.quoted_colorant_cost:.2f} KES")
        _logger.info(f"  Selling Price (from quotation): {line.price_unit:.2f} KES")
        
        profit = line.price_unit - line.quoted_cost_at_creation
        margin = (profit / line.price_unit * 100) if line.price_unit > 0 else 0
        _logger.info(f"  Calculated Profit: {profit:.2f} KES")
        _logger.info(f"  Calculated Margin: {margin:.2f}%")
        
        # ============================================
        # STEP 7: PRODUCT TYPE DETECTION
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 7: PRODUCT TYPE ANALYSIS")
        _logger.info("=" * 100)
        
        # Check available product types in this Odoo instance
        product_type_field = self.env['product.template']._fields.get('type')
        if product_type_field:
            available_types = product_type_field.get_values(self.env)
            _logger.info(f"  Available product types in system: {available_types}")
        else:
            available_types = []
            _logger.warning("  ⚠️ No 'type' field found on product.template!")
        
        # Get base product type as fallback
        base_type = getattr(line.base_product_id, 'type', 'consu')
        _logger.info(f"  Base product type (fallback): '{base_type}'")
        _logger.info(f"  Base product: {line.base_product_id.display_name}")
        
        # ============================================
        # STEP 8: PRODUCT CREATION WITH FALLBACKS
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 8: PRODUCT TEMPLATE CREATION (WITH FALLBACKS)")
        _logger.info("=" * 100)
        
        product_vals = {
            'name': clean_product_name,
            'base_product_name': clean_product_name,
            'categ_id': categ.id,
            'uom_id': uom.id,
            'uom_po_id': uom.id,
            'standard_price': total_cost_excl_vat,
            'list_price': line.price_unit,  # ← Selling price from quotation
            'is_tinted_product': True,
            'fandeck_id': line.fandeck_id.id,
            'colour_code_id': line.colour_code_id.id,
            'sale_ok': True,
            'purchase_ok': True,
            'tracking': 'lot',
            'description': f"Tinted paint: {line.base_product_id.display_name} with {line.colour_code_id.code}",
            'default_code': f"TINT-{line.colour_code_id.code}-{fields.Datetime.now().strftime('%Y%m%d')}",
        }
        
        _logger.info(f"  Product values prepared:")
        _logger.info(f"    name: {product_vals['name']}")
        _logger.info(f"    categ_id: {product_vals['categ_id']}")
        _logger.info(f"    uom_id: {product_vals['uom_id']}")
        _logger.info(f"    standard_price (cost): {product_vals['standard_price']:.2f} KES")
        _logger.info(f"    list_price (selling from quotation): {product_vals['list_price']:.2f} KES")
        _logger.info(f"    tracking: {product_vals['tracking']}")
        _logger.info(f"    sale_ok: {product_vals['sale_ok']}")
        _logger.info(f"    purchase_ok: {product_vals['purchase_ok']}")
        
        # ============================================
        # FALLBACK CHAIN: product → stockable → base_type → no type
        # ============================================
        tmpl = None
        creation_method = None
        
        _logger.info("=" * 100)
        _logger.info("  🔄 ATTEMPT 1: type='product' (Storable Product)")
        _logger.info("=" * 100)
        try:
            product_vals['type'] = 'product'
            _logger.info(f"    Setting type='product'...")
            tmpl = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
            creation_method = "type='product'"
            _logger.info("    ✅ SUCCESS: Product created with type='product'")
        except ValueError as e:
            _logger.warning("    ❌ FAILED with ValueError: %s" % str(e))
            _logger.info("=" * 100)
            _logger.info("  🔄 ATTEMPT 2: type='stockable' (Legacy Storable)")
            _logger.info("=" * 100)
            try:
                product_vals['type'] = 'stockable'
                _logger.info(f"    Setting type='stockable'...")
                tmpl = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                creation_method = "type='stockable'"
                _logger.info("    ✅ SUCCESS: Product created with type='stockable'")
            except ValueError as e2:
                _logger.warning("    ❌ FAILED with ValueError: %s" % str(e2))
                _logger.info("=" * 100)
                _logger.info(f"  🔄 ATTEMPT 3: type='{base_type}' (Base Product Type)")
                _logger.info("=" * 100)
                try:
                    product_vals['type'] = base_type
                    _logger.info(f"    Setting type='{base_type}' (from base product)...")
                    tmpl = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                    creation_method = f"type='{base_type}'"
                    _logger.info(f"    ✅ SUCCESS: Product created with type='{base_type}'")
                except Exception as e3:
                    _logger.error("    ❌ FAILED: %s" % str(e3))
                    _logger.info("=" * 100)
                    _logger.info("  🔄 ATTEMPT 4: No type specified (System Default)")
                    _logger.info("=" * 100)
                    _logger.info(f"    Removing 'type' from product_vals...")
                    if 'type' in product_vals:
                        del product_vals['type']
                    tmpl = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                    creation_method = "no type (system default)"
                    _logger.warning("    ⚠️ SUCCESS: Product created without explicit type")
        except Exception as e:
            _logger.error("    ❌ FAILED with unexpected error: %s" % str(e))
            _logger.error(f"    Exception type: {type(e).__name__}")
            import traceback
            _logger.error(f"    Traceback:\n{traceback.format_exc()}")
            raise UserError(_("Failed to create product template: %s") % str(e))
        
        # ============================================
        # STEP 9: POST-CREATION VERIFICATION
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 9: POST-CREATION VERIFICATION")
        _logger.info("=" * 100)
        
        if not tmpl or not tmpl.id:
            _logger.error("=" * 100)
            _logger.error("❌ PRODUCT CREATION FAILED - No template returned!")
            _logger.error("=" * 100)
            raise UserError(_("Product creation failed - no template returned!"))
        
        _logger.info(f"  ✅ Product Template Created")
        _logger.info(f"     ID: {tmpl.id}")
        _logger.info(f"     Name: {tmpl.name}")
        _logger.info(f"     Creation Method: {creation_method}")
        
        # Check actual type
        if hasattr(tmpl, 'type'):
            current_type = tmpl.type
            _logger.info(f"     Current type: '{current_type}'")
            
            # ============================================
            # STEP 10: TYPE CORRECTION IF NEEDED
            # ============================================
            if current_type != 'product':
                _logger.warning("=" * 100)
                _logger.warning("⚠️ STEP 10: TYPE CORRECTION NEEDED")
                _logger.warning("=" * 100)
                _logger.warning(f"  Product type is '{current_type}', not 'product'")
                _logger.warning(f"  Attempting to update to 'product'...")
                
                try:
                    tmpl.write({'type': 'product'})
                    _logger.info("  ✅ Successfully updated type to 'product'")
                    _logger.info(f"     Verified type: {tmpl.type}")
                except Exception as e:
                    _logger.error(f"  ❌ Failed to update to 'product': {str(e)}")
                    _logger.warning(f"  Trying fallback to 'stockable'...")
                    try:
                        tmpl.write({'type': 'stockable'})
                        _logger.info("  ✅ Successfully updated type to 'stockable'")
                        _logger.info(f"     Verified type: {tmpl.type}")
                    except Exception as e2:
                        _logger.error(f"  ❌ Failed to update to 'stockable': {str(e2)}")
                        _logger.warning(f"  ⚠️ Product will remain as type '{current_type}'")
                        _logger.warning(f"  This may affect inventory visibility!")
            else:
                _logger.info(f"  ✅ Type is already 'product' - no correction needed")
        else:
            _logger.warning("  ⚠️ Product template has no 'type' field!")
        
        # ============================================
        # STEP 11: TRACKING VERIFICATION
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 11: TRACKING VERIFICATION")
        _logger.info("=" * 100)
        
        if hasattr(tmpl, 'tracking'):
            _logger.info(f"  Current tracking: {tmpl.tracking}")
            if tmpl.tracking != 'lot':
                _logger.warning(f"  ⚠️ Tracking is '{tmpl.tracking}', forcing to 'lot'...")
                tmpl.write({'tracking': 'lot'})
                _logger.info(f"  ✅ Tracking updated to: {tmpl.tracking}")
            else:
                _logger.info(f"  ✅ Tracking is already 'lot'")
        else:
            _logger.warning("  ⚠️ Product template has no 'tracking' field!")
        
        # ============================================
        # STEP 12: FINAL PRODUCT STATE VERIFICATION
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 12: FINAL PRODUCT STATE")
        _logger.info("=" * 100)
        
        _logger.info(f"  Product Template ID: {tmpl.id}")
        _logger.info(f"  Product Name: {tmpl.name}")
        _logger.info(f"  Type: {getattr(tmpl, 'type', 'N/A')}")
        _logger.info(f"  Tracking: {getattr(tmpl, 'tracking', 'N/A')}")
        _logger.info(f"  Category: {tmpl.categ_id.name}")
        _logger.info(f"  UOM: {tmpl.uom_id.name}")
        _logger.info(f"  Sale OK: {tmpl.sale_ok}")
        _logger.info(f"  Purchase OK: {tmpl.purchase_ok}")
        _logger.info(f"  Is Tinted Product: {tmpl.is_tinted_product}")
        _logger.info(f"  Standard Price (Cost): {tmpl.standard_price:.2f} KES")
        _logger.info(f"  List Price (Selling): {tmpl.list_price:.2f} KES")
        
        # Check if storable
        is_storable = getattr(tmpl, 'type', None) in ['product', 'stockable']
        _logger.info("=" * 100)
        if is_storable:
            _logger.info("✅ PRODUCT IS STORABLE - Will appear in inventory!")
        else:
            _logger.error("❌ PRODUCT IS NOT STORABLE - Will NOT track inventory!")
            _logger.error(f"   Current type: {getattr(tmpl, 'type', 'Unknown')}")
            _logger.error("   This product will not show available quantity!")
        _logger.info("=" * 100)
        
        # ============================================
        # STEP 13: ROUTES SETUP
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 13: ROUTES CONFIGURATION")
        _logger.info("=" * 100)
        
        routes_added = []
        
        # Manufacturing route
        try:
            manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture')
            if manufacture_route:
                tmpl.write({'route_ids': [(4, manufacture_route.id)]})
                routes_added.append(manufacture_route.name)
                _logger.info(f"  ✅ Added route: {manufacture_route.name}")
            else:
                _logger.warning("  ⚠️ Manufacturing route not found")
        except Exception as e:
            _logger.error(f"  ❌ Could not set manufacturing route: {str(e)}")
        
        # Purchase route
        try:
            purchase_route = self.env.ref('purchase_stock.route_warehouse0_buy')
            if purchase_route:
                tmpl.write({'route_ids': [(4, purchase_route.id)]})
                routes_added.append(purchase_route.name)
                _logger.info(f"  ✅ Added route: {purchase_route.name}")
            else:
                _logger.warning("  ⚠️ Purchase route not found")
        except Exception as e:
            _logger.error(f"  ❌ Could not set purchase route: {str(e)}")
        
        if routes_added:
            _logger.info(f"  Total routes added: {len(routes_added)}")
            _logger.info(f"  Routes: {', '.join(routes_added)}")
        else:
            _logger.warning("  ⚠️ No routes were added to product")
        
        # ============================================
        # STEP 14: BOM CREATION
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 14: BILL OF MATERIALS CREATION")
        _logger.info("=" * 100)
        
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': tmpl.id,
            'product_qty': 1.0,
            'product_uom_id': uom.id,
            'type': 'normal',
            'is_tinting_bom': True,
            'fandeck_id': line.fandeck_id.id,
            'colour_code_id': line.colour_code_id.id,
            'base_variant_id': line.base_product_id.id,
            'pack_size_uom_id': line.base_product_uom_id.id,
            'tinting_notes': line.name,
        })
        
        _logger.info(f"  ✅ BOM Created")
        _logger.info(f"     ID: {bom.id}")
        _logger.info(f"     Product: {tmpl.name}")
        _logger.info(f"     Quantity: {bom.product_qty} {bom.product_uom_id.name}")
        _logger.info(f"     Type: {bom.type}")
        
        # Add base product line
        _logger.info(f"  Adding base product line...")
        base_bom_line = self.env['mrp.bom.line'].create({
            'bom_id': bom.id,
            'product_id': line.base_product_id.id,
            'product_qty': 1.0,
            'product_uom_id': uom.id,
            'unit_cost_excl_vat': line.quoted_base_cost / 1.16,
        })
        _logger.info(f"    ✅ Base line: {line.base_product_id.display_name} × 1.0 {uom.name}")
        _logger.info(f"       Cost: {base_bom_line.unit_cost_excl_vat:.2f} KES (excl VAT)")
        
        # Add colorant lines
        _logger.info(f"  Adding colorant lines from formula...")
        colorant_lines_added = 0
        
        for colorant_code, data in formula_shots.items():
            _logger.info(f"    Processing {colorant_code}...")
            
            # Find colorant product
            colorant_product = self.env['product.product'].search([
                ('product_tmpl_id.colorant_code', '=', colorant_code),
                ('product_tmpl_id.is_colorant', '=', True)
            ], limit=1)
            
            if not colorant_product:
                _logger.error(f"      ❌ Colorant {colorant_code} not found in system!")
                raise UserError(_("Colorant %s not found in system!") % colorant_code)
            
            shots = data['shots']
            ml_volume = shots * 0.616
            qty_litres = ml_volume / 1000.0
            
            _logger.info(f"      Product: {colorant_product.display_name}")
            _logger.info(f"      Shots: {shots:.2f}")
            _logger.info(f"      ML: {ml_volume:.3f}")
            _logger.info(f"      Litres: {qty_litres:.6f}")
            
            colorant_bom_line = self.env['mrp.bom.line'].create({
                'bom_id': bom.id,
                'product_id': colorant_product.id,
                'product_qty': qty_litres,
                'product_uom_id': colorant_product.uom_id.id,
                'is_colorant_line': True,
                'colorant_shots': shots,
                'unit_cost_excl_vat': data['unit_cost_excl_vat'],
            })
            
            colorant_lines_added += 1
            _logger.info(f"      ✅ Added: {qty_litres:.6f} {colorant_product.uom_id.name}")
        
        _logger.info(f"  ✅ BOM completed with {colorant_lines_added} colorant line(s)")
        
        # ============================================
        # STEP 15: UPDATE PRODUCT COSTS FROM BOM
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 15: COST UPDATE FROM BOM")
        _logger.info("=" * 100)
        
        _logger.info(f"  Current product costs:")
        _logger.info(f"    standard_price: {tmpl.standard_price:.2f} KES")
        _logger.info(f"    list_price: {tmpl.list_price:.2f} KES")
        
        _logger.info(f"  BOM costs:")
        _logger.info(f"    total_cost_excl_vat: {bom.total_cost_excl_vat:.2f} KES")
        _logger.info(f"    total_cost_incl_vat: {bom.total_cost_incl_vat:.2f} KES")
        
        # Update cost but preserve selling price
        tmpl.write({
            'standard_price': bom.total_cost_excl_vat,
            'cost_price_excl_vat': bom.total_cost_excl_vat,
        })
        
        _logger.info(f"  ✅ Updated costs from BOM")
        _logger.info(f"    NEW standard_price: {tmpl.standard_price:.2f} KES")
        _logger.info(f"    Selling price preserved: {tmpl.list_price:.2f} KES")
        
        # ============================================
        # STEP 16: MANUFACTURING ORDER CREATION
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 16: MANUFACTURING ORDER CREATION")
        _logger.info("=" * 100)
        
        mo = self.env['mrp.production'].create({
            'product_id': tmpl.product_variant_id.id,
            'bom_id': bom.id,
            'product_qty': 1.0,
            'product_uom_id': uom.id,
            'origin': self.name,
            'is_tinting_mo': True,
        })
        
        _logger.info(f"  ✅ MO Created")
        _logger.info(f"     MO Name: {mo.name}")
        _logger.info(f"     ID: {mo.id}")
        _logger.info(f"     Product: {mo.product_id.display_name}")
        _logger.info(f"     Quantity: {mo.product_qty} {mo.product_uom_id.name}")
        _logger.info(f"     State: {mo.state}")
        
        _logger.info(f"  Confirming MO...")
        mo.action_confirm()
        _logger.info(f"  ✅ MO confirmed - State: {mo.state}")
        
        # Set exact quantities in raw material moves
        _logger.info(f"  Setting exact colorant quantities in stock moves...")
        moves_updated = 0
        for move in mo.move_raw_ids:
            if move.bom_line_id and move.bom_line_id.is_colorant_line:
                exact_qty = move.bom_line_id.product_qty
                move.write({
                    'product_uom_qty': exact_qty,
                    'quantity': exact_qty,
                })
                _logger.info(f"    ✅ {move.product_id.display_name}: {exact_qty:.6f} {move.product_uom.name}")
                moves_updated += 1
        
        _logger.info(f"  ✅ Updated {moves_updated} colorant move(s) with exact quantities")
        
        # ============================================
        # STEP 17: UPDATE SALE ORDER LINE WITH TINTED PRODUCT
        # ============================================
        _logger.info("=" * 100)
        _logger.info("📋 STEP 17: UPDATING SALE ORDER LINE")
        _logger.info("=" * 100)
        _logger.info(f"  🔄 Replacing base product with tinted product in sale order...")
        
        # Store old values for logging
        old_product_id = line.product_id.id
        old_product_name = line.product_id.display_name
        old_price = line.price_unit
        
        _logger.info(f"  OLD LINE STATE:")
        _logger.info(f"    Product ID: {old_product_id}")
        _logger.info(f"    Product Name: {old_product_name}")
        _logger.info(f"    Price Unit: {old_price:.2f} KES")
        _logger.info(f"    Quantity: {line.product_uom_qty}")
        
        # Update line with new product while preserving price
        try:
            line.write({
                'product_id': tmpl.product_variant_id.id,
                'price_unit': original_selling_price,  # ← PRESERVE ORIGINAL PRICE
                'name': f"{tmpl.name}\n{line.name}",  # Append original description
            })
            _logger.info(f"  ✅ Sale order line updated successfully")
        except Exception as e:
            _logger.error(f"  ❌ ERROR updating sale order line: {str(e)}")
            _logger.error(f"     Exception type: {type(e).__name__}")
            import traceback
            _logger.error(f"     Traceback:\n{traceback.format_exc()}")
            raise UserError(_("Failed to update sale order line: %s") % str(e))
        
        _logger.info(f"  NEW LINE STATE:")
        _logger.info(f"    Product ID: {line.product_id.id}")
        _logger.info(f"    Product Name: {line.product_id.display_name}")
        _logger.info(f"    Price Unit: {line.price_unit:.2f} KES")
        _logger.info(f"    Quantity: {line.product_uom_qty}")
        
        # Verify price was preserved
        _logger.info("=" * 100)
        _logger.info("💰 PRICE PRESERVATION VERIFICATION")
        _logger.info("=" * 100)
        _logger.info(f"  Original Selling Price: {original_selling_price:.2f} KES")
        _logger.info(f"  Current Line Price: {line.price_unit:.2f} KES")
        
        if abs(line.price_unit - original_selling_price) > 0.01:
            _logger.error(f"  ❌ PRICE DRIFT DETECTED!")
            _logger.error(f"     Expected: {original_selling_price:.2f} KES")
            _logger.error(f"     Got: {line.price_unit:.2f} KES")
            _logger.error(f"     Difference: {line.price_unit - original_selling_price:.2f} KES")
            
            # Force correct price
            _logger.info(f"  🔧 Forcing price correction...")
            line.write({'price_unit': original_selling_price})
            _logger.info(f"  ✅ Price corrected to: {line.price_unit:.2f} KES")
        else:
            _logger.info(f"  ✅ PRICE PRESERVED CORRECTLY!")
        
        _logger.info("=" * 100)
        
        # ============================================
        # STEP 18: FINAL SUMMARY
        # ============================================
        _logger.info("=" * 100)
        _logger.info("🎉 QUOTATION → PRODUCT CREATION COMPLETE")
        _logger.info("=" * 100)
        _logger.info(f"  Sale Order: {self.name}")
        _logger.info(f"  Customer: {self.partner_id.name}")
        _logger.info("")
        _logger.info(f"  ✅ PRODUCT CREATED:")
        _logger.info(f"     ID: {tmpl.id}")
        _logger.info(f"     Name: {tmpl.name}")
        _logger.info(f"     Type: {getattr(tmpl, 'type', 'N/A')}")
        _logger.info(f"     Tracking: {getattr(tmpl, 'tracking', 'N/A')}")
        _logger.info(f"     Storable: {'YES' if is_storable else 'NO'}")
        _logger.info("")
        _logger.info(f"  ✅ BOM CREATED:")
        _logger.info(f"     ID: {bom.id}")
        _logger.info(f"     Lines: 1 base + {colorant_lines_added} colorants")
        _logger.info(f"     Cost: {bom.total_cost_incl_vat:.2f} KES (incl VAT)")
        _logger.info("")
        _logger.info(f"  ✅ MO CREATED:")
        _logger.info(f"     Name: {mo.name}")
        _logger.info(f"     ID: {mo.id}")
        _logger.info(f"     State: {mo.state}")
        _logger.info("")
        _logger.info(f"  ✅ SALE ORDER LINE UPDATED:")
        _logger.info(f"     Old Product: {old_product_name}")
        _logger.info(f"     New Product: {line.product_id.display_name}")
        _logger.info(f"     Price Preserved: {line.price_unit:.2f} KES")
        _logger.info("")
        _logger.info(f"  💰 PRICING:")
        _logger.info(f"     Cost: {tmpl.standard_price:.2f} KES")
        _logger.info(f"     Selling: {tmpl.list_price:.2f} KES")
        _logger.info(f"     Profit: {profit:.2f} KES")
        _logger.info(f"     Margin: {margin:.2f}%")
        _logger.info("=" * 100)
        
        # ============================================
        # RETURN ACTION: OPEN MO FORM
        # ============================================
        return {
            'type': 'ir.actions.act_window',
            'name': _('Manufacturing Order'),
            'res_model': 'mrp.production',
            'res_id': mo.id,
            'view_mode': 'form',
            'target': 'current',
        }


class SaleOrderLine(models.Model):
    """Extension to store tinting formula and cost snapshots"""
    _inherit = 'sale.order.line'

    # ============================================
    # TINTING FIELDS
    # ============================================
    is_tinted_product_line = fields.Boolean(
        string='Is Tinted Product Line',
        default=False
    )

    tinting_formula_json = fields.Text(
        string='Tinting Formula (JSON)',
        help='Colorant shots stored as JSON'
    )

    # ============================================
    # BASE PRODUCT TRACKING
    # ============================================
    base_product_id = fields.Many2one(
        'product.product',
        string='Base Product',
        help='Base product used for tinting (before colorants added)',
        copy=False
    )

    base_product_uom_id = fields.Many2one(
        'uom.uom',
        string='Base Product UOM',
        help='Unit of measure for base product',
        copy=False
    )

    # ============================================
    # COST SNAPSHOTS
    # ============================================
    quoted_cost_at_creation = fields.Float(
        string='Quoted Cost (Snapshot)',
        digits='Product Price',
        readonly=True,
        copy=False
    )

    quoted_base_cost = fields.Float(
        string='Quoted Base Cost',
        digits='Product Price',
        readonly=True,
        copy=False
    )

    quoted_colorant_cost = fields.Float(
        string='Quoted Colorant Cost',
        digits='Product Price',
        readonly=True,
        copy=False
    )

    # ============================================
    # METADATA
    # ============================================
    colour_code_id = fields.Many2one('colour.code', string='Colour Code')
    fandeck_id = fields.Many2one('colour.fandeck', string='Fandeck')
    base_category_id = fields.Many2one('product.category', string='Base Category')

    # ============================================
    # PRICE PROTECTION
    # ============================================
    price_locked = fields.Boolean(
        string="Price Locked (Manual)",
        default=False,
        copy=False,
        help="When checked, prevents automatic recomputation of unit price from product, pricelist or other rules"
    )

    # === DIAGNOSTIC LOGGING FOR PRICE SWAPPING ISSUE ===

    @api.model
    def create(self, vals):
        _logger.info(
            "[PRICE DIAG] Creating sale order line - initial vals: price_unit=%s, product_id=%s, sequence=%s, price_locked=%s",
            vals.get('price_unit'),
            vals.get('product_id'),
            vals.get('sequence'),
            vals.get('price_locked')
        )
        line = super(SaleOrderLine, self).create(vals)

        _logger.info(
            "[PRICE DIAG] Line created (ID %s) - product=%s, price_unit=%.2f, price_locked=%s",
            line.id,
            line.product_id.display_name if line.product_id else "None",
            line.price_unit,
            line.price_locked
        )
        return line

    def write(self, vals):
        if 'price_unit' in vals or 'product_id' in vals or 'order_id' in vals or 'price_locked' in vals:
            old_price = self.price_unit
            old_product = self.product_id.display_name if self.product_id else "None"
            old_locked = self.price_locked

            _logger.info(
                "[PRICE DIAG] WRITE attempt on line %s - old price=%.2f → new price=%s | "
                "product change=%s | price_locked change=%s → %s | vals=%s | context=%s",
                self.id,
                old_price,
                vals.get('price_unit'),
                'product_id' in vals,
                old_locked,
                vals.get('price_locked'),
                vals,
                self.env.context
            )

        res = super(SaleOrderLine, self).write(vals)

        if 'price_unit' in vals or 'product_id' in vals or 'price_locked' in vals:
            _logger.info(
                "[PRICE DIAG] AFTER WRITE on line %s - final price_unit=%.2f (was %.2f) | "
                "product=%s | price_locked=%s",
                self.id,
                self.price_unit,
                old_price,
                self.product_id.display_name if self.product_id else "None",
                self.price_locked
            )

        return res

    @api.depends('product_id', 'product_uom_qty', 'product_uom', 'price_unit', 'tax_id', 'discount')
    def _compute_price_unit(self):
        _logger.info(
            "[PRICE DIAG] _compute_price_unit triggered on lines %s - context=%s",
            self.ids,
            self.env.context
        )

        for line in self:
            if line.price_locked:
                _logger.info(
                    "[PRICE DIAG] Skipping recompute - price_locked=True on line %s (preserved price: %.2f)",
                    line.id, line.price_unit
                )
                continue  # Do NOT recompute → keep the manual price

            old_price = line.price_unit
            super(SaleOrderLine, line)._compute_price_unit()

            if line.price_unit != old_price:
                _logger.warning(
                    "[PRICE DIAG] PRICE RECOMPUTED on line %s - %.2f → %.2f | product=%s | locked=%s",
                    line.id,
                    old_price,
                    line.price_unit,
                    line.product_id.display_name if line.product_id else "None",
                    line.price_locked
                )