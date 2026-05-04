# -*- coding: utf-8 -*-
from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    net_price = fields.Float(
        string="Net Price (Landed)",
        compute='_compute_net_price',
        store=True,
        readonly=True
    )

    applied_discount = fields.Float(
        string="Applied Discount %",
        compute='_compute_applied_discount',
        store=True
    )

    applied_freight = fields.Float(
        string="Applied Freight %",
        compute='_compute_applied_freight',
        store=True
    )

    pricing_rule_id = fields.Many2one(
        'product.vendor.pricing',
        string='Pricing Rule',
        compute='_compute_pricing_rule',
        store=True
    )

    use_custom_pricing = fields.Boolean(
        related='product_id.use_custom_vendor_pricing',
        string='Custom Pricing',
        store=True
    )

    @api.depends('product_id', 'product_id.use_custom_vendor_pricing',
                 'order_id.partner_id', 'product_qty')
    def _compute_pricing_rule(self):
        """Find the applicable pricing rule based on product, vendor, and quantity"""
        for line in self:
            # Only look for pricing rules if product has custom pricing enabled
            if not line.product_id or not line.product_id.use_custom_vendor_pricing:
                line.pricing_rule_id = False
                continue

            if not line.order_id.partner_id:
                line.pricing_rule_id = False
                continue

            # Search for applicable pricing rules
            domain = [
                ('partner_id', '=', line.order_id.partner_id.id),
                ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                ('active', '=', True),
                ('min_qty', '<=', line.product_qty),
                '|',
                ('max_qty', '=', 0),
                ('max_qty', '>=', line.product_qty),
            ]

            # Prefer rules with specific product variant
            pricing_rules = self.env['product.vendor.pricing'].search(
                domain + [('product_id', '=', line.product_id.id)],
                order='min_qty desc',
                limit=1
            )

            # Fall back to template-level rules
            if not pricing_rules:
                pricing_rules = self.env['product.vendor.pricing'].search(
                    domain + [('product_id', '=', False)],
                    order='min_qty desc',
                    limit=1
                )

            line.pricing_rule_id = pricing_rules[:1] if pricing_rules else False

    @api.depends('product_id', 'order_id.partner_id', 'pricing_rule_id', 'discount')
    def _compute_applied_discount(self):
        """Calculate the discount to apply, triggered on product or partner change"""
        for line in self:
            if not line.product_id or not line.order_id.partner_id:
                line.applied_discount = 0.0
                continue

            # Priority: line discount > pricing rule > vendor default
            if line.discount:
                line.applied_discount = line.discount
            elif line.pricing_rule_id and line.pricing_rule_id.discount_percentage:
                line.applied_discount = line.pricing_rule_id.discount_percentage
            elif line.order_id.partner_id:
                line.applied_discount = line.order_id.partner_id.discount_percentage or 0.0
            else:
                line.applied_discount = 0.0

    @api.depends('product_id', 'order_id.partner_id', 'pricing_rule_id')
    def _compute_applied_freight(self):
        """Calculate the freight to apply, triggered on product or partner change"""
        for line in self:
            if not line.product_id or not line.order_id.partner_id:
                line.applied_freight = 0.0
                continue

            # Priority: pricing rule > vendor default
            if line.pricing_rule_id and line.pricing_rule_id.freight_percentage:
                line.applied_freight = line.pricing_rule_id.freight_percentage
            elif line.order_id.partner_id:
                line.applied_freight = line.order_id.partner_id.freight_percentage or 0.0
            else:
                line.applied_freight = 0.0

    @api.depends('price_unit', 'applied_discount', 'applied_freight', 'taxes_id',
                 'order_id.currency_id', 'product_id', 'order_id.partner_id',
                 'product_qty')
    def _compute_net_price(self):
        """
        Calculate the net landed price per unit, excluding tax
        """
        for line in self:
            if not line.order_id or not line.product_id:
                line.net_price = line.price_unit
                continue

            _logger.info(f"=== Computing Net Price for {line.product_id.name} ===")
            _logger.info(f"Price Unit: {line.price_unit}")
            _logger.info(f"Applied Discount: {line.applied_discount}%")
            _logger.info(f"Applied Freight: {line.applied_freight}%")

            # Step 1: Apply discount
            discounted_price = line.price_unit * (1 - (line.applied_discount / 100.0))

            # Step 2: Add freight (calculated on discounted price)
            freight_amount = discounted_price * (line.applied_freight / 100.0)

            # Step 3: Subtotal (landed cost excluding tax)
            line.net_price = discounted_price + freight_amount

            _logger.info(f"Discounted Price: {discounted_price}")
            _logger.info(f"Freight Amount: {freight_amount}")
            _logger.info(f"Net Price (excluding tax): {line.net_price}")

    @api.depends('product_qty', 'net_price', 'taxes_id')
    def _compute_amount(self):
        """
        Override to calculate line totals using net_price as the base (excluding tax),
        then apply taxes separately
        """
        for line in self:
            if not line.order_id or not line.product_id:
                super(PurchaseOrderLine, line)._compute_amount()
                continue

            # Use net_price as the base price per unit (excluding tax)
            base_price = line.net_price

            # Calculate taxes and totals based on net_price * quantity
            if line.taxes_id:
                taxes_res = line.taxes_id.compute_all(
                    base_price,
                    currency=line.order_id.currency_id,
                    quantity=line.product_qty,
                    product=line.product_id,
                    partner=line.order_id.partner_id,
                )
                line.price_subtotal = taxes_res['total_excluded']
                line.price_tax = sum(t.get('amount', 0.0) for t in taxes_res.get('taxes', []))
                line.price_total = taxes_res['total_included']
            else:
                line.price_subtotal = base_price * line.product_qty
                line.price_tax = 0.0
                line.price_total = line.price_subtotal

    @api.onchange('product_id', 'product_qty', 'order_id.partner_id')
    def _onchange_product_pricing(self):
        """Auto-apply pricing rule and populate discount/freight when product or quantity changes"""
        for line in self:
            if not line.product_id or not line.order_id.partner_id:
                continue

            # Trigger pricing rule computation
            line._compute_pricing_rule()

            # Populate applied_discount and applied_freight
            line._compute_applied_discount()
            line._compute_applied_freight()

            # If there's a pricing rule with a price, use it
            if line.pricing_rule_id and line.pricing_rule_id.price_unit > 0:
                line.price_unit = line.pricing_rule_id.price_unit

            # Recalculate net_price to reflect new discount and freight
            line._compute_net_price()

    def _prepare_invoice_line(self, **optional_values):
        """
        Override to use net_price for custom pricing products
        This ensures bills created from PO use the correct landed cost
        """
        res = super(PurchaseOrderLine, self)._prepare_invoice_line(**optional_values)

        # If custom pricing is enabled, use net_price instead of price_unit
        if self.use_custom_pricing and self.net_price:
            _logger.info(f"=== Preparing Invoice Line with Custom Pricing ===")
            _logger.info(f"Product: {self.product_id.name}")
            _logger.info(f"Original price_unit: {res.get('price_unit')}")
            _logger.info(f"Net Price (Landed): {self.net_price}")

            # Store additional info
            res['net_price'] = self.net_price
            res['use_custom_pricing'] = True
            res['applied_discount'] = self.applied_discount
            res['applied_freight'] = self.applied_freight

            # CRITICAL: Replace price_unit with net_price
            res['price_unit'] = self.net_price

            _logger.info(f"Invoice line price_unit set to: {res['price_unit']}")
        else:
            res['net_price'] = self.net_price
            res['use_custom_pricing'] = False

        return res