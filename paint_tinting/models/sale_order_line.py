# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare
import json
import logging


_logger = logging.getLogger(__name__)
_logger.info("=== DIAGNOSTIC: sale_order.py LOADED SUCCESSFULLY ===")


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pending_tinted_line_count = fields.Integer(
        string="Pending Tinted Lines",
        compute='_compute_pending_tinted_lines',
        store=False,
    )

    has_pending_tinted_lines = fields.Boolean(
        string="Has Pending Tinted Lines",
        compute='_compute_pending_tinted_lines',
        store=False,
    )

    # Kept so that any database-stored inherited view that still references
    # this name does not fail view validation during an upgrade cycle.
    has_exactly_one_tinted_line = fields.Boolean(
        compute='_compute_pending_tinted_lines',
        store=False,
    )

    @api.depends('order_line.is_tinted_product_line', 'order_line.tinted_product_created')
    def _compute_pending_tinted_lines(self):
        for order in self:
            pending = order.order_line.filtered(
                lambda l: l.is_tinted_product_line and not l.tinted_product_created
            )
            order.pending_tinted_line_count = len(pending)
            order.has_pending_tinted_lines = bool(pending)
            order.has_exactly_one_tinted_line = bool(pending)

    def action_create_tinted_product_from_line(self):
        """Process the next pending tinted line. Delegates to the line-level method."""
        self.ensure_one()
        pending = self.order_line.filtered(
            lambda l: l.is_tinted_product_line and not l.tinted_product_created
        )
        if not pending:
            raise UserError(_("All tinted product lines have already been processed."))
        return pending[0].action_create_tinted_product_for_line()

    def _is_profit_guard_discount_line(self, line):
        discount_product = line.company_id.sale_discount_product_id
        if discount_product and line.product_id == discount_product:
            return True
        return (
            line.price_unit < 0
            and line.product_uom_qty >= 0
            and (line.product_id.standard_price or 0.0) == 0.0
        )

    def _get_line_unit_price_and_cost_vat_incl(self, line):
        product = line.product_id
        cost_excl = product.standard_price or 0.0

        if product.uom_id and line.product_uom and product.uom_id != line.product_uom:
            cost_excl = product.uom_id._compute_price(cost_excl, line.product_uom)

        company_currency = product.company_id.currency_id or line.order_id.company_id.currency_id
        if company_currency and company_currency != line.currency_id:
            cost_excl = company_currency._convert(
                cost_excl,
                line.currency_id,
                line.order_id.company_id,
                line.order_id.date_order or fields.Date.context_today(line),
            )

        price_excl = line.price_unit * (1.0 - (line.discount or 0.0) / 100.0)
        if line.tax_id:
            price_incl = line.tax_id.compute_all(
                price_excl,
                currency=line.currency_id,
                quantity=1.0,
                product=product,
                partner=line.order_id.partner_shipping_id or line.order_id.partner_id,
            )['total_included']
            cost_incl = line.tax_id.compute_all(
                cost_excl,
                currency=line.currency_id,
                quantity=1.0,
                product=product,
                partner=line.order_id.partner_shipping_id or line.order_id.partner_id,
                handle_price_include=False,
            )['total_included']
        else:
            price_incl = price_excl
            cost_incl = cost_excl

        return price_incl, cost_incl

    def _get_discount_profit_guard_values(self):
        self.ensure_one()
        total_profit = 0.0
        discount_amount = 0.0

        for line in self.order_line:
            if line.display_type or not line.product_id:
                continue

            price_incl, cost_incl = self._get_line_unit_price_and_cost_vat_incl(line)
            qty = line.product_uom_qty or 0.0

            if self._is_profit_guard_discount_line(line):
                discount_amount += abs(price_incl * qty)
                continue

            if qty <= 0 or cost_incl <= 0:
                continue

            total_profit += (price_incl - cost_incl) * qty

        return {
            'total_profit': total_profit,
            'discount_amount': discount_amount,
        }

    def _get_below_cost_lines_vat_incl(self):
        self.ensure_one()
        offenders = []
        precision = self.currency_id.rounding or 0.01

        for line in self.order_line:
            if line.display_type or not line.product_id or line.product_uom_qty <= 0:
                continue

            product = line.product_id
            if self._is_profit_guard_discount_line(line) or (product.standard_price or 0.0) <= 0:
                continue

            price_incl, cost_incl = self._get_line_unit_price_and_cost_vat_incl(line)

            if float_compare(price_incl, cost_incl, precision_rounding=precision) < 0:
                offenders.append({
                    'product_name': product.display_name,
                    'price_incl': round(price_incl, 2),
                    'cost_incl': round(cost_incl, 2),
                })

        return offenders

    def action_confirm(self):
        for order in self:
            discount_guard = order._get_discount_profit_guard_values()
            if (
                discount_guard['discount_amount'] > 0
                and float_compare(
                    discount_guard['total_profit'],
                    discount_guard['discount_amount'],
                    precision_rounding=order.currency_id.rounding or 0.01,
                ) < 0
            ):
                raise UserError(_(
                    "You cannot confirm this sales order because the discount amount "
                    "is greater than the order total profit (VAT inclusive).\n\n"
                    "Discount Amount: %.2f\n"
                    "Order Total Profit: %.2f"
                ) % (
                    round(discount_guard['discount_amount'], 2),
                    round(discount_guard['total_profit'], 2),
                ))

            below_cost_lines = order._get_below_cost_lines_vat_incl()
            if below_cost_lines:
                detail_lines = [
                    "%s: selling %.2f < cost %.2f"
                    % (item['product_name'], item['price_incl'], item['cost_incl'])
                    for item in below_cost_lines
                ]
                raise UserError(_(
                    "You cannot confirm this sales order because these products "
                    "are below cost price (VAT inclusive):\n%s"
                ) % "\n".join(detail_lines))

            pending = order.order_line.filtered(
                lambda l: l.is_tinted_product_line and not l.tinted_product_created
            )
            if pending:
                products = ', '.join(
                    pending.mapped(lambda l: l.product_id.display_name or l.name)
                )
                raise UserError(_(
                    "You cannot confirm this sales order while tinted product lines "
                    "are still pending manufacture.\n\n"
                    "Please manufacture/produce or delete these line(s) first:\n%s"
                ) % products)
        return super().action_confirm()


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

    # ============================================
    # TINTED PRODUCT CREATION TRACKING
    # ============================================
    tinted_product_created = fields.Boolean(
        string='Tinted Product Created',
        default=False,
        copy=False,
        help='Set after tinted product, BOM and MO have been created for this line'
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        try:
            fields_list = super()._load_pos_data_fields(config_id)
        except AttributeError:
            fields_list = []
        for field_name in ['is_tinted_product_line', 'tinted_product_created']:
            if field_name not in fields_list:
                fields_list.append(field_name)
        return fields_list

    # ============================================
    # LINE-LEVEL TINTED PRODUCT CREATION
    # ============================================
    def action_create_tinted_product_for_line(self):
        """
        Create tinted product, BOM and MO for this specific order line.

        Duplication is prevented by two guards:
          1. tinted_product_created flag (already processed)
          2. Existing product.template name check (same name exists)
        """
        self.ensure_one()

        _logger.info("=" * 80)
        _logger.info("🚀 LINE → TINTED PRODUCT CREATION: %s", self.product_id.display_name)
        _logger.info("   Order: %s | Line ID: %s", self.order_id.name, self.id)
        _logger.info("=" * 80)

        # ── DUPLICATION GUARDS ────────────────────────────────────────────
        if self.tinted_product_created:
            raise UserError(_(
                "Tinted product already created for this line.\n"
                "Product: %s\n\n"
                "Each line can only be processed once to avoid duplicates."
            ) % self.product_id.display_name)

        if not self.is_tinted_product_line:
            raise UserError(_("This order line is not a tinted product line."))

        line = self
        original_selling_price = line.price_unit
        _logger.info("  💰 Original selling price: %.2f KES", original_selling_price)

        # ── STEP 1: METADATA VALIDATION ───────────────────────────────────
        required = {
            'base_product_id': 'Base Product',
            'base_product_uom_id': 'Base Product UOM',
            'tinting_formula_json': 'Tinting Formula',
            'colour_code_id': 'Colour Code',
            'fandeck_id': 'Fandeck',
            'base_category_id': 'Base Category',
        }
        missing = [label for field, label in required.items() if not getattr(line, field, None)]
        if missing:
            raise UserError(_("Missing tinting metadata on order line: %s") % ', '.join(missing))
        _logger.info("  ✅ All metadata present")

        # ── STEP 2: PARSE FORMULA ──────────────────────────────────────────
        try:
            formula_shots = json.loads(line.tinting_formula_json or '{}')
            if not formula_shots:
                raise ValueError("Empty formula — no colorant shots found")
            _logger.info("  ✅ Formula parsed: %d colorant(s)", len(formula_shots))
        except json.JSONDecodeError as e:
            raise UserError(_("Invalid tinting formula JSON: %s") % str(e))

        # ── STEP 3: PRODUCT NAME & DUPLICATE CHECK ─────────────────────────
        clean_name = line._get_tinted_product_name_from_sale()
        _logger.info("  Product name: '%s'", clean_name)

        existing = self.env['product.template'].search(
            [('name', '=', clean_name), ('is_tinted_product', '=', True)], limit=1
        )
        if existing:
            latest_mo = self.env['mrp.production'].search(
                [('product_id.product_tmpl_id', '=', existing.id)],
                order='id desc', limit=1
            )
            exists_wiz = self.env['tint.product.exists.wizard'].create({
                'product_name': clean_name,
                'product_tmpl_id': existing.id,
                'mo_id': latest_mo.id if latest_mo else False,
                'source_sale_order_id': self.order_id.id,
                'source_sale_order_line_id': self.id,
            })
            return {
                'type': 'ir.actions.act_window',
                'name': _('Product Already Exists'),
                'res_model': 'tint.product.exists.wizard',
                'res_id': exists_wiz.id,
                'view_mode': 'form',
                'target': 'new',
            }

        uom = line.base_product_uom_id

        if hasattr(uom.category_id, 'is_pos_groupable') and not uom.category_id.is_pos_groupable:
            uom.category_id.write({'is_pos_groupable': True})
            _logger.info("  ✅ Marked UoM category %s as POS-groupable", uom.category_id.name)

        # ── STEP 4: CATEGORY ──────────────────────────────────────────────
        categ = self.env['product.category'].search([('name', '=', 'Tinted Paint')], limit=1)
        if not categ:
            categ = self.env['product.category'].create({
                'name': 'Tinted Paint',
                'property_cost_method': 'fifo',
                'property_valuation': 'real_time',
            })
        _logger.info("  ✅ Category: %s (ID: %s)", categ.name, categ.id)

        # ── STEP 5: COST CALCULATIONS ──────────────────────────────────────
        total_cost_excl_vat = line.quoted_cost_at_creation / 1.16
        profit = line.price_unit - line.quoted_cost_at_creation
        margin = (profit / line.price_unit * 100) if line.price_unit > 0 else 0
        _logger.info("  Cost excl VAT: %.2f | Profit: %.2f | Margin: %.2f%%",
                     total_cost_excl_vat, profit, margin)

        # ── STEP 6: PRODUCT CREATION (type fallback chain) ────────────────
        base_type = getattr(line.base_product_id, 'type', 'consu')
        product_vals = {
            'name': clean_name,
            'base_product_name': clean_name,
            'categ_id': categ.id,
            'uom_id': uom.id,
            'uom_po_id': uom.id,
            'standard_price': total_cost_excl_vat,
            'list_price': line.price_unit,
            'is_tinted_product': True,
            'fandeck_id': line.fandeck_id.id,
            'colour_code_id': line.colour_code_id.id,
            'sale_ok': True,
            'purchase_ok': True,
            'tracking': 'lot',
            'description': (
                f"Tinted paint: {line.base_product_id.display_name} "
                f"with {line.colour_code_id.code}"
            ),
            'default_code': (
                f"TINT-{line.colour_code_id.code}-"
                f"{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
            ),
        }

        tmpl = None
        for type_val in ['product', 'stockable', base_type, None]:
            try:
                if type_val is not None:
                    product_vals['type'] = type_val
                elif 'type' in product_vals:
                    del product_vals['type']
                tmpl = self.env['product.template'].with_context(skip_auto_name=True).create(
                    product_vals
                )
                _logger.info("  ✅ Product template created (type=%s) ID: %s", type_val, tmpl.id)
                break
            except ValueError:
                continue

        if not tmpl or not tmpl.id:
            raise UserError(_("Failed to create tinted product template."))

        # Ensure storable type
        if getattr(tmpl, 'type', None) not in ['product', 'stockable']:
            for t in ['product', 'stockable']:
                try:
                    tmpl.write({'type': t})
                    break
                except Exception:
                    continue

        # Ensure lot tracking
        if getattr(tmpl, 'tracking', None) != 'lot':
            tmpl.write({'tracking': 'lot'})

        # ── STEP 7: ROUTES ────────────────────────────────────────────────
        for route_ref in ['mrp.route_warehouse0_manufacture', 'purchase_stock.route_warehouse0_buy']:
            try:
                route = self.env.ref(route_ref)
                if route:
                    tmpl.write({'route_ids': [(4, route.id)]})
            except Exception:
                pass

        _logger.info(
            "  ✅ Product ready: %s | type=%s | tracking=%s",
            tmpl.name, getattr(tmpl, 'type', 'N/A'), getattr(tmpl, 'tracking', 'N/A')
        )

        # ── STEP 8: BOM CREATION ──────────────────────────────────────────
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
        _logger.info("  ✅ BOM created: ID %s", bom.id)

        # Base product line
        self.env['mrp.bom.line'].create({
            'bom_id': bom.id,
            'product_id': line.base_product_id.id,
            'product_qty': 1.0,
            'product_uom_id': uom.id,
            'unit_cost_excl_vat': line.quoted_base_cost / 1.16,
        })

        # Colorant lines
        colorant_count = 0
        for colorant_code, data in formula_shots.items():
            colorant_product = self.env['product.product'].search([
                ('product_tmpl_id.colorant_code', '=', colorant_code),
                ('product_tmpl_id.is_colorant', '=', True),
            ], limit=1)
            if not colorant_product:
                raise UserError(_("Colorant %s not found in system!") % colorant_code)

            shots = data['shots']
            qty_litres = (shots * 0.616) / 1000.0

            self.env['mrp.bom.line'].create({
                'bom_id': bom.id,
                'product_id': colorant_product.id,
                'product_qty': qty_litres,
                'product_uom_id': colorant_product.uom_id.id,
                'is_colorant_line': True,
                'colorant_shots': shots,
                'unit_cost_excl_vat': data['unit_cost_excl_vat'],
            })
            colorant_count += 1
            _logger.info(
                "    Colorant %s: %.6f L (%.2f shots)", colorant_code, qty_litres, shots
            )

        _logger.info("  ✅ BOM: 1 base + %d colorant line(s)", colorant_count)

        # ── STEP 9: UPDATE PRODUCT COST FROM BOM ──────────────────────────
        tmpl.write({
            'standard_price': bom.total_cost_excl_vat,
            'cost_price_excl_vat': bom.total_cost_excl_vat,
        })

        # ── STEP 10: MANUFACTURING ORDER ──────────────────────────────────
        mo = self.env['mrp.production'].create({
            'product_id': tmpl.product_variant_id.id,
            'bom_id': bom.id,
            'product_qty': 1.0,
            'product_uom_id': uom.id,
            'origin': self.order_id.name,
            'is_tinting_mo': True,
        })
        mo.action_confirm()
        _logger.info("  ✅ MO created & confirmed: %s (ID: %s)", mo.name, mo.id)

        # Exact colorant quantities on stock moves
        for move in mo.move_raw_ids:
            if move.bom_line_id and move.bom_line_id.is_colorant_line:
                exact_qty = move.bom_line_id.product_qty
                move.write({'product_uom_qty': exact_qty, 'quantity': exact_qty})

        # ── STEP 11: UPDATE SALE ORDER LINE ───────────────────────────────
        old_product_name = line.product_id.display_name
        try:
            line_description = (
                f"Colour: {line.colour_code_id.code} - {line.colour_code_id.name}"
            )
            line.write({
                'product_id': tmpl.product_variant_id.id,
                'price_unit': original_selling_price,
                'name': line_description,
            })
        except Exception as e:
            raise UserError(_("Failed to update sale order line: %s") % str(e))

        # Force price if Odoo recomputed it
        if abs(line.price_unit - original_selling_price) > 0.01:
            line.write({'price_unit': original_selling_price})

        # ── STEP 12: MARK LINE AS DONE ────────────────────────────────────
        line.write({'tinted_product_created': True})

        # Chatter note on the sale order
        self.order_id.message_post(
            body=_(
                "<strong>Tinted Product Created</strong><br/>"
                "<ul>"
                "<li>Was: %s</li>"
                "<li>Now: %s</li>"
                "<li>MO: %s</li>"
                "<li>BOM: 1 base + %d colorant(s)</li>"
                "<li>Selling price preserved: %.2f KES</li>"
                "<li>Profit: %.2f KES (%.1f%%)</li>"
                "</ul>"
            ) % (
                old_product_name, tmpl.name, mo.name,
                colorant_count, original_selling_price, profit, margin
            ),
            subject=_("Tinted Product Created: %s") % tmpl.name,
        )

        _logger.info(
            "✅ DONE: %s | MO: %s | Price: %.2f KES | Margin: %.1f%%",
            tmpl.name, mo.name, original_selling_price, margin
        )
        _logger.info("=" * 80)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Manufacturing Order: %s') % mo.name,
            'res_model': 'mrp.production',
            'res_id': mo.id,
            'view_mode': 'form',
            'target': 'current',
        }

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
