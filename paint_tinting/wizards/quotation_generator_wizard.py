# -*- coding: utf-8 -*-
"""
Quotation Generator Wizard
===========================

Loads products from cost comparison wizard and allows quotation creation.
All products are AUTO-CHECKED - user only needs to enter customer and prices.

Key Features:
- Loads ALL products from cost comparison wizard
- Products pre-selected (auto-checked)
- User enters customer and manual prices
- Creates quotation with data from comparison wizard (not this wizard)
- Validates manual pricing before creation
- Captures base product and UOM for tinted products

Author: Crown Kenya PLC / Mzaramo Paints
Date: 2025
Odoo Version: 18 Enterprise
"""

import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class QuotationGeneratorLine(models.TransientModel):
    """
    Individual product line in quotation generator.
    
    IMPORTANT: This model stores ONLY:
    - Product selection (selected checkbox)
    - Manual selling price
    - Reference to comparison line
    
    Costs are READ from comparison_line_id (single source of truth)
    """
    _name = 'quotation.generator.line'
    _description = 'Quotation Generator Line'
    _order = 'id'
    
    # ============================================
    # RELATIONSHIP
    # ============================================
    wizard_id = fields.Many2one(
        'quotation.generator.wizard',
        string='Quotation Wizard',
        required=True,
        ondelete='cascade'
    )
    
    comparison_line_id = fields.Many2one(
        'cost.comparison.line',
        string='Comparison Line',
        required=True,
        ondelete='cascade',
        help='Reference to comparison line (source of truth for costs)'
    )
    
    # ============================================
    # PRODUCT INFORMATION (from comparison line)
    # ============================================
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        related='comparison_line_id.product_id',
        readonly=True,
        store=True
    )
    
    brand_name = fields.Char(
        string='Brand',
        related='comparison_line_id.brand_name',
        readonly=True
    )
    
    # ============================================
    # SELECTION CHECKBOX
    # ============================================
    selected = fields.Boolean(
        string='Select',
        default=True,  # ← AUTO-CHECKED!
        help='Check to include this product in quotation'
    )
    
    # ============================================
    # COST INFORMATION (READ from comparison line)
    # ============================================
    base_cost_incl_vat = fields.Float(
        string='Base Cost',
        related='comparison_line_id.base_cost_incl_vat',
        readonly=True,
        digits='Product Price'
    )
    
    colorant_cost_incl_vat = fields.Float(
        string='Colorant Cost',
        related='comparison_line_id.colorant_cost_incl_vat',
        readonly=True,
        digits='Product Price'
    )
    
    total_cost_incl_vat = fields.Float(
        string='Total Cost',
        related='comparison_line_id.total_cost_incl_vat',
        readonly=True,
        digits='Product Price'
    )
    
    # ============================================
    # SELLING PRICE (MANUAL INPUT REQUIRED)
    # ============================================
    selling_price_manual = fields.Float(
        string='Selling Price (Manual)',
        digits='Product Price',
        help='Enter selling price manually - REQUIRED before quotation creation'
    )
    
    price_manually_set = fields.Boolean(
        string='Price Manually Set',
        default=False,
        help='True if user has entered a price manually'
    )
    
    # ============================================
    # PROFIT ANALYSIS (COMPUTED)
    # ============================================
    profit_amount = fields.Float(
        string='Profit',
        compute='_compute_profit',
        digits='Product Price',
        help='Selling Price - Total Cost'
    )
    
    profit_margin_percent = fields.Float(
        string='Margin %',
        compute='_compute_profit',
        digits=(5, 2),
        help='(Profit / Selling Price) × 100'
    )
    
    # ============================================
    # COMPUTE METHODS
    # ============================================
    @api.depends('selling_price_manual', 'total_cost_incl_vat')
    def _compute_profit(self):
        """Calculate profit and margin"""
        for line in self:
            if line.selling_price_manual and line.total_cost_incl_vat:
                line.profit_amount = line.selling_price_manual - line.total_cost_incl_vat
                
                if line.selling_price_manual > 0:
                    line.profit_margin_percent = (
                        line.profit_amount / line.selling_price_manual
                    ) * 100
                else:
                    line.profit_margin_percent = 0.0
            else:
                line.profit_amount = 0.0
                line.profit_margin_percent = 0.0
    
    # ============================================
    # ONCHANGE METHODS
    # ============================================
    @api.onchange('selling_price_manual')
    def _onchange_selling_price_manual(self):
        """Mark price as manually set when user enters value"""
        for line in self:
            if line.selling_price_manual > 0:
                line.price_manually_set = True
                
    @api.onchange('selling_price_manual')
    def _onchange_selling_price_validate_cost(self):
        """
        NEW: Warn immediately if manual price is below total cost.
        Fires on every keystroke so user sees warning in real time.
        """
        for line in self:
            if not line.selling_price_manual or not line.total_cost_incl_vat:
                continue

            if line.selling_price_manual < line.total_cost_incl_vat:
                shortage = line.total_cost_incl_vat - line.selling_price_manual
                brand = line.brand_name or line.product_id.display_name or 'Unknown'
                _logger.warning(
                    f"⚠ Quotation Line [{brand}]: "
                    f"price {line.selling_price_manual:.2f} < "
                    f"cost {line.total_cost_incl_vat:.2f} KES"
                )
                return {
                    'warning': {
                        'title': f'⚠ Loss-Making Price — {brand}',
                        'message': (
                            f"Selling price ({line.selling_price_manual:.2f} KES) is "
                            f"BELOW total cost ({line.total_cost_incl_vat:.2f} KES).\n\n"
                            f"Loss per unit:       {shortage:.2f} KES\n"
                            f"Break-even minimum:  {line.total_cost_incl_vat:.2f} KES\n\n"
                            f"Please enter a price at or above the total cost."
                        )
                    }
                }


class QuotationGeneratorWizard(models.TransientModel):
    """
    Main quotation generator wizard.
    
    Loads products from cost comparison wizard (all auto-checked).
    User enters customer and manual prices.
    Creates quotation with data from comparison wizard.
    """
    _name = 'quotation.generator.wizard'
    _description = 'Quotation Generator Wizard'
    
    # ============================================
    # SOURCE DATA FIELDS
    # ============================================
    source_wizard_id = fields.Many2one(
        'cost.comparison.wizard',
        string='Source Comparison',
        required=True,
        readonly=True,
        help='Cost comparison wizard that opened this quotation generator'
    )
    
    colour_code_id = fields.Many2one(
        'colour.code',
        string='Colour Code',
        required=True,
        readonly=True
    )
    
    fandeck_id = fields.Many2one(
        'colour.fandeck',
        string='Fandeck',
        required=True,
        readonly=True
    )
    
    base_category_id = fields.Many2one(
        'product.category',
        string='Category',
        required=True,
        readonly=True
    )
    
    # NEW: Temporary storage to reliably map back to original comparison lines
    comparison_line_ids_json = fields.Text(
        string='Comparison Line IDs (JSON)',
        help='JSON list of original comparison line IDs in display order'
    )
    
    # ============================================
    # CUSTOMER SELECTION
    # ============================================
    # MODE SELECTION
    # ============================================
    quotation_mode = fields.Selection([
        ('new', 'Create New Quotation'),
        ('existing', 'Add to Existing Quotation'),
    ], string='Mode', default='new', required=True)

    existing_sale_order_id = fields.Many2one(
        'sale.order',
        string='Existing Quotation',
        domain="[('state', 'in', ['draft', 'sent'])]",
        help='Select an existing quotation to add products to'
    )

    # ============================================
    # CUSTOMER SELECTION
    # ============================================
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=False,
        domain="[('customer_rank', '>', 0)]",
        help='Customer for this quotation'
    )

    new_customer_name = fields.Char(
        string='New Customer Name',
        help='Name to use when creating a customer from this quotation wizard'
    )

    new_customer_phone = fields.Char(
        string='Phone'
    )

    new_customer_email = fields.Char(
        string='Email'
    )

    # ============================================
    # PRODUCT LINES
    # ============================================
    line_ids = fields.One2many(
        'quotation.generator.line',
        'wizard_id',
        string='Products'
    )
    
    # ============================================
    # STATISTICS
    # ============================================
    total_selected = fields.Integer(
        string='Selected Products',
        compute='_compute_statistics'
    )
    
    total_selected_with_price = fields.Integer(
        string='Products with Price',
        compute='_compute_statistics'
    )
    
    can_generate_quotation = fields.Boolean(
        string='Can Generate',
        compute='_compute_can_generate'
    )
    
    # ============================================
    # COMPUTE METHODS
    # ============================================
    @api.depends('line_ids.selected')
    def _compute_statistics(self):
        """Calculate selection statistics"""
        _logger.info("🔢 Computing quotation statistics...")
        for wizard in self:
            selected_lines = wizard.line_ids.filtered('selected')
            wizard.total_selected = len(selected_lines)
            wizard.total_selected_with_price = len(
                selected_lines.filtered('price_manually_set')
            )
            _logger.info(f"  Selected: {wizard.total_selected}, With Price: {wizard.total_selected_with_price}")
    
    @api.depends('total_selected', 'total_selected_with_price', 'partner_id',
                 'quotation_mode', 'existing_sale_order_id')
    def _compute_can_generate(self):
        """Check if quotation can be generated"""
        for wizard in self:
            prices_ready = (
                wizard.total_selected > 0 and
                wizard.total_selected == wizard.total_selected_with_price
            )
            if wizard.quotation_mode == 'new':
                can_generate = bool(wizard.partner_id) and prices_ready
            else:
                can_generate = bool(wizard.existing_sale_order_id) and prices_ready
            wizard.can_generate_quotation = can_generate
            _logger.info(f"  Can generate quotation: {can_generate}")
    
    # ============================================
    # ONCHANGE METHODS
    # ============================================
    @api.onchange('existing_sale_order_id')
    def _onchange_existing_sale_order_id(self):
        if self.existing_sale_order_id:
            self.partner_id = self.existing_sale_order_id.partner_id

    def action_create_customer_from_wizard(self):
        """Create a customer profile from the quotation wizard and select it."""
        self.ensure_one()

        customer_name = (self.new_customer_name or '').strip()
        if not customer_name:
            raise ValidationError("Please enter the new customer name.")

        partner = self.env['res.partner'].create({
            'name': customer_name,
            'phone': (self.new_customer_phone or '').strip() or False,
            'email': (self.new_customer_email or '').strip() or False,
            'customer_rank': 1,
        })

        self.partner_id = partner.id
        self.new_customer_name = False
        self.new_customer_phone = False
        self.new_customer_email = False

        _logger.info(
            "Created customer %s (ID: %s) from quotation generator wizard %s",
            partner.display_name,
            partner.id,
            self.id,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate Quotation',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ============================================
    # DEFAULT_GET: LOAD LINES FROM COMPARISON + STORE IDs
    # ============================================
    @api.model
    def default_get(self, fields_list):
        """
        Load product lines from cost comparison wizard using Command syntax.
        
        CRITICAL: Guard clause prevents duplicate loading on web_save.
        Only loads on NEW wizard creation, not on web_save.
        
        Also stores original comparison line IDs for reliable mapping.
        """
        res = super(QuotationGeneratorWizard, self).default_get(fields_list)
        
        source_wizard_id = self.env.context.get('default_source_wizard_id')
        
        # Guard clause - prevent duplicate loading
        if not source_wizard_id:
            _logger.warning("⚠️ No source wizard ID in context")
            return res
        
        # If lines already exist in result, don't reload (web_save scenario)
        if 'line_ids' in res and res['line_ids']:
            _logger.info("  ✅ Lines already loaded, skipping default_get reload")
            return res
        
        _logger.info("=" * 80)
        _logger.info("🔄 QUOTATION GENERATOR - LOADING PRODUCTS FROM COMPARISON WIZARD")
        _logger.info("=" * 80)
        
        source_wizard = self.env['cost.comparison.wizard'].browse(source_wizard_id)
        
        if not source_wizard.exists():
            _logger.error(f"❌ Source wizard {source_wizard_id} not found!")
            return res
        
        _logger.info(f"  📊 Source wizard ID: {source_wizard.id}")
        _logger.info(f"  📦 Comparison lines available: {len(source_wizard.comparison_line_ids)}")
        
        # CREATE LINES USING COMMAND SYNTAX - (0, 0, {...})
        # All products AUTO-CHECKED (selected=True)
        line_vals = []
        
        for idx, comp_line in enumerate(source_wizard.comparison_line_ids, 1):
            if not comp_line.product_id:
                _logger.warning(f"  ⚠️ Line {idx}: Skipping - no product_id")
                continue
            
            line_vals.append((0, 0, {
                'comparison_line_id': comp_line.id,  # ← Reference to source
                'selected': True,                    # ← AUTO-CHECKED!
                'selling_price_manual': 0.0,
                'price_manually_set': False,
            }))
            
            _logger.info(f"  ✅ Line {idx}: {comp_line.product_id.display_name} (AUTO-CHECKED)")
            _logger.info(f"      Brand: {comp_line.brand_name}")
            _logger.info(f"      Total Cost: {comp_line.total_cost_incl_vat:.2f} KES")
        
        res['line_ids'] = line_vals
        
        # NEW: Store original comparison line IDs in order for safe lookup later
        comparison_ids = [comp_line.id for comp_line in source_wizard.comparison_line_ids]
        res['comparison_line_ids_json'] = json.dumps(comparison_ids)
        _logger.info(f"  📋 Stored {len(comparison_ids)} original comparison line IDs")
        
        _logger.info(f"  🎯 Successfully loaded {len(line_vals)} product lines (all auto-checked)")
        _logger.info("=" * 80)
        
        return res
    
    # ============================================
    # VALIDATION METHOD
    # ============================================
    def _validate_manual_prices(self):
        """Validate that all selected products have manually set prices"""
        self.ensure_one()
        
        _logger.info("🔍 VALIDATING MANUAL PRICES...")
        
        selected_lines = self.line_ids.filtered('selected')
        
        if not selected_lines:
            _logger.error("❌ No products selected!")
            raise ValidationError(
                "No Products Selected!\n\n"
                "Please select at least one product by checking the 'Select' checkbox."
            )
        
        _logger.info(f"  📊 Total selected products: {len(selected_lines)}")
        
        missing_prices = selected_lines.filtered(lambda l: not l.price_manually_set or l.selling_price_manual <= 0)
        
        if missing_prices:
            product_names = '\n'.join([f"  • {line.comparison_line_id.product_id.display_name}" for line in missing_prices])
            
            _logger.error(f"❌ {len(missing_prices)} product(s) missing manual price:")
            _logger.error(product_names)
            
            raise ValidationError(
                f"Manual Selling Price Required!\n\n"
                f"The following {len(missing_prices)} product(s) need manual price entry:\n\n"
                f"{product_names}\n\n"
                f"Please enter selling price manually for each selected product."
            )
        
        _logger.info(f"  ✅ All {len(selected_lines)} selected products have valid manual prices")
        
        # Log price summary
        for line in selected_lines:
            _logger.info(f"    • {line.comparison_line_id.product_id.display_name}: {line.selling_price_manual:.2f} KES")
            
        
            
            
    def _validate_no_losses(self):
        """
        NEW: Hard-block quotation creation if any selected line
        has a selling price below its total cost (loss-making line).

        Called from action_generate_quotation before sale order creation.
        """
        self.ensure_one()

        _logger.info("🔍 VALIDATING NO LOSS-MAKING LINES...")

        selected_lines = self.line_ids.filtered('selected')

        loss_lines = selected_lines.filtered(
            lambda l: l.price_manually_set
            and l.selling_price_manual < l.total_cost_incl_vat
        )

        if not loss_lines:
            _logger.info(
                f"  ✅ All {len(selected_lines)} selected lines are "
                f"priced at or above cost"
            )
            return

        # Build detailed breakdown for the error message
        lines_detail = '\n'.join([
            f"  • {l.brand_name or l.product_id.display_name or 'Unknown'}:\n"
            f"      Price:  {l.selling_price_manual:.2f} KES\n"
            f"      Cost:   {l.total_cost_incl_vat:.2f} KES\n"
            f"      Loss:   {l.total_cost_incl_vat - l.selling_price_manual:.2f} KES"
            for l in loss_lines
        ])

        total_loss = sum(
            l.total_cost_incl_vat - l.selling_price_manual
            for l in loss_lines
        )

        _logger.error(
            f"❌ {len(loss_lines)} loss-making line(s) detected:\n{lines_detail}"
        )
        _logger.error(f"   Total potential loss: {total_loss:.2f} KES")

        raise ValidationError(
            f"Cannot create quotation — {len(loss_lines)} product(s) "
            f"are priced below cost:\n\n"
            f"{lines_detail}\n\n"
            f"Total potential loss: {total_loss:.2f} KES\n\n"
            f"Please increase all selling prices to at least their "
            f"respective total costs before generating this quotation."
        )
    
    # ============================================
    # BROWSE QUOTATIONS - opens Sales list to help user pick the right SO
    # ============================================
    def action_browse_quotations(self):
        """Open the Sales quotations list as a dialog so the user can
        browse customer names, totals and status before selecting."""
        action = self.env.ref('sale.action_quotations_with_onboarding').sudo().read()[0]
        action['target'] = 'new'
        action['view_mode'] = 'list,form'
        action['views'] = [(False, 'list'), (False, 'form')]
        action['domain'] = [('state', 'in', ['draft', 'sent'])]
        action['context'] = {}
        return action

    # ============================================
    # QUOTATION GENERATION METHOD - FIXED
    # ============================================
    def action_generate_quotation(self):
        """
        Generate quotation from selected products.
        
        FIXED: Uses stored comparison line IDs to reliably fetch original comparison lines
        instead of depending on transient quot_line.comparison_line_id which may not resolve correctly.
        
        Process:
        1. Validate customer and selections
        2. Validate manual prices
        3. Get formula from comparison wizard (scaled or original)
        4. For each selected line:
           - Fetch original comparison line by position
           - Read all required data from comparison line
           - Create sale order line with full tinting metadata
        """
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("📝 GENERATING QUOTATION - START")
        _logger.info("=" * 80)
        
        # ============================================
        # STEP 1: VALIDATION
        # ============================================
        _logger.info("📋 STEP 1: VALIDATION")
        _logger.info("-" * 80)

        if self.quotation_mode == 'new':
            if not self.partner_id:
                raise UserError("Please select a customer first!")
            _logger.info(f"  ✅ Customer: {self.partner_id.name} (ID: {self.partner_id.id})")
        else:
            if not self.existing_sale_order_id:
                raise UserError("Please select an existing quotation!")
            _logger.info(f"  ✅ Existing quotation: {self.existing_sale_order_id.name} (ID: {self.existing_sale_order_id.id})")
        
        self._validate_manual_prices()
        
         # ── NEW: hard-block any loss-making lines ──────────────────
        self._validate_no_losses()
        # ── END NEW ───────────────────────────────────────────────
        
        selected_lines = self.line_ids.filtered('selected')
        
        _logger.info(f"  ✅ Selected products: {len(selected_lines)}")
        _logger.info(f"  ✅ Colour: {self.colour_code_id.code} - {self.colour_code_id.name}")
        _logger.info(f"  ✅ Fandeck: {self.fandeck_id.name}")
        _logger.info(f"  ✅ Category: {self.base_category_id.name}")
        
        # ============================================
        # STEP 2: GET FORMULA FROM SOURCE WIZARD
        # ============================================
        _logger.info("📋 STEP 2: FORMULA RETRIEVAL")
        _logger.info("-" * 80)
        
        source_wizard = self.source_wizard_id
        
        if source_wizard.show_scaled_products and source_wizard.scaled_colorant_shots_json:
            formula_json = source_wizard.scaled_colorant_shots_json
            _logger.info(f"  ✅ Using SCALED formula")
            _logger.info(f"     Scale factor: {source_wizard.scale_factor:.2f}×")
        else:
            formula_json = source_wizard.colorant_shots_json
            _logger.info(f"  ✅ Using ORIGINAL formula")
        
        _logger.info(f"     Formula: {formula_json[:200]}...")
        
        # ============================================
        # STEP 3: CREATE OR FETCH SALE ORDER
        # ============================================
        _logger.info("📋 STEP 3: SALE ORDER")
        _logger.info("-" * 80)

        if self.quotation_mode == 'new':
            sale_order = self.env['sale.order'].create({
                'partner_id': self.partner_id.id,
                'date_order': fields.Datetime.now(),
                'pricelist_id': self.partner_id.property_product_pricelist.id,
                'note': (
                    f"Tinted Paint Quotation\n"
                    f"Colour: {self.colour_code_id.code} - {self.colour_code_id.name}\n"
                    f"Fandeck: {self.fandeck_id.name}\n"
                    f"Category: {self.base_category_id.name}"
                ),
            })
            _logger.info(f"  ✅ Sale order created: {sale_order.name} (ID: {sale_order.id})")
        else:
            sale_order = self.existing_sale_order_id
            _logger.info(f"  ✅ Using existing sale order: {sale_order.name} (ID: {sale_order.id})")
        
        # ============================================
        # STEP 4: CREATE SALE ORDER LINES - FIXED MAPPING
        # ============================================
        _logger.info("📋 STEP 4: SALE ORDER LINES CREATION")
        _logger.info("-" * 80)
        
        lines_created = 0

        for idx, quot_line in enumerate(self.line_ids, 1):
            if not quot_line.selected:
                continue

            comp_line = quot_line.comparison_line_id
            
            if not comp_line:
                raise UserError(
                    "A quotation line is missing its source comparison line. "
                    "Please close and reopen the quotation generator."
                )
            
            _logger.info(f"  🔧 Processing line {idx+1}/{len(selected_lines)}")
            _logger.info(f"     Comparison line ID: {comp_line.id}")
            _logger.info(f"     Product: {comp_line.product_id.display_name} (ID: {comp_line.product_id.id})")
            
            if comp_line.base_product_id:
                _logger.info(f"     Base Product: {comp_line.base_product_id.display_name} (ID: {comp_line.base_product_id.id})")
            else:
                _logger.warning(f"     ⚠️ No base_product_id in comparison line!")
            
            if comp_line.base_product_uom_id:
                _logger.info(f"     Base UOM: {comp_line.base_product_uom_id.name} (ID: {comp_line.base_product_uom_id.id})")
            else:
                _logger.warning(f"     ⚠️ No base_product_uom_id in comparison line!")
            
            _logger.info(f"     Brand: {comp_line.brand_name}")
            _logger.info(f"     Manual Price: {quot_line.selling_price_manual:.2f} KES")
            _logger.info(f"     Base Cost: {comp_line.base_cost_incl_vat:.2f} KES")
            _logger.info(f"     Colorant Cost: {comp_line.colorant_cost_incl_vat:.2f} KES")
            _logger.info(f"     Total Cost: {comp_line.total_cost_incl_vat:.2f} KES")
            
            description = (
                f"{comp_line.product_id.display_name}\n"
                f"Colour: {self.colour_code_id.code} - {self.colour_code_id.name}"
            )
            
            order_line = self.env['sale.order.line'].create({
                'order_id': sale_order.id,
                'product_id': comp_line.product_id.id,
                'name': description,
                'product_uom_qty': 1.0,
                'product_uom': comp_line.product_id.uom_id.id,
                'price_unit': quot_line.selling_price_manual,
                'price_locked': True,
                
                # ============================================
                # FIXED: All tinting metadata now correctly written
                # ============================================
                'tinting_formula_json': formula_json,
                'quoted_cost_at_creation': comp_line.total_cost_incl_vat,
                'quoted_base_cost': comp_line.base_cost_incl_vat,
                'quoted_colorant_cost': comp_line.colorant_cost_incl_vat,
                
                'base_product_id': comp_line.base_product_id.id if comp_line.base_product_id else False,
                'base_product_uom_id': comp_line.base_product_uom_id.id if comp_line.base_product_uom_id else False,
                
                'is_tinted_product_line': True,
                'colour_code_id': self.colour_code_id.id,
                'fandeck_id': self.fandeck_id.id,
                'base_category_id': self.base_category_id.id,
            })
            
            lines_created += 1
            
            _logger.info(f"  ✅ Sale order line created (ID: {order_line.id})")
            _logger.info(f"     Base Product: {order_line.base_product_id.display_name if order_line.base_product_id else 'N/A'}")
            _logger.info(f"     Base UOM: {order_line.base_product_uom_id.name if order_line.base_product_uom_id else 'N/A'}")
            _logger.info(f"     Selling Price: {order_line.price_unit:.2f} KES")
            _logger.info(f"     Quoted Total Cost: {order_line.quoted_cost_at_creation:.2f} KES")
            _logger.info(f"     Tinting Formula stored: {bool(order_line.tinting_formula_json)}")
        
        # ============================================
        # STEP 5: ADD CHATTER MESSAGE
        # ============================================
        _logger.info("📋 STEP 5: CHATTER MESSAGE")
        _logger.info("-" * 80)
        
        action_label = "Tinted Paint Products Added" if self.quotation_mode == 'existing' else "Tinted Paint Quotation Created"
        sale_order.message_post(
            body=f"""
            <strong>{action_label}</strong><br/>
            <ul>
                <li>Colour: {self.colour_code_id.code} - {self.colour_code_id.name}</li>
                <li>Fandeck: {self.fandeck_id.name}</li>
                <li>Products: {lines_created}</li>
                <li>All prices manually entered and validated ✓</li>
                <li>Formula and cost snapshots stored for integrity checking</li>
                <li>Base product tracking enabled for all lines</li>
                {f'<li>Volume scaled: {source_wizard.source_volume_litres:.0f}L → {source_wizard.target_volume_litres:.0f}L ({source_wizard.scale_factor:.2f}×)</li>' if source_wizard.show_scaled_products else ''}
            </ul>
            """,
            subject=action_label
        )
        
        _logger.info(f"  ✅ Chatter message posted to sale order")
        
        _logger.info("=" * 80)
        _logger.info(f"✅ QUOTATION GENERATION COMPLETE")
        _logger.info(f"   Sale Order: {sale_order.name} (ID: {sale_order.id})")
        _logger.info(f"   Customer: {self.partner_id.name}")
        _logger.info(f"   Products: {lines_created}")
        _logger.info(f"   Subtotal: {sale_order.amount_untaxed:.2f} KES")
        _logger.info(f"   Tax: {sale_order.amount_tax:.2f} KES")
        _logger.info(f"   Total: {sale_order.amount_total:.2f} KES")
        _logger.info("=" * 80)
        
        # ============================================
        # STEP 6: RETURN ACTION TO OPEN SALE ORDER
        # ============================================
        window_name = f'Quotation: {sale_order.name}'
        return {
            'type': 'ir.actions.act_window',
            'name': window_name,
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'view_mode': 'form',
            'target': 'current',
        }
