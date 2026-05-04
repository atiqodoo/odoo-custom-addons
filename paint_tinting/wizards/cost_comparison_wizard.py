# -*- coding: utf-8 -*-
"""
Cost Comparison Wizard Module with Volume Scaling & Attribute Equivalency
==========================================================================

Allows users to compare costs across different paint brands using the same
colorant formula. Supports volume scaling to translate formulas between
different package sizes. Supports attribute equivalency grouping so that
interchangeable base products (e.g. Pastel Base / Brilliant White / White)
are always included in the comparison regardless of naming differences.

Key Features:
- Finds similar products (same category, UOM, and attribute)
- Attribute Equivalency Map: groups interchangeable attributes so products
  like "Pastel Base", "Brilliant White", "White" are compared together
- Applies same colorant formula to all products
- Shows cost breakdown, profit, and margin for each brand
- Allows inline price editing to see profit/margin changes
- "Use This" button to switch base product in parent tint wizard
- Volume scaling: translate formula to different package sizes
- Search products in target UOM with scaled colorant shots
- One-click update of parent wizard with scaled formula

Author: ATIQ - Crown Kenya PLC / Mzaramo Paints & Wallpaper
Odoo Version: 18 Enterprise

Architecture Notes:
- Lines created in create() method after wizard record exists
- Volume Scaling: complete package translation with real product costs
- Attribute Equivalency: resolved via _normalize_attribute_name() before
  any comparison so all matching happens on canonical group names
"""

import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CostComparisonLine(models.TransientModel):
    """
    Individual product comparison line in the cost comparison wizard.

    Each line represents one product variant being compared against the
    current base product in the parent tint wizard. Stores:
        - Cost breakdown (base cost + colorant cost)
        - Editable selling price for profit simulation
        - Auto-calculated profit amount and profit margin percentage
        - Flag indicating whether this is the currently selected product

    The selling price defaults to total cost + 30% markup on creation.
    Users can edit it inline; profit and margin recalculate automatically
    via _compute_profit().

    Below-cost pricing is caught immediately via _onchange_selling_price_validate()
    which fires a warning dialog before the user saves.
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
        help='Parent comparison wizard that owns this line'
    )

    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=False,
        help='Product variant being compared. Not enforced required at field '
             'level to avoid constraint issues during transient record creation.'
    )

    # ============================================
    # BASE PRODUCT TRACKING FIELDS
    # ============================================
    base_product_id = fields.Many2one(
        'product.product',
        string='Base Product',
        related='product_id',
        store=True,
        help='Base product used for tinting (mirrors product_id, stored '
             'for downstream quotation generation workflows)'
    )

    base_product_uom_id = fields.Many2one(
        'uom.uom',
        string='Base Product UOM',
        related='product_id.uom_id',
        store=True,
        help='Unit of measure of the base product (stored for quotation generation)'
    )

    # ============================================
    # COMPUTED DISPLAY FIELDS
    # ============================================
    brand_name = fields.Char(
        string='Brand',
        compute='_compute_brand_name',
        help='Brand name extracted from product name or brand_id field'
    )

    # ============================================
    # STATUS FIELDS
    # ============================================
    is_current_product = fields.Boolean(
        string='Is Current Product',
        default=False,
        help='True if this line represents the product currently selected '
             'in the parent tint wizard (highlighted bold in the list view)'
    )

    # ============================================
    # COST FIELDS
    # ============================================
    base_cost_incl_vat = fields.Float(
        string='Base Cost (Incl. VAT)',
        digits=(16, 2),
        help='Cost of the base paint product including 16% VAT. '
             'Varies per product; colorant cost is the same for all lines.'
    )

    colorant_cost_incl_vat = fields.Float(
        string='Colorant Cost (Incl. VAT)',
        digits=(16, 2),
        help='Total colorant cost including 16% VAT. '
             'Identical across all comparison lines as the same formula is applied.'
    )

    total_cost_incl_vat = fields.Float(
        string='Total Cost (Incl. VAT)',
        digits=(16, 2),
        help='Sum of base cost + colorant cost including 16% VAT. '
             'This is the minimum viable selling price to avoid a loss.'
    )

    # ============================================
    # PRICING FIELDS — EDITABLE BY USER
    # ============================================
    selling_price_incl_vat = fields.Float(
        string='Selling Price (Incl. VAT)',
        digits=(16, 2),
        help='Editable selling price including VAT. '
             'Edit this field to simulate different pricing scenarios; '
             'profit amount and margin percentage update automatically.'
    )

    # ============================================
    # PROFIT FIELDS — COMPUTED
    # ============================================
    profit_amount_incl_vat = fields.Float(
        string='Profit (Incl. VAT)',
        compute='_compute_profit',
        store=True,
        digits=(16, 2),
        help='Profit = Selling Price - Total Cost (including VAT). '
             'Negative values indicate a below-cost selling price.'
    )

    profit_margin_percent = fields.Float(
        string='Profit Margin %',
        compute='_compute_profit',
        store=True,
        digits=(16, 2),
        help='Profit margin as a percentage: (Profit / Selling Price) × 100. '
             'A margin of 0% means break-even; negative means a loss.'
    )

    # ============================================
    # COMPUTE METHODS
    # ============================================
    @api.depends('product_id')
    def _compute_brand_name(self):
        """
        Extract and return the brand name for each comparison line.

        Extraction priority:
            1. product_tmpl_id.brand_id.name  (if product_brand module installed)
            2. Search for known brand keywords in product display name
            3. Parse first non-numeric, non-unit word from display name
            4. Fallback to 'Unknown'

        Known brand list is intentionally kept simple and expanded here as
        new suppliers are onboarded. Case-insensitive matching is used.

        Examples:
            "4ltr Crown Silk Vinyl"    → "Crown"
            "4ltr Gamma Silk Vinyl"    → "Gamma"
            "4ltr Plascon Vinyl Silk"  → "Plascon"
            "4ltr Brilliant White"     → "Unknown" (no known brand keyword)
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: _compute_brand_name — processing %d line(s)", len(self))
        _logger.info("=" * 80)

        for line in self:
            line_ref = f"Line ID {line.id}" if line.id else "New Line"
            _logger.debug("  [%s] Starting brand extraction", line_ref)

            if not line.product_id:
                line.brand_name = 'Unknown'
                _logger.debug("  [%s] No product set → brand = 'Unknown'", line_ref)
                continue

            _logger.debug(
                "  [%s] Product: %s (ID: %s)",
                line_ref, line.product_id.display_name, line.product_id.id
            )

            # ── STEP 1: Try brand_id field (product_brand module) ─────────────
            try:
                if hasattr(line.product_id.product_tmpl_id, 'brand_id') and \
                        line.product_id.product_tmpl_id.brand_id:
                    line.brand_name = line.product_id.product_tmpl_id.brand_id.name
                    _logger.info(
                        "  [%s] ✅ Brand from brand_id field: '%s'",
                        line_ref, line.brand_name
                    )
                    continue
            except AttributeError:
                _logger.debug(
                    "  [%s] product_brand module not installed — using fallback extraction",
                    line_ref
                )

            # ── STEP 2: Search for known brand keywords ───────────────────────
            product_name = line.product_id.display_name or ''
            name_lower = product_name.lower()
            _logger.debug(
                "  [%s] Searching known brands in: '%s'", line_ref, product_name
            )

            known_brands = [
                'crown', 'gamma', 'plascon', 'dulux', 'robbialac',
                'sadolin', 'basco', 'royal', 'maroo', 'neuce', 'neucesilk'
            ]

            brand_found = False
            for brand in known_brands:
                if brand in name_lower:
                    line.brand_name = brand.capitalize()
                    _logger.info(
                        "  [%s] ✅ Matched known brand keyword '%s' → '%s'",
                        line_ref, brand, line.brand_name
                    )
                    brand_found = True
                    break

            if brand_found:
                continue

            # ── STEP 3: Parse first non-numeric, non-unit word ────────────────
            parts = product_name.split()
            _logger.debug(
                "  [%s] No known brand found — parsing name parts: %s",
                line_ref, parts
            )

            for part in parts:
                if not any(char.isdigit() for char in part.lower()) and \
                        part.lower() not in ['ltr', 'litre', 'l', 'litres']:
                    line.brand_name = part.capitalize()
                    _logger.info(
                        "  [%s] ✅ Extracted brand from name parts: '%s'",
                        line_ref, line.brand_name
                    )
                    brand_found = True
                    break

            if not brand_found:
                line.brand_name = 'Unknown'
                _logger.warning(
                    "  [%s] ⚠️ Could not extract brand for '%s' → using 'Unknown'",
                    line_ref, product_name
                )

        _logger.info(
            "✅ _compute_brand_name completed for %d line(s)", len(self)
        )
        _logger.info("=" * 80)

    @api.depends('selling_price_incl_vat', 'total_cost_incl_vat')
    def _compute_profit(self):
        """
        Calculate profit amount and profit margin percentage.

        Called automatically when selling_price_incl_vat or
        total_cost_incl_vat changes (store=True dependency chain).

        Formulas:
            Profit Amount = Selling Price - Total Cost
            Profit Margin = (Profit Amount / Selling Price) × 100

        Edge cases:
            - selling_price_incl_vat = 0  → margin = 0.0 (avoids division by zero)
            - Negative profit             → line renders in red (decoration-danger)

        Examples:
            Selling Price = 3,500 KES | Total Cost = 2,800 KES
            Profit = 700 KES | Margin = 20.00%

            Selling Price = 2,500 KES | Total Cost = 2,800 KES
            Profit = -300 KES | Margin = -12.00% (loss scenario)
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: _compute_profit — processing %d line(s)", len(self))
        _logger.info("=" * 80)

        for line in self:
            line_ref = f"Line ID {line.id}" if line.id else "New Line"
            brand = line.brand_name or 'Unknown'
            _logger.debug("  [%s | %s] Computing profit...", line_ref, brand)

            if line.selling_price_incl_vat and line.total_cost_incl_vat:
                line.profit_amount_incl_vat = (
                    line.selling_price_incl_vat - line.total_cost_incl_vat
                )

                if line.selling_price_incl_vat > 0:
                    line.profit_margin_percent = (
                        line.profit_amount_incl_vat / line.selling_price_incl_vat
                    ) * 100
                else:
                    line.profit_margin_percent = 0.0

                _logger.info(
                    "  [%s | %s] Selling: %.2f KES | Cost: %.2f KES | "
                    "Profit: %.2f KES | Margin: %.2f%%",
                    line_ref, brand,
                    line.selling_price_incl_vat,
                    line.total_cost_incl_vat,
                    line.profit_amount_incl_vat,
                    line.profit_margin_percent
                )

                if line.profit_amount_incl_vat < 0:
                    _logger.warning(
                        "  [%s | %s] ⚠️ LOSS SCENARIO: selling %.2f < cost %.2f "
                        "(loss = %.2f KES)",
                        line_ref, brand,
                        line.selling_price_incl_vat,
                        line.total_cost_incl_vat,
                        abs(line.profit_amount_incl_vat)
                    )
            else:
                line.profit_amount_incl_vat = 0.0
                line.profit_margin_percent = 0.0
                _logger.debug(
                    "  [%s | %s] No price or cost set → profit = 0",
                    line_ref, brand
                )

        _logger.info(
            "✅ _compute_profit completed for %d line(s)", len(self)
        )
        _logger.info("=" * 80)

    # ============================================
    # ONCHANGE — BELOW-COST PRICE VALIDATION
    # ============================================
    @api.onchange('selling_price_incl_vat')
    def _onchange_selling_price_validate(self):
        """
        Warn immediately if the user sets a selling price below total cost.

        Fires as soon as the field loses focus (before record save).
        Does NOT block saving — it is a warning, not a hard constraint.
        Hard blocking is enforced at product creation time in tint.wizard.

        Returns:
            dict: {'warning': {...}} if price is below cost, else None.

        Example warning:
            Brand: Crown
            Selling price (2,500.00 KES) is BELOW total cost (2,800.00 KES).
            Loss per unit: 300.00 KES
            Minimum price to break even: 2,800.00 KES
        """
        _logger.info(
            "🎯 ONCHANGE: _onchange_selling_price_validate triggered"
        )

        for line in self:
            line_ref = f"Line ID {line.id}" if line.id else "New Line"
            brand = line.brand_name or 'Unknown'

            _logger.debug(
                "  [%s | %s] Selling price changed to: %.2f KES",
                line_ref, brand, line.selling_price_incl_vat or 0.0
            )

            if line.selling_price_incl_vat and line.total_cost_incl_vat:
                if line.selling_price_incl_vat < line.total_cost_incl_vat:
                    shortage = line.total_cost_incl_vat - line.selling_price_incl_vat
                    _logger.warning(
                        "  [%s | %s] ⚠️ Below-cost price detected: "
                        "selling %.2f KES < cost %.2f KES | loss = %.2f KES",
                        line_ref, brand,
                        line.selling_price_incl_vat,
                        line.total_cost_incl_vat,
                        shortage
                    )
                    return {
                        'warning': {
                            'title': f'⚠ Below Cost — {brand}',
                            'message': (
                                f"Selling price ({line.selling_price_incl_vat:.2f} KES) is "
                                f"BELOW total cost ({line.total_cost_incl_vat:.2f} KES).\n\n"
                                f"Loss per unit: {shortage:.2f} KES\n\n"
                                f"Minimum price to break even: "
                                f"{line.total_cost_incl_vat:.2f} KES"
                            )
                        }
                    }
                else:
                    _logger.debug(
                        "  [%s | %s] ✅ Price %.2f KES is above cost %.2f KES — OK",
                        line_ref, brand,
                        line.selling_price_incl_vat,
                        line.total_cost_incl_vat
                    )

    # ============================================
    # ACTION METHODS
    # ============================================
    def action_use_this_product(self):
        """
        Switch the parent tint wizard to use this line's product as the base.

        Handles both normal (no scaling) and volume-scaled scenarios.
        When scaling is active the parent wizard's colorant lines are updated
        with the scaled shot values stored in scaled_colorant_shots_json.

        Process:
            1. Locate and validate parent tint wizard
            2. Determine whether volume scaling is active
            3. Disable formula auto-fill flags to preserve shots
            4. Write new base_variant_id and selling_price_incl_vat to parent
            5. If scaled: write scaled colorant shots to each parent line
            6. Force recompute of all parent wizard cost fields
            7. Invalidate cache and reopen parent wizard form

        Returns:
            dict: ir.actions.act_window action to reopen parent tint wizard

        Raises:
            UserError: If parent wizard has expired or update fails
        """
        self.ensure_one()

        _logger.info("=" * 80)
        _logger.info("🎯 ACTION: action_use_this_product")
        _logger.info("=" * 80)
        _logger.info("  Line ID:            %s", self.id)
        _logger.info("  Product:            %s", self.product_id.display_name)
        _logger.info("  Product ID:         %s", self.product_id.id)
        _logger.info("  Brand:              %s", self.brand_name)
        _logger.info("  Product UOM:        %s", self.product_id.uom_id.name)
        _logger.info("  Base cost:          %.2f KES", self.base_cost_incl_vat)
        _logger.info("  Colorant cost:      %.2f KES", self.colorant_cost_incl_vat)
        _logger.info("  Total cost:         %.2f KES", self.total_cost_incl_vat)
        _logger.info("  Selling price:      %.2f KES", self.selling_price_incl_vat)

        # ── STEP 1: Get parent wizard ─────────────────────────────────────────
        _logger.info("📋 STEP 1: Locating parent tint wizard...")

        parent_wizard = self.wizard_id.parent_wizard_id
        if not parent_wizard.exists():
            _logger.error(
                "❌ Parent tint wizard not found or has expired! "
                "wizard_id=%s parent_wizard_id=%s",
                self.wizard_id.id,
                self.wizard_id.parent_wizard_id.id
            )
            raise UserError(
                "Parent tint wizard has expired or not found!\n\n"
                "Please close this window and start over."
            )

        _logger.info(
            "  ✅ Parent wizard ID: %s | Base: %s | UOM: %s | Price: %.2f KES",
            parent_wizard.id,
            parent_wizard.base_variant_id.display_name,
            parent_wizard.base_variant_id.uom_id.name,
            parent_wizard.selling_price_incl_vat
        )

        # ── STEP 2: Check volume scaling ──────────────────────────────────────
        _logger.info("📋 STEP 2: Checking volume scaling state...")

        is_scaled = (
            self.wizard_id.show_scaled_products and
            self.wizard_id.scale_factor != 1.0
        )

        if is_scaled:
            _logger.info(
                "  🔄 VOLUME SCALING ACTIVE | "
                "Source: %s (%.2fL) | Target: %s (%.2fL) | Factor: %.4f×",
                self.wizard_id.source_uom_id.name,
                self.wizard_id.source_volume_litres,
                self.wizard_id.target_uom_id.name,
                self.wizard_id.target_volume_litres,
                self.wizard_id.scale_factor
            )
        else:
            _logger.info(
                "  ✅ No scaling active — only base product and price will update"
            )

        # ── STEP 3: Disable formula auto-fill ────────────────────────────────
        _logger.info("📋 STEP 3: Disabling formula auto-fill to preserve shots...")

        parent_wizard.formula_applied = False
        parent_wizard.formula_id = False
        _logger.info("  ✅ formula_applied=False | formula_id=False")

        # ── STEP 4: Update base product and selling price ─────────────────────
        _logger.info("📋 STEP 4: Updating base product and selling price on parent...")

        try:
            parent_wizard.with_context(skip_formula_search=True).write({
                'base_variant_id': self.product_id.id,
                'selling_price_incl_vat': self.selling_price_incl_vat,
                'selling_price_manually_set': True,
            })
            _logger.info(
                "  ✅ base_variant_id → %s | selling_price → %.2f KES | manually_set=True",
                self.product_id.display_name,
                self.selling_price_incl_vat
            )
        except Exception as e:
            _logger.error(
                "❌ Failed to update parent wizard (Step 4): %s", str(e)
            )
            raise UserError(f"Failed to update parent wizard: {str(e)}")

        # ── STEP 5: Update colorant shots if scaled ───────────────────────────
        if is_scaled:
            _logger.info("=" * 80)
            _logger.info("📋 STEP 5: Applying scaled colorant shots to parent wizard...")
            _logger.info("=" * 80)

            try:
                scaled_shots = json.loads(
                    self.wizard_id.scaled_colorant_shots_json or '{}'
                )
                _logger.info(
                    "  Parsed %d scaled colorant entries from JSON",
                    len(scaled_shots)
                )

                if not scaled_shots:
                    _logger.warning(
                        "  ⚠️ scaled_colorant_shots_json is empty — "
                        "no colorant shots will be updated!"
                    )
                else:
                    for code, data in scaled_shots.items():
                        _logger.info(
                            "    %s: %.2f shots (scaled)", code, data['shots']
                        )

                lines_updated = 0
                for line in parent_wizard.colorant_line_ids:
                    if line.colorant_code in scaled_shots:
                        old_shots = line.shots
                        new_shots = scaled_shots[line.colorant_code]['shots']

                        _logger.info(
                            "    Updating %s: %.2f → %.2f shots (%+.2f)",
                            line.colorant_code, old_shots, new_shots,
                            new_shots - old_shots
                        )

                        line.write({'shots': new_shots})

                        # Force field recomputation after write
                        _logger.debug(
                            "    🔄 Forcing recomputation on %s...",
                            line.colorant_code
                        )
                        line._compute_ml_volume()
                        line._compute_qty_litres()
                        line._compute_unit_cost_incl_vat()
                        line._compute_line_costs()
                        line._compute_available_stock()
                        line._compute_stock_warning()
                        _logger.debug(
                            "    ✅ %s recomputed | ml=%.3f | qty=%.6fL",
                            line.colorant_code, line.ml_volume, line.qty_litres
                        )
                        lines_updated += 1

                _logger.info(
                    "  ✅ SCALING COMPLETE: %d colorant line(s) updated",
                    lines_updated
                )

            except json.JSONDecodeError as e:
                _logger.error(
                    "❌ JSON decode error on scaled_colorant_shots_json: %s", str(e)
                )
                raise UserError(f"Failed to parse scaled colorant shots: {str(e)}")
            except Exception as e:
                import traceback
                _logger.error(
                    "❌ Error updating colorant shots (Step 5): %s\n%s",
                    str(e), traceback.format_exc()
                )
                raise UserError(f"Failed to update colorant shots: {str(e)}")
        else:
            _logger.info("📋 STEP 5: Skipped (no volume scaling active)")

        # ── STEP 6: Force parent wizard recomputation ─────────────────────────
        _logger.info("=" * 80)
        _logger.info("📋 STEP 6: Forcing parent wizard field recomputation...")
        _logger.info("=" * 80)

        try:
            parent_wizard._compute_base_cost()
            _logger.info(
                "  ✅ _compute_base_cost() | base_cost_incl=%.2f KES",
                parent_wizard.base_cost_incl_vat
            )

            parent_wizard._compute_totals()
            _logger.info(
                "  ✅ _compute_totals() | total_ml=%.2f | total_cost=%.2f KES",
                parent_wizard.total_colorant_ml,
                parent_wizard.total_cost_incl_vat
            )

            parent_wizard._compute_warnings()
            _logger.info(
                "  ✅ _compute_warnings() | stock_warnings=%s",
                parent_wizard.has_stock_warnings
            )

        except Exception as e:
            import traceback
            _logger.error(
                "⚠️ Recomputation error (Step 6) — wizard will still reopen: "
                "%s\n%s", str(e), traceback.format_exc()
            )
            # Do not re-raise — allow wizard to reopen even if compute fails

        # ── STEP 7: Invalidate cache and reopen ───────────────────────────────
        _logger.info("📋 STEP 7: Invalidating cache and reopening parent wizard...")

        try:
            parent_wizard.invalidate_recordset()
            _logger.info("  ✅ Cache invalidated — UI will show fresh data")
        except Exception as e:
            _logger.warning("  ⚠️ Cache invalidation warning (non-fatal): %s", str(e))

        # ── Final Summary ─────────────────────────────────────────────────────
        _logger.info("=" * 80)
        _logger.info("✅ action_use_this_product COMPLETED SUCCESSFULLY")
        _logger.info("=" * 80)
        _logger.info("  Base Product:    %s", parent_wizard.base_variant_id.display_name)
        _logger.info("  Base UOM:        %s", parent_wizard.base_variant_id.uom_id.name)
        _logger.info("  Base Cost:       %.2f KES", parent_wizard.base_cost_incl_vat)
        _logger.info("  Colorant Cost:   %.2f KES", parent_wizard.colorant_cost_incl_vat)
        _logger.info("  Total Cost:      %.2f KES", parent_wizard.total_cost_incl_vat)
        _logger.info("  Selling Price:   %.2f KES", parent_wizard.selling_price_incl_vat)
        _logger.info("  Profit:          %.2f KES", parent_wizard.profit_amount_incl_vat)
        if is_scaled:
            _logger.info(
                "  Volume Scaled:   %.0fL → %.0fL (%.2f×)",
                self.wizard_id.source_volume_litres,
                self.wizard_id.target_volume_litres,
                self.wizard_id.scale_factor
            )
        _logger.info("=" * 80)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Paint Tinting Wizard',
            'res_model': 'tint.wizard',
            'res_id': parent_wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }


class CostComparisonWizard(models.TransientModel):
    """
    Main cost comparison wizard for comparing paint products across brands.

    Enhanced with:
    - Attribute Equivalency Map (_ATTRIBUTE_EQUIVALENCY_MAP): defines groups
      of interchangeable base product attributes so that products like
      "Pastel Base", "Brilliant White", "White", "B1", "W0" are treated as
      the same group and always compared together.
    - Volume Scaling: translate colorant formula to different package sizes.
    - Automatic shot scaling based on volume ratio (target ÷ source).
    - One-click "Use This" to update parent wizard with selected product
      and (optionally) scaled formula.

    Usage Flow:
        1. User opens tint wizard, selects base product, enters colorant shots
        2. User clicks "Compare Costs Across Brands"
        3. This wizard opens with all similar products and colorant costs
        4. OPTIONAL: Enable scaling and enter target volume (e.g. 20L)
        5. System finds products in target UOM and scales colorant shots
        6. User edits prices inline, observing profit/margin changes
        7. User clicks "Use This" → parent wizard switches to selected product

    Architecture:
        - Configuration data collected in default_get()
        - Comparison lines created in create() AFTER wizard record exists
        - Attribute matching uses canonical group names from equivalency map
    """

    _name = 'cost.comparison.wizard'
    _description = 'Cost Comparison Wizard with Volume Scaling and Attribute Equivalency'

    # ============================================
    # ATTRIBUTE EQUIVALENCY MAP
    # ─────────────────────────────────────────────
    # Groups interchangeable base product attributes.
    # Any attribute keyword that maps to the same group name will be treated
    # as identical during product comparison searches.
    #
    # To add a new equivalency:
    #   1. Add the keyword (lowercase) → canonical group name
    #   2. No logic changes needed — _normalize_attribute_name() handles it
    #
    # Keyword matching order (in _normalize_attribute_name):
    #   1. Full string match
    #   2. Word-by-word match (splits on space, '/', '-')
    #   3. Substring match
    #   4. No match → return raw attribute unchanged (exact match still works)
    # ============================================
    _ATTRIBUTE_EQUIVALENCY_MAP = {
        # ── Pastel / Brilliant White / White group ────────────────────────────
        # These bases are interchangeable for tinting light/neutral colours.
        'pastel base':       'pastel_white_group',
        'pastel':            'pastel_white_group',
        'b1':                'pastel_white_group',
        'w0':                'pastel_white_group',
        'brilliant white':   'pastel_white_group',
        'white':             'pastel_white_group',
        'brilliant':         'pastel_white_group',
        # ── Deep Base group ───────────────────────────────────────────────────
        'deep base':         'deep_base_group',
        'deep':              'deep_base_group',
        'b3':                'deep_base_group',
        # ── Medium Base group ─────────────────────────────────────────────────
        'medium base':       'medium_base_group',
        'medium':            'medium_base_group',
        'b2':                'medium_base_group',
        # ── Accent Base group ─────────────────────────────────────────────────
        'accent base':       'accent_base_group',
        'accent':            'accent_base_group',
        'b4':                'accent_base_group',
    }

    # ============================================
    # RELATIONSHIP FIELDS
    # ============================================
    parent_wizard_id = fields.Many2one(
        'tint.wizard',
        string='Parent Tint Wizard',
        required=True,
        ondelete='cascade',
        help='Reference to the tint wizard that opened this comparison. '
             'Used to update base_variant_id and colorant shots when '
             '"Use This" is clicked on a comparison line.'
    )

    # ============================================
    # COMPARISON CRITERIA
    # ============================================
    base_category_id = fields.Many2one(
        'product.category',
        string='Category',
        readonly=True,
        help='Product category from the parent wizard\'s base product '
             '(e.g. Vinyl Silk, Matt Emulsion). Used as the primary search filter.'
    )

    base_attribute_name = fields.Char(
        string='Attribute',
        readonly=True,
        help='Canonical attribute name after equivalency normalization '
             '(e.g. "pastel_white_group", "deep_base_group"). '
             'This is what all comparison lines are filtered against.'
    )

    # ============================================
    # COLORANT FORMULA — STORED AS JSON
    # ============================================
    colorant_shots_json = fields.Text(
        string='Original Colorant Shots (JSON)',
        help='Snapshot of colorant shots from the parent wizard at the time '
             'this comparison was opened. Stored as JSON: '
             '{colorant_code: {shots, unit_cost_excl_vat}}. '
             'Used to calculate colorant costs for all comparison lines.'
    )

    # ============================================
    # COMPARISON LINES
    # ============================================
    comparison_line_ids = fields.One2many(
        'cost.comparison.line',
        'wizard_id',
        string='Product Comparisons',
        help='One line per similar product found. Lines are created in '
             'create() after the wizard record exists so child records '
             'can reference a valid parent wizard_id.'
    )

    # ============================================
    # VOLUME SCALING FIELDS
    # ============================================
    source_uom_id = fields.Many2one(
        'uom.uom',
        string='Source UOM',
        readonly=True,
        help='UOM of the current base product (e.g. 4L). '
             'Used as the denominator when calculating the scale factor.'
    )

    source_volume_litres = fields.Float(
        string='Source Volume (Litres)',
        compute='_compute_source_volume',
        digits=(16, 4),
        help='Source UOM converted to litres. '
             'Computed from source_uom_id via UOM conversion API.'
    )

    show_scaled_products = fields.Boolean(
        string='Show Different Volume',
        default=False,
        help='Enable to search products in a different package size and '
             'scale the colorant formula accordingly. '
             'Click "Refresh Products" after enabling and entering target volume.'
    )

    target_volume_litres = fields.Float(
        string='Target Volume (Litres)',
        default=0.0,
        digits=(16, 4),
        help='Desired package size in litres (e.g. 20.0 for a 20L tin). '
             'System searches for a matching UOM and scales shots proportionally.'
    )

    target_uom_id = fields.Many2one(
        'uom.uom',
        string='Target UOM',
        compute='_compute_target_uom',
        help='UOM record found by searching common naming patterns for the '
             'target volume (e.g. "20L", "20ltr"). Falls back to litres UOM '
             'if no specific record found.'
    )

    scale_factor = fields.Float(
        string='Scale Factor',
        compute='_compute_scale_factor',
        digits=(16, 6),
        help='Multiplier applied to all colorant shots: '
             'Scale Factor = Target Volume ÷ Source Volume. '
             'Example: 20L ÷ 4L = 5.0× (all shots multiplied by 5)'
    )

    shots_per_litre = fields.Float(
        string='Shots per Litre',
        compute='_compute_shots_per_litre',
        digits=(16, 6),
        help='Total shots from original formula divided by source volume. '
             'Informational field for the user to understand formula density.'
    )

    scaled_colorant_shots_json = fields.Text(
        string='Scaled Colorant Shots (JSON)',
        compute='_compute_scaled_shots',
        help='Original colorant shots multiplied by scale_factor, stored as JSON. '
             'Used to update parent wizard\'s colorant lines when "Use This" is '
             'clicked while scaling is active.'
    )

    # ============================================
    # STATISTICS
    # ============================================
    total_products = fields.Integer(
        string='Total Products',
        compute='_compute_statistics',
        help='Total number of similar products found in the search'
    )

    avg_cost = fields.Float(
        string='Average Cost',
        compute='_compute_statistics',
        digits=(16, 2),
        help='Average total cost (incl. VAT) across all comparison lines'
    )

    lowest_cost = fields.Float(
        string='Lowest Cost',
        compute='_compute_statistics',
        digits=(16, 2),
        help='Minimum total cost across all comparison lines. '
             'Lines with this cost are highlighted green in the list view.'
    )

    highest_profit = fields.Float(
        string='Highest Profit',
        compute='_compute_statistics',
        digits=(16, 2),
        help='Maximum profit amount achievable at the default 30% markup'
    )

    # ============================================
    # DEFAULT_GET — CONFIGURATION ONLY (NO LINES)
    # ============================================
    @api.model
    def default_get(self, fields_list):
        """
        Initialise wizard configuration from the parent tint wizard.

        Collects all data needed to populate comparison lines but does NOT
        create lines here. Lines are created in create() after the wizard
        record has a valid database ID.

        Steps:
            1. Read parent_wizard_id from context
            2. Extract base product category, UOM, attribute
            3. Normalize attribute via _normalize_attribute_name()
               (equivalency group resolution happens here)
            4. Snapshot colorant shots from parent wizard as JSON
            5. Set default target volume = source volume (no scaling initially)
            6. Disable scaling by default

        Args:
            fields_list (list): Field names requested by the form view

        Returns:
            dict: Default values for wizard fields (NO comparison_line_ids)

        Raises:
            UserError: If no parent wizard in context or parent does not exist
        """
        _logger.info("=" * 80)
        _logger.info("🚀 DEFAULT_GET: CostComparisonWizard initialising...")
        _logger.info("=" * 80)

        res = super(CostComparisonWizard, self).default_get(fields_list)
        _logger.debug("  Super default_get keys: %s", list(res.keys()))

        # ── STEP 1: Get parent wizard ─────────────────────────────────────────
        _logger.info("📋 STEP 1: Reading parent_wizard_id from context...")

        parent_wizard_id = (
            self.env.context.get('default_parent_wizard_id') or
            self.env.context.get('parent_wizard_id')
        )

        _logger.debug("  Context keys: %s", list(self.env.context.keys()))
        _logger.debug("  parent_wizard_id from context: %s", parent_wizard_id)

        if not parent_wizard_id:
            _logger.error(
                "❌ No parent_wizard_id found in context! "
                "Available keys: %s",
                list(self.env.context.keys())
            )
            raise UserError("No parent wizard specified in context!")

        parent_wizard = self.env['tint.wizard'].browse(parent_wizard_id)
        if not parent_wizard.exists():
            _logger.error(
                "❌ Parent tint wizard ID %s does not exist!", parent_wizard_id
            )
            raise UserError(
                f"Parent tint wizard (ID: {parent_wizard_id}) not found!"
            )

        res['parent_wizard_id'] = parent_wizard.id
        _logger.info(
            "  ✅ Parent wizard found: ID %s | Base: %s",
            parent_wizard.id,
            parent_wizard.base_variant_id.display_name if parent_wizard.base_variant_id else 'None'
        )

        # ── STEP 2: Extract base product details ──────────────────────────────
        _logger.info("=" * 80)
        _logger.info("📋 STEP 2: Extracting base product details...")
        _logger.info("=" * 80)

        base_product = parent_wizard.base_variant_id
        if not base_product:
            _logger.error("❌ Parent wizard has no base product selected!")
            raise UserError("No base product selected in parent wizard!")

        _logger.info(
            "  Base product: %s (ID: %s)",
            base_product.display_name, base_product.id
        )
        _logger.info(
            "  Category:     %s (ID: %s)",
            base_product.categ_id.name, base_product.categ_id.id
        )
        _logger.info(
            "  UOM:          %s (ID: %s)",
            base_product.uom_id.name, base_product.uom_id.id
        )

        res['base_category_id'] = base_product.categ_id.id
        res['source_uom_id'] = base_product.uom_id.id
        _logger.info("  ✅ Category and source UOM stored")

        # Extract raw attribute then normalize (equivalency group resolution)
        raw_attribute = self._extract_attribute_name(base_product)
        _logger.info("  Raw attribute extracted: '%s'", raw_attribute)

        canonical_attribute = self._normalize_attribute_name(raw_attribute)
        res['base_attribute_name'] = canonical_attribute
        _logger.info(
            "  Canonical attribute (after normalization): '%s'",
            canonical_attribute
        )

        if raw_attribute != canonical_attribute:
            _logger.info(
                "  🔗 Equivalency applied: '%s' → '%s'",
                raw_attribute, canonical_attribute
            )
        else:
            _logger.info(
                "  ℹ️ No equivalency mapping — using raw attribute as-is"
            )

        # ── STEP 3: Snapshot colorant shots as JSON ───────────────────────────
        _logger.info("=" * 80)
        _logger.info("📋 STEP 3: Snapshotting colorant shots from parent wizard...")
        _logger.info("=" * 80)

        colorant_shots = {}
        _logger.info(
            "  Total colorant lines in parent: %d",
            len(parent_wizard.colorant_line_ids)
        )

        for line in parent_wizard.colorant_line_ids:
            if line.shots > 0:
                colorant_shots[line.colorant_code] = {
                    'shots': line.shots,
                    'unit_cost_excl_vat': line.unit_cost_excl_vat or 0.0
                }
                _logger.debug(
                    "    %s: %.2f shots @ %.2f KES/L",
                    line.colorant_code, line.shots, line.unit_cost_excl_vat
                )

        res['colorant_shots_json'] = json.dumps(colorant_shots)
        _logger.info(
            "  ✅ Snapshotted %d colorant(s) with shots > 0", len(colorant_shots)
        )

        if not colorant_shots:
            _logger.warning(
                "  ⚠️ No colorant shots found in parent wizard — "
                "comparison will show base cost only"
            )

        # ── STEP 4: Set default target volume ────────────────────────────────
        _logger.info("=" * 80)
        _logger.info("📋 STEP 4: Setting default target volume from source UOM...")
        _logger.info("=" * 80)

        try:
            reference_uom = self.env.ref('uom.product_uom_litre')
            source_volume = base_product.uom_id._compute_quantity(
                1.0, reference_uom, round=False
            )
            res['target_volume_litres'] = source_volume
            _logger.info(
                "  ✅ Source UOM '%s' → %.4f litres | target_volume_litres set to same",
                base_product.uom_id.name, source_volume
            )
        except Exception as e:
            _logger.error(
                "❌ UOM conversion failed (Step 4): %s | defaulting to 0.0", str(e)
            )
            res['target_volume_litres'] = 0.0

        # ── STEP 5: Scaling disabled by default ───────────────────────────────
        res['show_scaled_products'] = False
        _logger.info("  ✅ show_scaled_products=False (scaling off by default)")

        _logger.info("=" * 80)
        _logger.info("✅ DEFAULT_GET complete — wizard ready for create()")
        _logger.info(
            "   parent=%s | category=%s | attribute='%s' | colorants=%d",
            res.get('parent_wizard_id'),
            base_product.categ_id.name,
            canonical_attribute,
            len(colorant_shots)
        )
        _logger.info("=" * 80)

        return res

    # ============================================
    # CREATE METHOD — LINE CREATION HAPPENS HERE
    # ============================================
    @api.model_create_multi
    def create(self, vals_list):
        """
        Create wizard record(s) and immediately populate comparison lines.

        Architecture note: comparison lines cannot be created in default_get()
        because TransientModel records do not have a database ID at that stage.
        Lines must reference a valid wizard_id foreign key, so they are created
        here after super().create() has assigned IDs.

        Process:
            1. Call super().create() to persist wizard record(s)
            2. For each wizard: call _populate_comparison_lines()

        Args:
            vals_list (list[dict]): List of field values for each wizard to create

        Returns:
            recordset: Created cost.comparison.wizard record(s)

        Raises:
            Any exception raised by _populate_comparison_lines() (re-raised)
        """
        _logger.info("=" * 80)
        _logger.info("🚀 CREATE: CostComparisonWizard — creating %d record(s)...", len(vals_list))
        _logger.info("=" * 80)

        for i, vals in enumerate(vals_list, 1):
            _logger.debug("  Wizard %d vals keys: %s", i, list(vals.keys()))

        # STEP 1: Persist wizard records
        _logger.info("📋 STEP 1: Calling super().create()...")
        wizards = super().create(vals_list)
        _logger.info("  ✅ %d wizard record(s) created", len(wizards))

        for w in wizards:
            _logger.info(
                "    Wizard ID: %s | parent: %s | source_uom: %s | scaling: %s",
                w.id, w.parent_wizard_id.id,
                w.source_uom_id.name if w.source_uom_id else 'None',
                w.show_scaled_products
            )

        # STEP 2: Populate comparison lines
        _logger.info("=" * 80)
        _logger.info("📋 STEP 2: Populating comparison lines for each wizard...")
        _logger.info("=" * 80)

        for wizard in wizards:
            _logger.info("  Processing wizard ID: %s...", wizard.id)
            try:
                wizard._populate_comparison_lines()
                _logger.info(
                    "  ✅ Wizard %s: %d comparison line(s) created",
                    wizard.id, len(wizard.comparison_line_ids)
                )
            except Exception as e:
                import traceback
                _logger.error(
                    "❌ _populate_comparison_lines failed for wizard %s: "
                    "%s\n%s", wizard.id, str(e), traceback.format_exc()
                )
                raise

        _logger.info("=" * 80)
        _logger.info(
            "✅ CREATE complete — %d wizard(s) ready", len(wizards)
        )
        _logger.info("=" * 80)

        return wizards

    # ============================================
    # POPULATE COMPARISON LINES — CORE METHOD
    # ============================================
    def _populate_comparison_lines(self):
        """
        Search for similar products and create one comparison line per product.

        Called from create() after the wizard record exists.

        Behaviour with volume scaling:
            - show_scaled_products=False: search source_uom_id, use original shots
            - show_scaled_products=True:  search target_uom_id, use scaled shots

        Behaviour with attribute equivalency:
            - base_attribute_name is already a canonical group name (set in default_get)
            - _extract_attribute_name() on each candidate product also normalizes
              through _normalize_attribute_name() before comparison
            - So "brilliant white" → "pastel_white_group" matches
              "pastel base" → "pastel_white_group" ✅

        Process:
            1. Determine UOM and shots JSON to use (original or scaled)
            2. Parse colorant shots from JSON
            3. Domain search: same category + UOM, exclude colorants/tinted
            4. Python filter: canonical attribute must match base_attribute_name
            5. For each product: calculate base cost, colorant cost, total cost
            6. Create comparison line record with 30% markup as default price

        Raises:
            Exception: Re-raises any error during line creation for debugging
        """
        self.ensure_one()

        _logger.info("=" * 80)
        _logger.info("🔍 _populate_comparison_lines — Wizard ID: %s", self.id)
        _logger.info("=" * 80)

        # ── STEP 1: Determine UOM and shots source ────────────────────────────
        _logger.info("📋 STEP 1: Determining search UOM and colorant shots source...")

        if self.show_scaled_products and self.target_uom_id:
            search_uom_id = self.target_uom_id.id
            search_uom_name = self.target_uom_id.name
            colorant_shots_json = self.scaled_colorant_shots_json or '{}'

            _logger.info("  🔄 VOLUME SCALING ACTIVE")
            _logger.info(
                "  Source: %s (%.2fL) | Target: %s (%.2fL) | Factor: %.4f×",
                self.source_uom_id.name, self.source_volume_litres,
                search_uom_name, self.target_volume_litres,
                self.scale_factor
            )
            _logger.info("  Using SCALED colorant shots")
        else:
            search_uom_id = self.source_uom_id.id
            search_uom_name = self.source_uom_id.name
            colorant_shots_json = self.colorant_shots_json or '{}'

            _logger.info("  ✅ No scaling — using original UOM and shots")
            _logger.info("  Search UOM: %s", search_uom_name)

        # ── STEP 2: Parse colorant shots ──────────────────────────────────────
        _logger.info("=" * 80)
        _logger.info("📋 STEP 2: Parsing colorant shots from JSON...")
        _logger.info("=" * 80)

        try:
            colorant_shots = json.loads(colorant_shots_json)
            _logger.info(
                "  ✅ Parsed %d colorant entry/entries", len(colorant_shots)
            )
            for code, data in colorant_shots.items():
                _logger.info(
                    "    %s: %.2f shots @ %.2f KES/L",
                    code, data['shots'], data['unit_cost_excl_vat']
                )
        except json.JSONDecodeError as e:
            _logger.error("❌ JSON decode error: %s | JSON: %s...", str(e), colorant_shots_json[:100])
            colorant_shots = {}
        except Exception as e:
            _logger.error("❌ Unexpected error parsing shots JSON: %s", str(e))
            colorant_shots = {}

        if not colorant_shots:
            _logger.warning(
                "  ⚠️ No colorant shots to apply — comparison will show base cost only"
            )

        # ── STEP 3: Domain search for similar products ────────────────────────
        _logger.info("=" * 80)
        _logger.info("🔍 STEP 3: Domain search for similar products...")
        _logger.info("=" * 80)
        _logger.info("  category:  %s (ID: %s)", self.base_category_id.name, self.base_category_id.id)
        _logger.info("  UOM:       %s (ID: %s)", search_uom_name, search_uom_id)
        _logger.info("  attribute: '%s' (canonical)", self.base_attribute_name)

        domain = [
            ('categ_id', '=', self.base_category_id.id),
            ('uom_id', '=', search_uom_id),
            ('product_tmpl_id.is_colorant', '=', False),
            ('product_tmpl_id.is_tinted_product', '=', False),
        ]

        similar_products = self.env['product.product'].search(domain)
        _logger.info(
            "  Domain search returned %d product(s) before attribute filter",
            len(similar_products)
        )

        if similar_products:
            for p in similar_products:
                _logger.debug("    Found: %s (ID: %s)", p.display_name, p.id)

        # ── STEP 4: Attribute filter (canonical group comparison) ─────────────
        _logger.info("📋 STEP 4: Filtering by canonical attribute '%s'...", self.base_attribute_name)

        filtered_products = similar_products.filtered(
            lambda p: self._extract_attribute_name(p) == self.base_attribute_name
        )

        _logger.info(
            "  ✅ %d product(s) match attribute filter", len(filtered_products)
        )

        if filtered_products:
            for p in filtered_products:
                raw_attr = self._extract_raw_attribute_name(p)
                _logger.info(
                    "    ✓ %s | raw_attr='%s' → canonical='%s'",
                    p.display_name, raw_attr, self.base_attribute_name
                )
        else:
            _logger.warning("=" * 80)
            _logger.warning("⚠️ NO SIMILAR PRODUCTS FOUND after attribute filter!")
            _logger.warning("  Possible reasons:")
            _logger.warning(
                "    1. No other brands have %s products in '%s'",
                search_uom_name, self.base_category_id.name
            )
            _logger.warning(
                "    2. Attribute extraction/normalization could not match "
                "'%s' group", self.base_attribute_name
            )
            _logger.warning(
                "    3. Product naming convention inconsistency — check brackets"
            )
            _logger.warning("=" * 80)
            return

        # ── STEP 5 & 6: Calculate costs and create lines ──────────────────────
        _logger.info("=" * 80)
        _logger.info(
            "💰 STEP 5-6: Calculating costs and creating comparison lines "
            "for %d product(s)...", len(filtered_products)
        )
        _logger.info("=" * 80)

        current_product_id = self.parent_wizard_id.base_variant_id.id
        lines_created = 0
        import time
        total_time = 0.0

        for idx, product in enumerate(filtered_products, 1):
            t_start = time.time()

            _logger.info(
                "  [%d/%d] Processing: %s (ID: %s)",
                idx, len(filtered_products),
                product.display_name, product.id
            )

            is_current = (product.id == current_product_id)
            if is_current:
                _logger.info("    ⭐ This is the CURRENT product in parent wizard")

            # Base cost
            base_cost_excl = product.standard_price or 0.0
            base_cost_incl = base_cost_excl * 1.16
            _logger.debug(
                "    Base cost: %.2f KES (excl) → %.2f KES (incl 16%% VAT)",
                base_cost_excl, base_cost_incl
            )

            # Colorant cost (same formula for every product)
            colorant_cost_excl = 0.0
            for colorant_code, data in colorant_shots.items():
                shots = data['shots']
                unit_cost = data['unit_cost_excl_vat']
                ml_volume = shots * 0.616
                qty_litres = ml_volume / 1000.0
                line_cost = qty_litres * unit_cost
                colorant_cost_excl += line_cost
                _logger.debug(
                    "      %s: %.2f shots = %.3fml = %.6fL × %.2f KES = %.4f KES",
                    colorant_code, shots, ml_volume, qty_litres, unit_cost, line_cost
                )

            colorant_cost_incl = colorant_cost_excl * 1.16

            # Total cost
            total_cost_incl = base_cost_incl + colorant_cost_incl
            selling_price = total_cost_incl * 1.30

            _logger.info(
                "    Base: %.2f | Colorant: %.2f | TOTAL: %.2f KES | "
                "Selling (30%%): %.2f KES",
                base_cost_incl, colorant_cost_incl,
                total_cost_incl, selling_price
            )

            # Create comparison line
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

                line = self.env['cost.comparison.line'].create(line_vals)
                lines_created += 1
                elapsed = time.time() - t_start
                total_time += elapsed

                _logger.info(
                    "    ✅ Line ID %s created in %.3fs | "
                    "cost=%.2f KES, price=%.2f KES",
                    line.id, elapsed, total_cost_incl, selling_price
                )

            except Exception as e:
                import traceback
                _logger.error(
                    "    ❌ Failed to create comparison line for %s: "
                    "%s\n%s", product.display_name, str(e), traceback.format_exc()
                )
                raise

        _logger.info("=" * 80)
        _logger.info(
            "✅ _populate_comparison_lines COMPLETE: "
            "%d line(s) created in %.3fs total (avg %.3fs/line)",
            lines_created, total_time,
            total_time / lines_created if lines_created else 0.0
        )
        if self.show_scaled_products:
            _logger.info(
                "  🔄 Scaling was active: UOM=%s | factor=%.4f×",
                search_uom_name, self.scale_factor
            )
        _logger.info("=" * 80)

    # ============================================
    # NEW: ATTRIBUTE NORMALIZATION METHODS
    # ============================================
    def _normalize_attribute_name(self, raw_attribute):
        """
        Resolve a raw extracted attribute to its canonical equivalency group.

        Looks up raw_attribute (and its individual words / substrings) against
        _ATTRIBUTE_EQUIVALENCY_MAP. If a match is found, returns the canonical
        group name. If no match is found, returns the raw attribute unchanged so
        that attributes not listed in the map still use exact matching.

        Matching is applied in priority order:
            1. Full string match  (e.g. 'brilliant white' → 'pastel_white_group')
            2. Word-by-word match (e.g. 'pastel/b1/w0' → matches 'pastel')
            3. Substring match    (e.g. 'brilliant white base' → matches 'brilliant white')
            4. No match           → return raw_attribute as-is

        All comparisons are case-insensitive (input is lowercased before lookup).

        Args:
            raw_attribute (str): Extracted attribute string, already lowercased
                                 by _extract_attribute_name().

        Returns:
            str: Canonical group name (e.g. 'pastel_white_group') if mapped,
                 otherwise the original raw_attribute string.

        Examples:
            'pastel base'     → 'pastel_white_group'   (full match)
            'pastel/b1/w0'    → 'pastel_white_group'   (word match on 'pastel')
            'brilliant white' → 'pastel_white_group'   (full match)
            'brilliant white base' → 'pastel_white_group' (substring match)
            'deep base'       → 'deep_base_group'      (full match)
            'gloss'           → 'gloss'                (no match, returned as-is)
            'unknown'         → 'unknown'              (no match, returned as-is)
        """
        if not raw_attribute:
            _logger.debug(
                "  _normalize_attribute_name: empty input → returning 'unknown'"
            )
            return 'unknown'

        attribute_lower = raw_attribute.lower().strip()
        _logger.debug(
            "  _normalize_attribute_name: normalizing '%s'...", attribute_lower
        )

        # ── Priority 1: Full string match ─────────────────────────────────────
        if attribute_lower in self._ATTRIBUTE_EQUIVALENCY_MAP:
            canonical = self._ATTRIBUTE_EQUIVALENCY_MAP[attribute_lower]
            _logger.info(
                "  🔗 Equivalency [full match]: '%s' → '%s'",
                attribute_lower, canonical
            )
            return canonical

        # ── Priority 2: Word-by-word match ────────────────────────────────────
        # Handles 'pastel/b1/w0' → split to ['pastel', 'b1', 'w0']
        words = attribute_lower.replace('/', ' ').replace('-', ' ').split()
        _logger.debug(
            "  _normalize_attribute_name: word tokens: %s", words
        )

        for word in words:
            word = word.strip()
            if word in self._ATTRIBUTE_EQUIVALENCY_MAP:
                canonical = self._ATTRIBUTE_EQUIVALENCY_MAP[word]
                _logger.info(
                    "  🔗 Equivalency [word match on '%s']: '%s' → '%s'",
                    word, attribute_lower, canonical
                )
                return canonical

        # ── Priority 3: Substring match ───────────────────────────────────────
        # Handles 'brilliant white base' where key='brilliant white'
        for key, canonical in self._ATTRIBUTE_EQUIVALENCY_MAP.items():
            if key in attribute_lower:
                _logger.info(
                    "  🔗 Equivalency [substring match on '%s']: '%s' → '%s'",
                    key, attribute_lower, canonical
                )
                return canonical

        # ── No match ──────────────────────────────────────────────────────────
        _logger.debug(
            "  ℹ️ No equivalency group for '%s' — returning as-is",
            attribute_lower
        )
        return attribute_lower

    # ============================================
    # HELPER METHODS
    # ============================================
    def _extract_raw_attribute_name(self, product):
        """
        Extract the raw attribute string from a product's display name WITHOUT
        applying normalization. Used only for debug logging so we can see what
        was extracted before the equivalency map was consulted.

        Args:
            product (product.product): Product record

        Returns:
            str: Raw extracted attribute string (lowercase) or 'unknown'
        """
        display_name = product.display_name.lower()

        if '(' in display_name and '/' in display_name:
            start = display_name.find('(') + 1
            end = display_name.find('/', start)
            return display_name[start:end].strip()

        if '(' in display_name and ')' in display_name:
            start = display_name.find('(') + 1
            end = display_name.find(')')
            return display_name[start:end].strip()

        return display_name

    def _extract_attribute_name(self, product):
        """
        Extract the attribute from a product's display name and resolve it
        to a canonical equivalency group via _normalize_attribute_name().

        This is the primary method used for attribute comparison throughout
        the wizard. All calls to compare attributes use this method, so
        normalization is guaranteed to be applied consistently.

        Extraction logic:
            1. If display name contains '(' and '/':
               → Extract text between '(' and first '/'
               Example: "4ltr Crown Silk Vinyl (Deep Base/W2/B2)"
                         → raw = "deep base"
            2. If display name contains '(' and ')' but no '/':
               → Extract text between '(' and ')'
               Example: "4ltr Crown Brilliant White (White)"
                         → raw = "white"
            3. Fallback: pass full lowercase display name to normalizer
               → Handles products with no brackets at all
               Example: "4ltr Plascon Brilliant White 4L"
                         → raw = full name → normalizer checks for keywords

        After extraction, raw attribute is passed to _normalize_attribute_name()
        which maps it to its canonical group or returns it unchanged.

        Args:
            product (product.product): Product record to extract from

        Returns:
            str: Canonical attribute name (group name or raw attribute)

        Examples:
            "4ltr Crown Silk (Deep Base/W2/B2)"     → 'deep_base_group'
            "4ltr Crown Silk (Pastel Base/B1/W0)"   → 'pastel_white_group'
            "4ltr Gamma Brilliant White"             → 'pastel_white_group'
            "4ltr Crown Silk (Accent Base)"         → 'accent_base_group'
        """
        display_name = product.display_name.lower()
        _logger.debug(
            "    _extract_attribute_name: processing '%s'",
            product.display_name
        )

        # ── Pattern 1: (Attribute/VariantCode) ───────────────────────────────
        if '(' in display_name and '/' in display_name:
            start = display_name.find('(') + 1
            end = display_name.find('/', start)
            raw_attribute = display_name[start:end].strip()
            _logger.debug(
                "      Pattern 1 match: raw = '%s'", raw_attribute
            )
            return self._normalize_attribute_name(raw_attribute)

        # ── Pattern 2: (Attribute) — no variant code ─────────────────────────
        if '(' in display_name and ')' in display_name:
            start = display_name.find('(') + 1
            end = display_name.find(')')
            raw_attribute = display_name[start:end].strip()
            _logger.debug(
                "      Pattern 2 match: raw = '%s'", raw_attribute
            )
            return self._normalize_attribute_name(raw_attribute)

        # ── Pattern 3: No brackets — pass full name to normalizer ─────────────
        _logger.debug(
            "      No brackets found — passing full name to normalizer"
        )
        return self._normalize_attribute_name(display_name)

    # ============================================
    # VOLUME SCALING COMPUTE METHODS
    # ============================================
    @api.depends('source_uom_id')
    def _compute_source_volume(self):
        """
        Convert source UOM to its equivalent volume in litres.

        Uses Odoo's UOM conversion API (_compute_quantity) with the
        standard litre reference UOM as the target.

        Example:
            source_uom_id = '4L' UOM → source_volume_litres = 4.0

        Sets source_volume_litres = 0.0 if conversion fails.
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: _compute_source_volume — %d wizard(s)", len(self))
        _logger.info("=" * 80)

        for wizard in self:
            w_ref = f"Wizard ID {wizard.id}" if wizard.id else "New Wizard"

            if wizard.source_uom_id:
                try:
                    reference_uom = self.env.ref('uom.product_uom_litre')
                    volume = wizard.source_uom_id._compute_quantity(
                        1.0, reference_uom, round=False
                    )
                    wizard.source_volume_litres = volume
                    _logger.info(
                        "  [%s] ✅ %s → %.4f litres",
                        w_ref, wizard.source_uom_id.name, volume
                    )
                except Exception as e:
                    _logger.error(
                        "  [%s] ❌ UOM conversion error: %s | defaulting to 0.0",
                        w_ref, str(e)
                    )
                    wizard.source_volume_litres = 0.0
            else:
                wizard.source_volume_litres = 0.0
                _logger.debug("  [%s] No source UOM → volume = 0.0", w_ref)

        _logger.info("✅ _compute_source_volume complete")
        _logger.info("=" * 80)

    @api.depends('target_volume_litres')
    def _compute_target_uom(self):
        """
        Find the UOM record that best matches the target volume.

        Search strategy:
            Try common naming patterns in order:
                "{N}L", "{N}ltr", "{N} Litres", "{N} litres", "{N}LTR"
            First match wins.
            If no match: fallback to the standard litre reference UOM.

        Example:
            target_volume_litres = 20.0
            Tries: "20L" → found! → target_uom_id = UOM record for "20L"
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: _compute_target_uom — %d wizard(s)", len(self))
        _logger.info("=" * 80)

        for wizard in self:
            w_ref = f"Wizard ID {wizard.id}" if wizard.id else "New Wizard"

            if wizard.target_volume_litres > 0:
                volume_int = int(wizard.target_volume_litres)
                search_terms = [
                    f"{volume_int}L",
                    f"{volume_int}ltr",
                    f"{volume_int} Litres",
                    f"{volume_int} litres",
                    f"{volume_int}LTR",
                ]
                _logger.info(
                    "  [%s] Searching for UOM matching %.2fL | terms: %s",
                    w_ref, wizard.target_volume_litres, search_terms
                )

                found = False
                for term in search_terms:
                    uom = self.env['uom.uom'].search(
                        [('name', 'ilike', term)], limit=1
                    )
                    if uom:
                        wizard.target_uom_id = uom
                        _logger.info(
                            "  [%s] ✅ Found UOM: '%s' (ID: %s) via term '%s'",
                            w_ref, uom.name, uom.id, term
                        )
                        found = True
                        break

                if not found:
                    wizard.target_uom_id = self.env.ref('uom.product_uom_litre')
                    _logger.warning(
                        "  [%s] ⚠️ No UOM found for %.2fL — "
                        "falling back to standard Litres UOM",
                        w_ref, wizard.target_volume_litres
                    )
            else:
                wizard.target_uom_id = False
                _logger.debug(
                    "  [%s] target_volume_litres = 0 → no target UOM", w_ref
                )

        _logger.info("✅ _compute_target_uom complete")
        _logger.info("=" * 80)

    @api.depends('source_volume_litres', 'target_volume_litres')
    def _compute_scale_factor(self):
        """
        Calculate the scaling multiplier between source and target volumes.

        Formula: Scale Factor = Target Volume ÷ Source Volume

        Examples:
            4L → 20L : 20 ÷ 4  = 5.000000× (upscaling)
            20L → 4L : 4 ÷ 20  = 0.200000× (downscaling)
            4L → 4L  : 4 ÷ 4   = 1.000000× (no change)

        Sets scale_factor = 1.0 if either volume is 0 (safe default).
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: _compute_scale_factor — %d wizard(s)", len(self))
        _logger.info("=" * 80)

        for wizard in self:
            w_ref = f"Wizard ID {wizard.id}" if wizard.id else "New Wizard"

            if wizard.source_volume_litres > 0 and wizard.target_volume_litres > 0:
                wizard.scale_factor = (
                    wizard.target_volume_litres / wizard.source_volume_litres
                )
                direction = (
                    "🔼 UPSCALING" if wizard.scale_factor > 1 else
                    "🔽 DOWNSCALING" if wizard.scale_factor < 1 else
                    "➡️ NO CHANGE"
                )
                _logger.info(
                    "  [%s] %.2fL → %.2fL | factor=%.6f× | %s",
                    w_ref,
                    wizard.source_volume_litres,
                    wizard.target_volume_litres,
                    wizard.scale_factor,
                    direction
                )
            else:
                wizard.scale_factor = 1.0
                _logger.debug(
                    "  [%s] Invalid volumes (src=%.2f, tgt=%.2f) → "
                    "scale_factor=1.0 (no scaling)",
                    w_ref,
                    wizard.source_volume_litres,
                    wizard.target_volume_litres
                )

        _logger.info("✅ _compute_scale_factor complete")
        _logger.info("=" * 80)

    @api.depends('colorant_shots_json', 'source_volume_litres')
    def _compute_shots_per_litre(self):
        """
        Calculate the total colorant shot rate per litre of the formula.

        Formula: Shots per Litre = Total Shots in Formula ÷ Source Volume

        Informational only — displayed in the wizard so users understand
        how dense the formula is before deciding on a target volume.

        Example:
            Source: 4L tin | C1=10 shots, C3=5 shots
            Total shots = 15 | Rate = 15 ÷ 4 = 3.75 shots/litre
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: _compute_shots_per_litre — %d wizard(s)", len(self))
        _logger.info("=" * 80)

        for wizard in self:
            w_ref = f"Wizard ID {wizard.id}" if wizard.id else "New Wizard"

            try:
                colorant_shots = json.loads(wizard.colorant_shots_json or '{}')
                total_shots = sum(
                    data['shots'] for data in colorant_shots.values()
                )

                if wizard.source_volume_litres > 0 and total_shots > 0:
                    wizard.shots_per_litre = (
                        total_shots / wizard.source_volume_litres
                    )
                    _logger.info(
                        "  [%s] Total shots: %.2f | Volume: %.2fL | "
                        "Rate: %.6f shots/litre",
                        w_ref, total_shots,
                        wizard.source_volume_litres,
                        wizard.shots_per_litre
                    )
                else:
                    wizard.shots_per_litre = 0.0
                    _logger.debug(
                        "  [%s] shots=%.2f or volume=%.2f is 0 → rate=0",
                        w_ref, total_shots, wizard.source_volume_litres
                    )

            except Exception as e:
                _logger.error(
                    "  [%s] ❌ Error computing shots_per_litre: %s", w_ref, str(e)
                )
                wizard.shots_per_litre = 0.0

        _logger.info("✅ _compute_shots_per_litre complete")
        _logger.info("=" * 80)

    @api.depends('colorant_shots_json', 'scale_factor')
    def _compute_scaled_shots(self):
        """
        Multiply each colorant's shots by scale_factor and store as JSON.

        Formula: Scaled Shots = Original Shots × Scale Factor

        The result is stored in scaled_colorant_shots_json and consumed by:
            - _populate_comparison_lines() (when scaling is active)
            - action_use_this_product() (to update parent wizard lines)

        Example (4L → 20L, scale=5×):
            Original: {C1: {shots: 10, unit_cost: 500.0}}
            Scaled:   {C1: {shots: 50, unit_cost: 500.0}}

        Sets scaled_colorant_shots_json = '{}' on any parse/compute error.
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: _compute_scaled_shots — %d wizard(s)", len(self))
        _logger.info("=" * 80)

        for wizard in self:
            w_ref = f"Wizard ID {wizard.id}" if wizard.id else "New Wizard"

            try:
                original_shots = json.loads(wizard.colorant_shots_json or '{}')
                scaled_shots = {}

                _logger.info(
                    "  [%s] scale_factor=%.6f× | %d colorant(s) to scale",
                    w_ref, wizard.scale_factor, len(original_shots)
                )

                for code, data in original_shots.items():
                    original_val = data['shots']
                    scaled_val = original_val * wizard.scale_factor
                    scaled_shots[code] = {
                        'shots': scaled_val,
                        'unit_cost_excl_vat': data['unit_cost_excl_vat']
                    }
                    _logger.debug(
                        "    %s: %.2f → %.2f shots (×%.4f)",
                        code, original_val, scaled_val, wizard.scale_factor
                    )

                wizard.scaled_colorant_shots_json = json.dumps(scaled_shots)
                _logger.info(
                    "  [%s] ✅ Scaled %d colorant(s)", w_ref, len(scaled_shots)
                )

            except json.JSONDecodeError as e:
                _logger.error(
                    "  [%s] ❌ JSON decode error in _compute_scaled_shots: %s",
                    w_ref, str(e)
                )
                wizard.scaled_colorant_shots_json = '{}'
            except Exception as e:
                _logger.error(
                    "  [%s] ❌ Error scaling shots: %s", w_ref, str(e)
                )
                wizard.scaled_colorant_shots_json = '{}'

        _logger.info("✅ _compute_scaled_shots complete")
        _logger.info("=" * 80)

    # ============================================
    # REFRESH ACTION
    # ============================================
    def action_refresh_comparison(self):
        """
        Delete existing comparison lines and repopulate with current settings.

        Triggered by the "Refresh Products" button after the user changes
        target_volume_litres or toggles show_scaled_products.

        Process:
            1. Delete all current comparison lines
            2. Call _populate_comparison_lines() with updated UOM / shots
            3. Reopen the wizard to display new results

        Returns:
            dict: ir.actions.act_window to reopen this wizard.
                  Includes notification context for success/warning display.
        """
        self.ensure_one()

        _logger.info("=" * 80)
        _logger.info("🔄 ACTION: action_refresh_comparison — Wizard ID: %s", self.id)
        _logger.info("=" * 80)
        _logger.info(
            "  Current lines: %d | Scaling: %s | Target: %.2fL",
            len(self.comparison_line_ids),
            self.show_scaled_products,
            self.target_volume_litres
        )

        # Delete existing lines
        line_count = len(self.comparison_line_ids)
        self.comparison_line_ids.unlink()
        _logger.info("  ✅ Deleted %d existing line(s)", line_count)

        # Repopulate
        _logger.info("  Repopulating with current settings...")
        if self.show_scaled_products:
            _logger.info(
                "    Target UOM: %s | Scale factor: %.4f×",
                self.target_uom_id.name if self.target_uom_id else 'None',
                self.scale_factor
            )

        self._populate_comparison_lines()

        new_count = len(self.comparison_line_ids)
        _logger.info(
            "✅ action_refresh_comparison complete: %d line(s) created", new_count
        )
        _logger.info("=" * 80)

        if new_count == 0:
            _logger.warning(
                "  ⚠️ No products found for target UOM: %s",
                self.target_uom_id.name if self.target_uom_id else 'None'
            )
            return {
                'type': 'ir.actions.act_window',
                'name': 'Cost Comparison & Volume Scaling',
                'res_model': 'cost.comparison.wizard',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
                'context': dict(
                    self.env.context,
                    default_show_notification=True,
                    notification_type='warning',
                    notification_title='No Products Found',
                    notification_message=(
                        f"No products found for "
                        f"{self.target_uom_id.name if self.target_uom_id else 'target UOM'} "
                        f"in '{self.base_category_id.name}' with attribute "
                        f"'{self.base_attribute_name}'."
                    )
                )
            }

        _logger.info(
            "  🎉 Reopening wizard with %d product(s)", new_count
        )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cost Comparison & Volume Scaling',
            'res_model': 'cost.comparison.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(
                self.env.context,
                default_show_notification=True,
                notification_type='success',
                notification_title='Products Refreshed',
                notification_message=(
                    f"Found {new_count} product(s) for comparison."
                )
            )
        }

    # ============================================
    # STATISTICS COMPUTE
    # ============================================
    @api.depends(
        'comparison_line_ids.total_cost_incl_vat',
        'comparison_line_ids.profit_amount_incl_vat'
    )
    def _compute_statistics(self):
        """
        Compute summary statistics across all comparison lines.

        Statistics:
            total_products : count of lines
            avg_cost       : mean of total_cost_incl_vat
            lowest_cost    : minimum total_cost_incl_vat
                             (used in list view decoration-success)
            highest_profit : maximum profit_amount_incl_vat

        All values set to 0 if no lines exist.
        """
        _logger.info("=" * 80)
        _logger.info("🔄 COMPUTE: _compute_statistics — %d wizard(s)", len(self))
        _logger.info("=" * 80)

        for wizard in self:
            w_ref = f"Wizard ID {wizard.id}" if wizard.id else "New Wizard"
            lines = wizard.comparison_line_ids

            if lines:
                costs = lines.mapped('total_cost_incl_vat')
                profits = lines.mapped('profit_amount_incl_vat')

                wizard.total_products = len(lines)
                wizard.avg_cost = sum(costs) / len(costs)
                wizard.lowest_cost = min(costs)
                wizard.highest_profit = max(profits)

                _logger.info(
                    "  [%s] Products: %d | Avg cost: %.2f KES | "
                    "Lowest: %.2f KES | Best profit: %.2f KES",
                    w_ref,
                    wizard.total_products,
                    wizard.avg_cost,
                    wizard.lowest_cost,
                    wizard.highest_profit
                )
            else:
                wizard.total_products = 0
                wizard.avg_cost = 0.0
                wizard.lowest_cost = 0.0
                wizard.highest_profit = 0.0
                _logger.warning(
                    "  [%s] ⚠️ No comparison lines — all statistics = 0", w_ref
                )

        _logger.info("✅ _compute_statistics complete")
        _logger.info("=" * 80)

    # ============================================
    # QUOTATION GENERATOR ACTION
    # ============================================
    def action_open_quotation_generator(self):
        """
        Open the quotation generator wizard, passing current comparison data.

        Passes the following via context to quotation.generator.wizard:
            - source_wizard_id   : this comparison wizard's ID
            - colour_code_id     : from parent tint wizard
            - fandeck_id         : from parent tint wizard
            - base_category_id   : current comparison category
            - colorant_shots_json: current formula snapshot

        Returns:
            dict: ir.actions.act_window to open quotation.generator.wizard
        """
        self.ensure_one()

        _logger.info("=" * 80)
        _logger.info("📝 ACTION: action_open_quotation_generator")
        _logger.info("=" * 80)
        _logger.info("  Comparison Wizard ID:   %s", self.id)
        _logger.info("  Comparison lines:       %d", len(self.comparison_line_ids))
        _logger.info(
            "  Colour Code:            %s",
            self.parent_wizard_id.colour_code_id.name
            if self.parent_wizard_id.colour_code_id else 'None'
        )
        _logger.info(
            "  Fandeck:                %s",
            self.parent_wizard_id.fandeck_id.name
            if self.parent_wizard_id.fandeck_id else 'None'
        )
        _logger.info("  Category:               %s", self.base_category_id.name)
        _logger.info("=" * 80)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate Quotation',
            'res_model': 'quotation.generator.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_source_wizard_id': self.id,
                'default_colour_code_id': self.parent_wizard_id.colour_code_id.id,
                'default_fandeck_id': self.parent_wizard_id.fandeck_id.id,
                'default_base_category_id': self.base_category_id.id,
                'default_colorant_shots_json': self.colorant_shots_json,
            }
        }