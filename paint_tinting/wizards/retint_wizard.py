# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
import re
import json

_logger = logging.getLogger(__name__)


class RetintWizardOriginalLine(models.TransientModel):
    """
    Display original formula used in the tinted product (READ-ONLY)
    Shows customer what colorants were in the original mix
    """
    _name = 'retint.wizard.original.line'
    _description = 'Re-Tint Wizard - Original Formula Line (Read-Only)'
    _order = 'colorant_code'

    wizard_id = fields.Many2one('retint.wizard', required=True, ondelete='cascade')
    colorant_name = fields.Char(string='Colorant', readonly=True)
    colorant_code = fields.Char(string='Code', readonly=True)
    original_shots = fields.Float(string='Original Shots', readonly=True, digits=(10, 2))
    original_ml = fields.Float(string='Original ml', readonly=True, digits=(10, 3))


class RetintWizardColorantLine(models.TransientModel):
    """
    ADDITIONAL colorants to add to the existing tinted product
    User enters NEW shots to add (not total shots)
    """
    _name = 'retint.wizard.colorant.line'
    _description = 'Re-Tint Wizard - Additional Colorant Line'
    _order = 'colorant_code'

    wizard_id = fields.Many2one('retint.wizard', required=True, ondelete='cascade')
    colorant_id = fields.Many2one(
        'product.product',
        string='Colorant',
        domain="[('product_tmpl_id.is_colorant', '=', True)]",
        help='Colorant product (C1–C16)'
    )
    colorant_name = fields.Char(compute='_compute_colorant_name', store=True, readonly=True)
    colorant_code = fields.Char(related='colorant_id.product_tmpl_id.colorant_code', readonly=True, store=True)
    
    # ADDITIONAL shots (not total)
    additional_shots = fields.Float(
        string='Additional Shots',
        digits=(10, 2),
        default=0.0,
        help='Additional shots to ADD to existing tinted product'
    )
    
    ml_volume = fields.Float(compute='_compute_ml_volume', store=True, digits=(10, 3))
    qty_litres = fields.Float(compute='_compute_qty_litres', store=True, digits=(10, 6))
    available_stock = fields.Float(compute='_compute_available_stock', digits=(10, 4))
    stock_warning = fields.Boolean(compute='_compute_stock_warning')
    
    unit_cost_excl_vat = fields.Float(related='colorant_id.standard_price', readonly=True, digits='Product Price')
    unit_cost_incl_vat = fields.Float(compute='_compute_unit_cost_incl_vat', digits='Product Price')
    line_cost_excl_vat = fields.Float(compute='_compute_line_costs', digits='Product Price')
    line_cost_incl_vat = fields.Float(compute='_compute_line_costs', digits='Product Price')

    @api.depends('additional_shots')
    def _compute_ml_volume(self):
        """Convert additional shots to milliliters (1 shot = 0.616 ml)"""
        _logger.debug("🔄 [RETINT LINE] Computing ml_volume for additional colorant lines")
        for line in self:
            line.ml_volume = line.additional_shots * 0.616
            if line.additional_shots > 0:
                _logger.debug(f"  [RETINT LINE] {line.colorant_code}: {line.additional_shots} shots = {line.ml_volume} ml")

    @api.depends('ml_volume')
    def _compute_qty_litres(self):
        """Convert milliliters to litres (ml ÷ 1000)"""
        _logger.debug("🔄 [RETINT LINE] Computing qty_litres for additional colorant lines")
        for line in self:
            line.qty_litres = line.ml_volume / 1000.0
            if line.additional_shots > 0:
                _logger.debug(f"  [RETINT LINE] {line.colorant_code}: {line.ml_volume} ml = {line.qty_litres} L")

    @api.depends('colorant_id')
    def _compute_available_stock(self):
        """Get available stock for colorant in litres"""
        _logger.debug("🔄 [RETINT LINE] Computing available_stock for colorant lines")
        for line in self:
            line.available_stock = line.colorant_id.qty_available if line.colorant_id else 0.0

    @api.depends('qty_litres', 'available_stock')
    def _compute_stock_warning(self):
        """Check if stock is insufficient"""
        _logger.debug("🔄 [RETINT LINE] Computing stock_warning for colorant lines")
        for line in self:
            line.stock_warning = line.additional_shots > 0 and line.qty_litres > line.available_stock
            if line.stock_warning:
                _logger.warning(f"  ⚠ [RETINT LINE] Stock warning for {line.colorant_code}: need {line.qty_litres}L, have {line.available_stock}L")

    @api.depends('unit_cost_excl_vat')
    def _compute_unit_cost_incl_vat(self):
        """Calculate VAT-inclusive unit cost (16% VAT)"""
        for line in self:
            line.unit_cost_incl_vat = line.unit_cost_excl_vat * 1.16

    @api.depends('unit_cost_excl_vat', 'qty_litres')
    def _compute_line_costs(self):
        """Calculate total line costs"""
        for line in self:
            line.line_cost_excl_vat = line.unit_cost_excl_vat * line.qty_litres
            line.line_cost_incl_vat = line.unit_cost_incl_vat * line.qty_litres

    @api.depends('colorant_id.name')
    def _compute_colorant_name(self):
        """Compute colorant name"""
        for line in self:
            line.colorant_name = line.colorant_id.name if line.colorant_id else ''

    @api.onchange('additional_shots')
    def _onchange_additional_shots(self):
        """Force immediate recompute when additional shots change"""
        _logger.info("🎯 [RETINT ONCHANGE] Additional shots updated")
        for line in self:
            if line.additional_shots > 0:
                _logger.debug(f"  [RETINT ONCHANGE] {line.colorant_code}: shots changed to {line.additional_shots}")
            
            # Force immediate computation
            line._compute_ml_volume()
            line._compute_qty_litres()
            line._compute_line_costs()
            
            # Trigger parent wizard recompute
            if line.wizard_id:
                _logger.debug(f"  [RETINT ONCHANGE] Triggering parent wizard recompute")
                line.wizard_id._compute_costs()
                line.wizard_id._compute_customer_charge()


class RetintWizard(models.TransientModel):
    """
    RE-TINTING WIZARD
    
    Allows staff to re-tint a returned tinted product by adding additional colorants.
    Supports flexible liability configurations (customer/company/shared).
    Creates new adjusted product with (Adj) suffix.
    
    Workflow:
    1. Select returned tinted product
    2. System loads original formula (read-only)
    3. Configure cost liability (who pays?)
    4. Enter additional colorants to add
    5. Create adjusted product and MO
    """
    _name = 'retint.wizard'
    _description = 'Paint Re-Tinting Wizard'

    # ============================================================
    # SECTION 1: ORIGINAL PRODUCT INFORMATION
    # ============================================================
    original_product_id = fields.Many2one(
        'product.product',
        string='Returned Tinted Product',
        domain="[('is_tinted_product', '=', True)]",
        required=True,
        help='Select the tinted product that was returned by customer'
    )
    
    # Original product details (auto-filled, read-only)
    original_base_product = fields.Char(
        string='Original Base',
        readonly=True,
        help='Base product used in original tinting'
    )
    original_colour_code = fields.Char(
        string='Colour Code',
        readonly=True
    )
    original_colour_name = fields.Char(
        string='Colour Name',
        readonly=True
    )
    original_fandeck = fields.Char(
        string='Fandeck',
        readonly=True
    )
    original_cost_excl_vat = fields.Float(
        string='Original Cost (Excl. VAT)',
        compute='_compute_original_prices',
        store=True,
        readonly=True,
        digits='Product Price'
    )
    original_cost_incl_vat = fields.Float(
        string='Original Cost (Incl. VAT)',
        compute='_compute_original_prices',
        store=True,
        readonly=True,
        digits='Product Price'
    )
    original_selling_price = fields.Float(
        string='Original Selling Price',
        compute='_compute_original_prices',
        store=True,  # ✅ CRITICAL: Store computed value in database
        readonly=True,  # ✅ Keep readonly in UI (auto-filled)
        digits='Product Price',
        help='Selling price of original tinted product (automatically loaded from selected product)'
    )
    # Original formula (read-only display)
    original_formula_line_ids = fields.One2many(
        'retint.wizard.original.line',
        'wizard_id',
        string='Original Formula',
        readonly=True,
        help='Original colorants used (for reference only)'
    )
    
    # ============================================================
    # SECTION 2: ADDITIONAL COLORANTS (USER INPUT)
    # ============================================================
    additional_colorant_line_ids = fields.One2many(
        'retint.wizard.colorant.line',
        'wizard_id',
        string='Additional Colorants to Add'
    )
    
    # ============================================================
    # SECTION 3: LIABILITY CONFIGURATION
    # ============================================================
    liability_type = fields.Selection([
        ('customer', 'Customer Liability (100%) - Customer pays all re-tinting costs'),
        ('company', 'Company Liability (100%) - Company absorbs all re-tinting costs'),
        ('shared', 'Shared Liability - Split costs by percentage')
    ], string='Cost Liability', required=True, default='customer',
       help='Who is responsible for paying the re-tinting costs?')
    
    customer_liability_percent = fields.Float(
        string='Customer Pays (%)',
        default=100.0,
        digits=(5, 2),
        help='Percentage of re-tinting cost customer pays (0-100)'
    )
    
    company_liability_percent = fields.Float(
        string='Company Pays (%)',
        compute='_compute_liability_split',
        store=True,
        digits=(5, 2)
    )
    
    liability_reason = fields.Selection([
        ('customer_preference', 'Customer Changed Mind / Preference'),
        ('wrong_color_ordered', 'Customer Ordered Wrong Color'),
        ('company_error_formula', 'Company Error: Wrong Formula'),
        ('company_error_mixing', 'Company Error: Mixing/Dispensing Error'),
        ('company_error_machine', 'Company Error: Machine Calibration'),
        ('quality_issue', 'Quality Issue / Product Defect'),
        ('mutual_agreement', 'Mutual Agreement / Goodwill'),
        ('other', 'Other (specify in notes)')
    ], string='Reason for Re-Tinting', required=True,
       help='Why is this product being re-tinted?')
    
    liability_notes = fields.Text(
        string='Liability Notes',
        help='Additional notes about cost responsibility or re-tinting reason'
    )
    
    # ============================================================
    # SECTION 4: COST CALCULATIONS
    # ============================================================
    additional_colorant_cost_excl_vat = fields.Float(
        string='Additional Colorants Cost (Excl. VAT)',
        compute='_compute_costs',
        store=True,
        digits='Product Price',
        help='Cost of additional colorants only'
    )
    
    additional_colorant_cost_incl_vat = fields.Float(
        string='Additional Colorants Cost (Incl. VAT)',
        compute='_compute_costs',
        store=True,
        digits='Product Price'
    )
    
    retint_service_cost = fields.Float(
        string='Re-Tinting Service Charge',
        default=0.0,
        digits='Product Price',
        help='Optional labor/service charge for re-tinting (manually set)'
    )
    
    total_retint_cost_incl_vat = fields.Float(
        string='Total Re-Tinting Cost (Incl. VAT)',
        compute='_compute_costs',
        store=True,
        digits='Product Price',
        help='Colorants + Service Charge (total cost to re-tint)'
    )
    
    customer_charge_amount = fields.Float(
        string='Customer Pays',
        compute='_compute_customer_charge',
        store=True,
        digits='Product Price',
        help='Amount to charge customer in POS'
    )
    
    company_absorption_amount = fields.Float(
        string='Company Absorbs',
        compute='_compute_customer_charge',
        store=True,
        digits='Product Price',
        help='Cost absorbed by company as expense'
    )
    
    # ============================================================
    # SECTION 5: NEW PRODUCT DETAILS
    # ============================================================
    new_product_name = fields.Char(
        string='New Product Name',
        compute='_compute_new_name',
        store=True,
        help='Auto-generated name for adjusted product'
    )
    
    adjustment_number = fields.Integer(
        string='Adjustment Number',
        compute='_compute_adjustment_number',
        store=True,
        help='Which adjustment is this? (1, 2, 3, etc.)'
    )
    
    new_product_cost_excl_vat = fields.Float(
        string='New Product Cost (Excl. VAT)',
        compute='_compute_costs',
        store=True,
        digits='Product Price',
        help='Original cost + Additional colorants (accounting cost)'
    )
    
    new_product_cost_incl_vat = fields.Float(
        string='New Product Cost (Incl. VAT)',
        compute='_compute_costs',
        store=True,
        digits='Product Price'
    )
    
    new_product_selling_price = fields.Float(
        string='New Product Selling Price',
        compute='_compute_selling_price',
        store=True,
        digits='Product Price',
        help='Price to set on adjusted product (includes customer portion of re-tint cost)'
    )
    
    # ============================================================
    # SECTION 6: WARNINGS & VALIDATION
    # ============================================================
    has_stock_warnings = fields.Boolean(
        string='Has Stock Warnings',
        compute='_compute_warnings'
    )
    stock_warning_message = fields.Html(
        string='Stock Warnings',
        compute='_compute_warnings'
    )
    
    # ============================================================
    # COMPUTE METHODS
    # ============================================================
    
    @api.onchange('original_product_id')
    def _onchange_original_product(self):
        """
        When user selects returned product:
        1. Load product details (colour, fandeck) - NON-computed fields only
        2. Load original BOM formula (read-only display)
        3. Setup colorant lines for additional shots
        4. Detect adjustment number
        
        Note: original_cost_excl_vat, original_cost_incl_vat, and original_selling_price
        are computed fields and will be set automatically by _compute_original_prices()
        """
        _logger.info("=" * 80)
        _logger.info("🎯 [RETINT ONCHANGE] original_product_id updated")
        _logger.info("=" * 80)
        
        if not self.original_product_id:
            _logger.info("  [RETINT ONCHANGE] No product selected - clearing fields")
            self.original_base_product = False
            self.original_colour_code = False
            self.original_colour_name = False
            self.original_fandeck = False
            # ✅ REMOVED: Do NOT set computed fields here
            # The compute method will handle: original_cost_excl_vat, original_cost_incl_vat, original_selling_price
            self.original_formula_line_ids = [(5, 0, 0)]
            self.additional_colorant_line_ids = [(5, 0, 0)]
            return
        
        product = self.original_product_id
        _logger.info(f"  [RETINT ONCHANGE] Selected product: {product.display_name}")
        _logger.info(f"  [RETINT ONCHANGE] Product ID: {product.id}")
        
        # ✅ Load product information (NON-computed fields only)
        _logger.info("  [RETINT ONCHANGE] Loading product details...")
        self.original_colour_code = product.colour_code_id.code if product.colour_code_id else 'N/A'
        self.original_colour_name = product.colour_code_id.name if product.colour_code_id else 'N/A'
        self.original_fandeck = product.fandeck_id.name if product.fandeck_id else 'N/A'
        
        # ✅ REMOVED: Do NOT set computed fields (original_cost_excl_vat, original_cost_incl_vat, original_selling_price)
        # The _compute_original_prices() method will automatically set these when original_product_id changes
        
        _logger.info(f"  [RETINT ONCHANGE] Colour: {self.original_colour_code} - {self.original_colour_name}")
        _logger.info(f"  [RETINT ONCHANGE] Fandeck: {self.original_fandeck}")
        _logger.info(f"  [RETINT ONCHANGE] Cost and prices will be computed automatically")
        
        # Find product's BOM
        _logger.info("  [RETINT ONCHANGE] Searching for product's BOM...")
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('is_tinting_bom', '=', True)
        ], limit=1)
        
        if bom:
            _logger.info(f"  [RETINT ONCHANGE] ✅ Found BOM ID: {bom.id}")
            _logger.info(f"  [RETINT ONCHANGE] BOM has {len(bom.bom_line_ids)} lines")
            self._load_original_formula(bom)
        else:
            _logger.warning(f"  [RETINT ONCHANGE] ⚠ No BOM found for product {product.display_name}")
            _logger.warning(f"  [RETINT ONCHANGE] This product may not be a properly tinted product")
            self.original_formula_line_ids = [(5, 0, 0)]
            self.original_base_product = "Unknown (No BOM found)"
        
        # Setup colorant lines for additional shots
        _logger.info("  [RETINT ONCHANGE] Setting up additional colorant lines...")
        self._setup_additional_colorant_lines()
        
        _logger.info("=" * 80)
    def _load_original_formula(self, bom):
        """
        Read BOM and display original colorants used.
        This is READ-ONLY information for staff reference.
        
        Args:
            bom: mrp.bom record of the original tinted product
        """
        _logger.info("  📋 [LOAD FORMULA] Loading original formula from BOM...")
        _logger.info(f"  📋 [LOAD FORMULA] BOM ID: {bom.id}")
        
        original_lines = []
        base_found = False
        
        for bom_line in bom.bom_line_ids:
            if bom_line.is_colorant_line:
                # This is a colorant line
                # ✅ FIX: Calculate ml from shots (1 shot = 0.616 ml)
                ml_qty = bom_line.colorant_shots * 0.616 if bom_line.colorant_shots else 0.0
                
                original_lines.append((0, 0, {
                    'colorant_name': bom_line.product_id.name,
                    'colorant_code': bom_line.product_id.product_tmpl_id.colorant_code,
                    'original_shots': bom_line.colorant_shots,
                    'original_ml': ml_qty,  # ✅ Calculated value
                }))
                _logger.info(f"  📋 [LOAD FORMULA] Colorant: {bom_line.product_id.product_tmpl_id.colorant_code} "
                        f"- {bom_line.colorant_shots} shots ({ml_qty} ml)")
            else:
                # This is the base product line
                if not base_found:
                    self.original_base_product = bom_line.product_id.display_name
                    base_found = True
                    _logger.info(f"  📋 [LOAD FORMULA] Base product: {bom_line.product_id.display_name}")
        
        self.original_formula_line_ids = original_lines
        _logger.info(f"  📋 [LOAD FORMULA] ✅ Loaded {len(original_lines)} colorant lines")
        
        if not base_found:
            _logger.warning("  📋 [LOAD FORMULA] ⚠ No base product found in BOM")
            self.original_base_product = "Unknown"

    def _setup_additional_colorant_lines(self):
        """
        Create colorant lines for ADDITIONAL shots.
        Same structure as main tinting wizard - C1-C16.
        These are BLANK lines for user to enter additional shots.
        """
        _logger.info("  🔧 [SETUP LINES] Setting up additional colorant lines (C1-C16)...")
        
        # Get all mapped colorant products
        colorants = self.env['product.product'].search([
            ('product_tmpl_id.is_colorant', '=', True),
            ('product_tmpl_id.colorant_code', '!=', False)
        ])
        _logger.info(f"  🔧 [SETUP LINES] Found {len(colorants)} colorant products in system")
        
        # Create mapping dictionary
        code_to_product = {}
        for colorant in colorants:
            code = colorant.product_tmpl_id.colorant_code.strip().upper()
            if code and code.startswith('C'):
                code_to_product[code] = colorant.id
                _logger.debug(f"  🔧 [SETUP LINES] Mapped {code} -> {colorant.name}")
        
        # Create 16 lines for C1-C16
        lines = []
        for i in range(1, 17):
            code = f'C{i}'
            product_id = code_to_product.get(code, False)
            lines.append((0, 0, {
                'colorant_id': product_id,
                'additional_shots': 0.0,
            }))
        
        self.additional_colorant_line_ids = lines
        _logger.info(f"  🔧 [SETUP LINES] ✅ Created {len(lines)} additional colorant lines")

    @api.depends('liability_type', 'customer_liability_percent')
    def _compute_liability_split(self):
        """
        Calculate company liability percentage based on selection.
        
        Logic:
        - Customer liability: Customer = 100%, Company = 0%
        - Company liability: Customer = 0%, Company = 100%
        - Shared liability: Customer = X%, Company = (100-X)%
        """
        _logger.debug("🔄 [COMPUTE] Computing liability split...")
        for wizard in self:
            if wizard.liability_type == 'customer':
                wizard.customer_liability_percent = 100.0
                wizard.company_liability_percent = 0.0
                _logger.debug(f"  [COMPUTE] Customer liability: 100% customer, 0% company")
            elif wizard.liability_type == 'company':
                wizard.customer_liability_percent = 0.0
                wizard.company_liability_percent = 100.0
                _logger.debug(f"  [COMPUTE] Company liability: 0% customer, 100% company")
            else:  # shared
                # Validate range
                if wizard.customer_liability_percent < 0:
                    wizard.customer_liability_percent = 0.0
                elif wizard.customer_liability_percent > 100:
                    wizard.customer_liability_percent = 100.0
                
                wizard.company_liability_percent = 100.0 - wizard.customer_liability_percent
                _logger.debug(f"  [COMPUTE] Shared liability: {wizard.customer_liability_percent}% customer, "
                            f"{wizard.company_liability_percent}% company")

    @api.depends('additional_colorant_line_ids.line_cost_excl_vat',
                 'additional_colorant_line_ids.line_cost_incl_vat',
                 'retint_service_cost',
                 'original_cost_excl_vat',
                 'original_cost_incl_vat')
    def _compute_costs(self):
        """
        Calculate all costs:
        1. Additional colorant costs
        2. Total re-tinting cost (colorants + service)
        3. New product total cost (original + additional colorants)
        """
        _logger.info("🔄 [COMPUTE COSTS] Computing all costs...")
        for wizard in self:
            # Sum additional colorant costs
            wizard.additional_colorant_cost_excl_vat = sum(
                line.line_cost_excl_vat 
                for line in wizard.additional_colorant_line_ids
            )
            wizard.additional_colorant_cost_incl_vat = sum(
                line.line_cost_incl_vat 
                for line in wizard.additional_colorant_line_ids
            )
            
            _logger.debug(f"  [COMPUTE COSTS] Additional colorants: {wizard.additional_colorant_cost_incl_vat} KES")
            _logger.debug(f"  [COMPUTE COSTS] Service charge: {wizard.retint_service_cost} KES")
            
            # Total re-tinting cost = colorants + service
            wizard.total_retint_cost_incl_vat = (
                wizard.additional_colorant_cost_incl_vat + 
                wizard.retint_service_cost
            )
            
            _logger.debug(f"  [COMPUTE COSTS] Total re-tint cost: {wizard.total_retint_cost_incl_vat} KES")
            
            # New product total cost (for accounting)
            wizard.new_product_cost_excl_vat = (
                wizard.original_cost_excl_vat + 
                wizard.additional_colorant_cost_excl_vat
            )
            wizard.new_product_cost_incl_vat = (
                wizard.original_cost_incl_vat + 
                wizard.additional_colorant_cost_incl_vat
            )
            
            _logger.info(f"  [COMPUTE COSTS] ✅ New product cost: {wizard.new_product_cost_incl_vat} KES "
                        f"(original {wizard.original_cost_incl_vat} + colorants {wizard.additional_colorant_cost_incl_vat})")

    @api.depends('total_retint_cost_incl_vat', 'customer_liability_percent')
    def _compute_customer_charge(self):
        """
        Calculate how much to charge customer based on liability split.
        
        Formula:
        - Customer charge = Total re-tint cost × (Customer % / 100)
        - Company absorbs = Total re-tint cost - Customer charge
        """
        _logger.info("🔄 [COMPUTE CHARGE] Computing customer charge...")
        for wizard in self:
            # Customer pays their percentage of re-tinting cost
            wizard.customer_charge_amount = (
                wizard.total_retint_cost_incl_vat * 
                (wizard.customer_liability_percent / 100.0)
            )
            
            # Company absorbs the rest
            wizard.company_absorption_amount = (
                wizard.total_retint_cost_incl_vat - 
                wizard.customer_charge_amount
            )
            
            _logger.info(f"  [COMPUTE CHARGE] Customer pays: {wizard.customer_charge_amount} KES "
                        f"({wizard.customer_liability_percent}%)")
            _logger.info(f"  [COMPUTE CHARGE] Company absorbs: {wizard.company_absorption_amount} KES "
                        f"({wizard.company_liability_percent}%)")

    @api.depends('original_product_id', 'original_product_id.name')
    def _compute_new_name(self):
        """
        Auto-generate new product name with (Adj) suffix.
        
        Examples:
            "4L Crown - Red Rose" → "4L Crown - Red Rose (Adj)"
            "4L Crown - Red Rose (Adj)" → "4L Crown - Red Rose (Adj2)"
            "4L Crown - Red Rose (Adj2)" → "4L Crown - Red Rose (Adj3)"
        """
        _logger.info("🔄 [COMPUTE NAME] Computing new product name...")
        for wizard in self:
            if not wizard.original_product_id:
                wizard.new_product_name = ''
                continue
            
            original_name = wizard.original_product_id.name
            _logger.info(f"  [COMPUTE NAME] Original name: '{original_name}'")
            
            # Check if already has (Adj) suffix
            adj_match = re.search(r'\(Adj(\d*)\)$', original_name.strip())
            
            if adj_match:
                # Increment existing adjustment number
                current_num_str = adj_match.group(1)
                current_num = int(current_num_str) if current_num_str else 1
                next_num = current_num + 1
                
                new_name = re.sub(r'\(Adj\d*\)$', f'(Adj{next_num})', original_name.strip())
                _logger.info(f"  [COMPUTE NAME] Incrementing: (Adj{current_num}) → (Adj{next_num})")
            else:
                # First adjustment
                new_name = f"{original_name.strip()} (Adj)"
                _logger.info(f"  [COMPUTE NAME] First adjustment: adding (Adj) suffix")
            
            wizard.new_product_name = new_name
            _logger.info(f"  [COMPUTE NAME] ✅ New name: '{new_name}'")

    @api.depends('original_product_id', 'original_product_id.name')
    def _compute_adjustment_number(self):
        """
        Track which adjustment this is (1, 2, 3, etc.).
        Useful for analytics and reporting.
        """
        _logger.debug("🔄 [COMPUTE ADJ#] Computing adjustment number...")
        for wizard in self:
            if not wizard.original_product_id:
                wizard.adjustment_number = 1
                continue
            
            original_name = wizard.original_product_id.name
            adj_match = re.search(r'\(Adj(\d*)\)$', original_name.strip())
            
            if adj_match:
                current_num_str = adj_match.group(1)
                wizard.adjustment_number = int(current_num_str) + 1 if current_num_str else 2
            else:
                wizard.adjustment_number = 1
            
            _logger.debug(f"  [COMPUTE ADJ#] This is adjustment #{wizard.adjustment_number}")
            
    @api.depends('original_product_id', 'original_product_id.list_price', 'original_product_id.standard_price')
    def _compute_original_prices(self):
        """
        Compute and STORE original product prices when product is selected.
        
        ✅ CRITICAL: These fields MUST be stored for price calculations.
        Without store=True, values are lost when wizard is submitted.
        """
        _logger.info("🔄 [COMPUTE ORIGINAL] Computing original product prices...")
        for wizard in self:
            if wizard.original_product_id:
                product = wizard.original_product_id
                
                # Store all original prices
                wizard.original_cost_excl_vat = product.standard_price
                wizard.original_cost_incl_vat = product.standard_price * 1.16
                wizard.original_selling_price = product.list_price
                
                _logger.info(f"  [COMPUTE ORIGINAL] Product: {product.display_name}")
                _logger.info(f"  [COMPUTE ORIGINAL] Cost (excl VAT): {wizard.original_cost_excl_vat} KES")
                _logger.info(f"  [COMPUTE ORIGINAL] Cost (incl VAT): {wizard.original_cost_incl_vat} KES")
                _logger.info(f"  [COMPUTE ORIGINAL] ✅ Selling Price: {wizard.original_selling_price} KES")
            else:
                wizard.original_cost_excl_vat = 0.0
                wizard.original_cost_incl_vat = 0.0
                wizard.original_selling_price = 0.0
                _logger.info(f"  [COMPUTE ORIGINAL] No product selected - prices reset to 0.0")

    @api.depends('original_selling_price', 'customer_charge_amount')
    def _compute_selling_price(self):
        """
        Calculate selling price for new adjusted product.
        
        Logic:
        - Selling price = Original selling price + Customer's portion of re-tint cost
        
        Examples:
            Original price: 1,000 KES
            Re-tint cost: 150 KES
            Customer pays 100%: New price = 1,000 + 150 = 1,150 KES
            Customer pays 30%: New price = 1,000 + 45 = 1,045 KES
            Customer pays 0%: New price = 1,000 + 0 = 1,000 KES (company absorbs)
        """
        _logger.info("🔄 [COMPUTE SELLING] Computing new selling price...")
        for wizard in self:
            if not wizard.original_product_id:
                wizard.new_product_selling_price = 0.0
                continue
            
            # Selling price = Original price + Customer's portion of re-tint
            wizard.new_product_selling_price = (
                wizard.original_selling_price + 
                wizard.customer_charge_amount
            )
            
            _logger.info(f"  [COMPUTE SELLING] Original price: {wizard.original_selling_price} KES")
            _logger.info(f"  [COMPUTE SELLING] Customer portion: {wizard.customer_charge_amount} KES")
            _logger.info(f"  [COMPUTE SELLING] ✅ New selling price: {wizard.new_product_selling_price} KES")

    @api.depends('additional_colorant_line_ids.stock_warning')
    def _compute_warnings(self):
        """Compute stock warnings for additional colorants"""
        _logger.debug("🔄 [COMPUTE WARN] Checking stock warnings...")
        for wizard in self:
            stock_msgs = []
            
            for line in wizard.additional_colorant_line_ids.filtered('stock_warning'):
                stock_msgs.append(
                    f"{line.colorant_name or 'Unknown'}: "
                    f"Need {line.qty_litres:.4f}L, Have {line.available_stock:.4f}L"
                )
                _logger.warning(f"  ⚠ [COMPUTE WARN] {stock_msgs[-1]}")
            
            wizard.has_stock_warnings = bool(stock_msgs)
            wizard.stock_warning_message = ''.join([
                f"<div style='color:red;'>⚠ Warning: {msg}</div>" 
                for msg in stock_msgs
            ]) or "<div style='color:green;'>✓ All colorants in stock</div>"

    # ============================================================
    # ACTION METHODS
    # ============================================================
    
    def action_create_adjusted_product(self):
            """
            MAIN ACTION: Create new adjusted product.
            
            Steps:
            1. Validate inputs
            2. Create new product with (Adj) suffix
            3. Create BOM consuming original product + additional colorants
            4. Create Manufacturing Order
            5. Track liability analytics
            6. Return to MO
            """
            _logger.info("=" * 80)
            _logger.info("🚀 [CREATE ADJUSTED] Starting adjusted product creation")
            _logger.info("=" * 80)
            
            self.ensure_one()
            
            # ============================================
            # STEP 1: VALIDATION
            # ============================================
            _logger.info("📋 [CREATE ADJUSTED] STEP 1: Validating inputs...")
            
            if not self.original_product_id:
                _logger.error("❌ [CREATE ADJUSTED] No original product selected")
                raise ValidationError(_("Please select a returned tinted product."))
            
            active_colorants = self.additional_colorant_line_ids.filtered('additional_shots')
            if not active_colorants:
                _logger.error("❌ [CREATE ADJUSTED] No additional colorants entered")
                raise ValidationError(_("Please enter at least one additional colorant shot.\n"
                                    "You must add colorants to adjust the color."))
            
            if not self.liability_reason:
                _logger.error("❌ [CREATE ADJUSTED] No liability reason selected")
                raise ValidationError(_("Please select a reason for re-tinting."))
            
            # Check for unmapped colorants
            unmapped = active_colorants.filtered(lambda l: not l.colorant_id)
            if unmapped:
                _logger.error("❌ [CREATE ADJUSTED] Unmapped colorants detected")
                raise ValidationError(_("Some colorants are not mapped to products.\n"
                                    "Please map all C1-C16 colorants first."))
            
            _logger.info(f"  [CREATE ADJUSTED] ✅ Validation passed")
            _logger.info(f"  [CREATE ADJUSTED] Original product: {self.original_product_id.display_name}")
            _logger.info(f"  [CREATE ADJUSTED] Additional colorants: {len(active_colorants)}")
            _logger.info(f"  [CREATE ADJUSTED] Liability: {self.liability_type}")
            _logger.info(f"  [CREATE ADJUSTED] Customer pays: {self.customer_liability_percent}%")
            
            # ============================================
            # STEP 2: CREATE NEW PRODUCT
            # ============================================
            _logger.info("📋 [CREATE ADJUSTED] STEP 2: Creating new product...")
            
            # Get Tinted Paint category
            categ = self.env['product.category'].search([('name', '=', 'Tinted Paint')], limit=1)
            if not categ:
                categ = self.env['product.category'].create({
                    'name': 'Tinted Paint',
                    'property_cost_method': 'fifo',
                    'property_valuation': 'real_time',
                })
                _logger.info(f"  [CREATE ADJUSTED] Created Tinted Paint category")
            
            # ✅ CRITICAL: Determine correct product type (same logic as tint_wizard)
            _logger.info("📋 [CREATE ADJUSTED] STEP 2A: Determining product type configuration...")
            
            # Check available product types in system
            product_type_field = self.env['product.template']._fields.get('type')
            if product_type_field:
                available_types = product_type_field.get_values(self.env)
                _logger.info(f"  [CREATE ADJUSTED] Available product types: {available_types}")
            else:
                available_types = []
                _logger.warning("  [CREATE ADJUSTED] ⚠ No 'type' field found in product.template")
            
            # Get base product type (from original product)
            base_type = getattr(self.original_product_id, 'type', 'consu')
            _logger.info(f"  [CREATE ADJUSTED] Original product type: {base_type}")
            
            product_vals = {
                'name': self.new_product_name,
                'categ_id': categ.id,
                'uom_id': self.original_product_id.uom_id.id,
                'uom_po_id': self.original_product_id.uom_po_id.id,
                'standard_price': self.new_product_cost_excl_vat,
                'list_price': self.new_product_selling_price,
                'is_tinted_product': True,
                'fandeck_id': self.original_product_id.fandeck_id.id,
                'colour_code_id': self.original_product_id.colour_code_id.id,
                'tracking': 'lot',  # ✅ CRITICAL: Enable lot tracking
                'sale_ok': True,
                'purchase_ok': True,
                'description': f"Re-tinted product (Adjustment #{self.adjustment_number})\n"
                            f"Original: {self.original_product_id.display_name}\n"
                            f"Reason: {dict(self._fields['liability_reason'].selection).get(self.liability_reason)}",
                'default_code': f"RETINT-{self.original_product_id.colour_code_id.code}-{fields.Datetime.now().strftime('%Y%m%d%H%M')}",
            }
            
            _logger.info(f"  [CREATE ADJUSTED] Product name: {product_vals['name']}")
            _logger.info(f"  [CREATE ADJUSTED] Cost: {product_vals['standard_price']} KES")
            _logger.info(f"  [CREATE ADJUSTED] Selling price: {product_vals['list_price']} KES")
            _logger.info(f"  [CREATE ADJUSTED] Tracking: {product_vals['tracking']}")
            
            # ✅ ROBUST PRODUCT TYPE FALLBACK (same as tint_wizard)
            _logger.info("  [CREATE ADJUSTED] Attempting product creation with type fallback...")
            new_product = None
            
            try:
                # Try 'product' first (storable product with tracking)
                product_vals['type'] = 'product'
                _logger.info("  [CREATE ADJUSTED] Attempt 1: type='product' (storable with tracking)")
                new_product = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                _logger.info("  [CREATE ADJUSTED] ✅ Created with type='product'")
            except ValueError as e:
                _logger.warning(f"  [CREATE ADJUSTED] ❌ Type 'product' failed: {e}")
                try:
                    # Try 'stockable' (some custom Odoo versions)
                    product_vals['type'] = 'stockable'
                    _logger.info("  [CREATE ADJUSTED] Attempt 2: type='stockable'")
                    new_product = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                    _logger.info("  [CREATE ADJUSTED] ✅ Created with type='stockable'")
                except ValueError as e2:
                    _logger.warning(f"  [CREATE ADJUSTED] ❌ Type 'stockable' failed: {e2}")
                    try:
                        # Try base product type (copy from original)
                        product_vals['type'] = base_type
                        _logger.info(f"  [CREATE ADJUSTED] Attempt 3: type='{base_type}' (from original product)")
                        new_product = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                        _logger.info(f"  [CREATE ADJUSTED] ✅ Created with type='{base_type}'")
                    except Exception as e3:
                        _logger.error(f"  [CREATE ADJUSTED] ❌ All type approaches failed: {e3}")
                        # Last resort: remove type and let system default
                        del product_vals['type']
                        _logger.info("  [CREATE ADJUSTED] Attempt 4: Creating without type specification (system default)")
                        new_product = self.env['product.template'].with_context(skip_auto_name=True).create(product_vals)
                        _logger.warning("  [CREATE ADJUSTED] ⚠ Created without explicit type")
            
            _logger.info(f"  [CREATE ADJUSTED] ✅ Created product ID: {new_product.id}")
            
            # ============================================
            # STEP 2B: VERIFY AND ENFORCE TRACKING
            # ============================================
            _logger.info("📋 [CREATE ADJUSTED] STEP 2B: Verifying tracking configuration...")
            _logger.info("  [CREATE ADJUSTED] 🔍 Product Type & Tracking Verification:")
            
            if hasattr(new_product, 'type'):
                current_type = new_product.type
                _logger.info(f"  [CREATE ADJUSTED]   Current type: '{current_type}'")
                
                # ✅ ENFORCE: Try to upgrade to 'product' if not already
                if current_type != 'product':
                    _logger.warning(f"  [CREATE ADJUSTED]   ⚠ Product type is '{current_type}', attempting to upgrade to 'product' for tracking...")
                    try:
                        new_product.write({'type': 'product'})
                        _logger.info("  [CREATE ADJUSTED]   ✅ Successfully upgraded to type='product'")
                    except Exception as e:
                        _logger.error(f"  [CREATE ADJUSTED]   ❌ Failed to upgrade to 'product': {e}")
                        try:
                            new_product.write({'type': 'stockable'})
                            _logger.info("  [CREATE ADJUSTED]   ✅ Upgraded to type='stockable'")
                        except Exception as e2:
                            _logger.error(f"  [CREATE ADJUSTED]   ❌ Failed to upgrade to 'stockable': {e2}")
                            _logger.warning(f"  [CREATE ADJUSTED]   ⚠ Product remains as type='{current_type}'")
            else:
                _logger.warning("  [CREATE ADJUSTED]   ⚠ Product template has no 'type' field")
            
            # ✅ ENFORCE: Verify tracking is set to 'lot'
            current_tracking = getattr(new_product, 'tracking', None)
            _logger.info(f"  [CREATE ADJUSTED]   Current tracking: '{current_tracking}'")
            
            if current_tracking != 'lot':
                _logger.warning(f"  [CREATE ADJUSTED]   ⚠ Tracking is '{current_tracking}', forcing to 'lot'...")
                try:
                    new_product.write({'tracking': 'lot'})
                    _logger.info("  [CREATE ADJUSTED]   ✅ Successfully set tracking='lot'")
                except Exception as e:
                    _logger.error(f"  [CREATE ADJUSTED]   ❌ Failed to set tracking='lot': {e}")
                    raise ValidationError(_(
                        "Failed to enable lot tracking on adjusted product.\n"
                        "This product may not be trackable in inventory.\n"
                        f"Error: {str(e)}"
                    ))
            
            # ✅ FINAL VERIFICATION
            _logger.info("  [CREATE ADJUSTED] 📊 FINAL PRODUCT CONFIGURATION:")
            _logger.info(f"  [CREATE ADJUSTED]   Product ID: {new_product.id}")
            _logger.info(f"  [CREATE ADJUSTED]   Name: {new_product.name}")
            _logger.info(f"  [CREATE ADJUSTED]   Type: {getattr(new_product, 'type', 'Unknown')}")
            _logger.info(f"  [CREATE ADJUSTED]   Tracking: {getattr(new_product, 'tracking', 'Unknown')}")
            _logger.info(f"  [CREATE ADJUSTED]   Category: {new_product.categ_id.name}")
            
            if getattr(new_product, 'tracking', None) == 'lot':
                _logger.info("  [CREATE ADJUSTED]   ✅ TRACKING CONFIRMED: Product is trackable by lot number")
            else:
                _logger.error("  [CREATE ADJUSTED]   ❌ TRACKING NOT CONFIRMED: Product may not be trackable!")
            
            # ============================================
            # STEP 3: SET UP INVENTORY CONFIGURATION
            # ============================================
            _logger.info("📋 [CREATE ADJUSTED] STEP 3: Configuring inventory routes...")
            
            try:
                manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture')
                if manufacture_route:
                    new_product.write({'route_ids': [(4, manufacture_route.id)]})
                    _logger.info("  [CREATE ADJUSTED] ✅ Added manufacturing route")
            except Exception as e:
                _logger.warning(f"  [CREATE ADJUSTED] ⚠ Could not set manufacturing route: {e}")
            
            try:
                purchase_route = self.env.ref('purchase_stock.route_warehouse0_buy')
                if purchase_route:
                    new_product.write({'route_ids': [(4, purchase_route.id)]})
                    _logger.info("  [CREATE ADJUSTED] ✅ Added purchase route")
            except Exception as e:
                _logger.warning(f"  [CREATE ADJUSTED] ⚠ Could not set purchase route: {e}")
            
            # ============================================
            # STEP 4: CREATE BOM
            # ============================================
            _logger.info("📋 [CREATE ADJUSTED] STEP 4: Creating Bill of Materials...")
            
            bom = self.env['mrp.bom'].create({
                'product_tmpl_id': new_product.id,
                'product_qty': 1.0,
                'product_uom_id': self.original_product_id.uom_id.id,
                'type': 'normal',
                'is_tinting_bom': True,
                'is_retint_bom': True,  # NEW FLAG
                'fandeck_id': self.original_product_id.fandeck_id.id,
                'colour_code_id': self.original_product_id.colour_code_id.id,
                'base_variant_id': self.original_product_id.id,  # Store original product as "base"
                
                # LIABILITY TRACKING
                'retint_liability_type': self.liability_type,
                'retint_customer_percent': self.customer_liability_percent,
                'retint_company_percent': self.company_liability_percent,
                'retint_liability_reason': self.liability_reason,
                'retint_total_cost': self.total_retint_cost_incl_vat,
                'retint_customer_charge': self.customer_charge_amount,
                'retint_company_absorption': self.company_absorption_amount,
                'retint_adjustment_number': self.adjustment_number,
                
                'tinting_notes': (self.liability_notes or '') + 
                            f"\n\nRe-Tinting Details:\n"
                            f"- Original Product: {self.original_product_id.display_name}\n"
                            f"- Adjustment #{self.adjustment_number}\n"
                            f"- Reason: {dict(self._fields['liability_reason'].selection).get(self.liability_reason)}\n"
                            f"- Liability: {dict(self._fields['liability_type'].selection).get(self.liability_type)}\n"
                            f"- Customer Pays: {self.customer_charge_amount} KES ({self.customer_liability_percent}%)\n"
                            f"- Company Absorbs: {self.company_absorption_amount} KES ({self.company_liability_percent}%)",
            })
            _logger.info(f"  [CREATE ADJUSTED] ✅ Created BOM ID: {bom.id}")
            
            # BOM Line 1: Original returned product (consumed)
            _logger.info(f"  [CREATE ADJUSTED] Adding original product to BOM...")
            self.env['mrp.bom.line'].create({
                'bom_id': bom.id,
                'product_id': self.original_product_id.id,
                'product_qty': 1.0,
                'product_uom_id': self.original_product_id.uom_id.id,
                'unit_cost_excl_vat': self.original_cost_excl_vat,
            })
            _logger.info(f"  [CREATE ADJUSTED] Added: 1× {self.original_product_id.display_name}")
            
            # BOM Lines 2+: Additional colorants
            _logger.info(f"  [CREATE ADJUSTED] Adding additional colorants to BOM...")
            for line in active_colorants:
                bom_line = self.env['mrp.bom.line'].create({
                    'bom_id': bom.id,
                    'product_id': line.colorant_id.id,
                    'product_qty': line.qty_litres,
                    'product_uom_id': line.colorant_id.uom_id.id,
                    'is_colorant_line': True,
                    'colorant_shots': line.additional_shots,
                    'unit_cost_excl_vat': line.unit_cost_excl_vat,
                })
                _logger.info(f"  [CREATE ADJUSTED] Added: {line.colorant_code} - "
                            f"{line.additional_shots} shots = {line.qty_litres}L")
                
                # Force recompute
                bom_line._compute_colorant_ml()
                bom_line._compute_unit_cost_incl_vat()
                bom_line._compute_line_costs()
            
            _logger.info(f"  [CREATE ADJUSTED] ✅ BOM has {len(bom.bom_line_ids)} lines total")
            
            # ============================================
            # STEP 5: CREATE MANUFACTURING ORDER
            # ============================================
            _logger.info("📋 [CREATE ADJUSTED] STEP 5: Creating Manufacturing Order...")
            
            mo = self.env['mrp.production'].create({
                'product_id': new_product.product_variant_id.id,
                'bom_id': bom.id,
                'product_qty': 1.0,
                'product_uom_id': self.original_product_id.uom_id.id,
                'origin': f"Re-Tint: {self.original_product_id.name} (Adj#{self.adjustment_number})",
                'is_tinting_mo': True,
            })
            _logger.info(f"  [CREATE ADJUSTED] ✅ Created MO: {mo.name} (ID: {mo.id})")
            
            mo.action_confirm()
            _logger.info(f"  [CREATE ADJUSTED] ✅ MO confirmed")
            
            # Set exact quantities
            for move in mo.move_raw_ids:
                bom_line = move.bom_line_id
                if bom_line and bom_line.is_colorant_line:
                    exact_qty = bom_line.product_qty
                    move.write({
                        'product_uom_qty': exact_qty,
                        'quantity': exact_qty,
                    })
                    _logger.debug(f"  [CREATE ADJUSTED] Set exact qty: {move.product_id.name} = {exact_qty}L")
            
            # ============================================
            # STEP 6: TRACK ANALYTICS
            # ============================================
            _logger.info("📋 [CREATE ADJUSTED] STEP 6: Creating analytics record...")
            
            analytics_data = [{
                'colorant_code': line.colorant_code,
                'additional_shots': line.additional_shots,
                'ml_volume': line.ml_volume,
                'cost': line.line_cost_incl_vat,
            } for line in active_colorants]
            
            analytics = self.env['retint.analytics'].create({
                'original_product_id': self.original_product_id.id,
                'new_product_id': new_product.product_variant_id.id,
                'colour_code_id': self.original_product_id.colour_code_id.id,
                'fandeck_id': self.original_product_id.fandeck_id.id,
                'bom_id': bom.id,
                'mo_id': mo.id,
                'adjustment_number': self.adjustment_number,
                
                'liability_type': self.liability_type,
                'customer_liability_percent': self.customer_liability_percent,
                'company_liability_percent': self.company_liability_percent,
                'liability_reason': self.liability_reason,
                
                'original_cost': self.original_cost_incl_vat,
                'additional_colorant_cost': self.additional_colorant_cost_incl_vat,
                'service_cost': self.retint_service_cost,
                'total_retint_cost': self.total_retint_cost_incl_vat,
                'customer_charged': self.customer_charge_amount,
                'company_absorbed': self.company_absorption_amount,
                'new_product_cost': self.new_product_cost_incl_vat,
                'new_selling_price': self.new_product_selling_price,
                
                'colorants_added_json': json.dumps(list(analytics_data)),
                'notes': self.liability_notes,
            })
            _logger.info(f"  [CREATE ADJUSTED] ✅ Created analytics record ID: {analytics.id}")
            
            # ============================================
            # STEP 7: FINAL SUMMARY
            # ============================================
            _logger.info("=" * 80)
            _logger.info("🎉 [CREATE ADJUSTED] PRODUCT CREATION SUMMARY")
            _logger.info("=" * 80)
            _logger.info(f"  Original Product: {self.original_product_id.display_name}")
            _logger.info(f"  New Product: {new_product.name}")
            _logger.info(f"  Product ID: {new_product.id}")
            _logger.info(f"  Type: {getattr(new_product, 'type', 'Unknown')}")
            _logger.info(f"  Tracking: {getattr(new_product, 'tracking', 'Unknown')}")
            _logger.info(f"  Adjustment #: {self.adjustment_number}")
            _logger.info(f"  ")
            _logger.info(f"  💰 COST BREAKDOWN:")
            _logger.info(f"    Original cost: {self.original_cost_incl_vat} KES")
            _logger.info(f"    Additional colorants: {self.additional_colorant_cost_incl_vat} KES")
            _logger.info(f"    Service charge: {self.retint_service_cost} KES")
            _logger.info(f"    Total re-tint cost: {self.total_retint_cost_incl_vat} KES")
            _logger.info(f"  ")
            _logger.info(f"  📊 LIABILITY SPLIT:")
            _logger.info(f"    Type: {dict(self._fields['liability_type'].selection).get(self.liability_type)}")
            _logger.info(f"    Reason: {dict(self._fields['liability_reason'].selection).get(self.liability_reason)}")
            _logger.info(f"    Customer pays: {self.customer_charge_amount} KES ({self.customer_liability_percent}%)")
            _logger.info(f"    Company absorbs: {self.company_absorption_amount} KES ({self.company_liability_percent}%)")
            _logger.info(f"  ")
            _logger.info(f"  🏷️ NEW PRODUCT PRICING:")
            _logger.info(f"    Cost (accounting): {new_product.standard_price} KES")
            _logger.info(f"    Selling price (POS): {new_product.list_price} KES")
            _logger.info(f"    Profit per unit: {new_product.list_price - new_product.standard_price} KES")
            _logger.info(f"  ")
            _logger.info(f"  📦 MANUFACTURING:")
            _logger.info(f"    BOM ID: {bom.id}")
            _logger.info(f"    MO: {mo.name}")
            _logger.info(f"    Status: Confirmed")
            _logger.info(f"  ")
            _logger.info(f"  🔍 TRACKING STATUS:")
            if getattr(new_product, 'tracking', None) == 'lot':
                _logger.info(f"    ✅ TRACKABLE: Product will require lot/serial numbers")
            else:
                _logger.warning(f"    ⚠ NOT TRACKABLE: Lot tracking may not be enabled")
            _logger.info("=" * 80)
            
            # Return to Manufacturing Order
            return {
                'type': 'ir.actions.act_window',
                'name': f'Re-Tinted Paint (Adjustment #{self.adjustment_number})',
                'res_model': 'mrp.production',
                'res_id': mo.id,
                'view_mode': 'form',
                'target': 'current',
            }