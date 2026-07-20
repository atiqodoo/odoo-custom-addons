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

    vendor_promised_cost_vat_incl = fields.Monetary(
        string="Vendor Promised Cost (VAT Incl.)",
        currency_field='currency_id',
        store=True,
        index=True,
        help="VAT-inclusive cost promised by the vendor for this purchase line.",
    )

    volume_reporting_grade_id = fields.Many2one(
        'product.tag',
        string='Grade',
        compute='_compute_lpo_grade_volume_fields',
        store=True,
        readonly=True,
        index=True,
        help='Movement-volume reporting grade mapped from the product tags.',
    )
    volume_reference_uom_id = fields.Many2one(
        'uom.uom',
        string='Volume UoM',
        compute='_compute_lpo_grade_volume_fields',
        store=True,
        readonly=True,
    )
    volume_conversion_ratio = fields.Float(
        string='Volume Ratio',
        compute='_compute_lpo_grade_volume_fields',
        store=True,
        readonly=True,
        digits=(16, 8),
    )
    order_line_grade_volume = fields.Float(
        string='Grade Volume',
        compute='_compute_lpo_grade_volume_fields',
        store=True,
        readonly=True,
        digits='Product Unit of Measure',
        help='Order line quantity converted to the reference UoM used by movement-volume analysis.',
    )
    order_line_grade_volume_label = fields.Char(
        string='Grade Volume',
        compute='_compute_lpo_grade_volume_fields',
        store=True,
        readonly=True,
    )
    order_line_grade_amount_vat_incl = fields.Monetary(
        string='Grade Value (VAT Incl.)',
        compute='_compute_order_line_grade_amount_vat_incl',
        store=True,
        readonly=True,
        currency_field='currency_id',
        help='VAT-inclusive purchase line value used in grade-wise RFQ/LPO comparisons.',
    )

    @api.depends('price_total')
    def _compute_order_line_grade_amount_vat_incl(self):
        for line in self:
            line.order_line_grade_amount_vat_incl = line.price_total or 0.0

    def _get_lpo_volume_reference_uom(self):
        self.ensure_one()
        if not self.product_uom:
            return self.env['uom.uom']
        return self.env['product.movement.volume.builder']._get_category_reference_uom(
            self.product_uom
        )

    def _get_lpo_volume_reporting_grade(self):
        self.ensure_one()
        if not self.product_id:
            return self.env['product.tag']
        grades = self.product_id.all_product_tag_ids.filtered(
            'is_volume_reporting_grade'
        ).sorted(key=lambda tag: (tag.sequence, tag.id))
        if len(grades) > 1:
            _logger.warning(
                "LPO_GRADE_AMBIGUOUS line_id=%s product_id=%s grade_ids=%s; using grade_id=%s",
                self.id,
                self.product_id.id,
                grades.ids,
                grades[0].id,
            )
        return grades[:1]

    @api.depends(
        'product_id',
        'product_id.all_product_tag_ids',
        'product_id.all_product_tag_ids.is_volume_reporting_grade',
        'product_qty',
        'product_uom',
        'display_type',
    )
    def _compute_lpo_grade_volume_fields(self):
        for line in self:
            if line.display_type or not line.product_id or not line.product_uom:
                line.volume_reporting_grade_id = False
                line.volume_reference_uom_id = False
                line.volume_conversion_ratio = 0.0
                line.order_line_grade_volume = 0.0
                line.order_line_grade_volume_label = False
                continue

            grade = line._get_lpo_volume_reporting_grade()
            try:
                reference_uom = line._get_lpo_volume_reference_uom()
                grade_volume = line.product_uom._compute_quantity(
                    line.product_qty or 0.0,
                    reference_uom,
                    round=False,
                )
            except Exception as error:
                _logger.warning(
                    "LPO_GRADE_VOLUME_FAILED line_id=%s product_id=%s uom_id=%s error=%s",
                    line.id,
                    line.product_id.id,
                    line.product_uom.id,
                    error,
                )
                reference_uom = self.env['uom.uom']
                grade_volume = 0.0

            line.volume_reporting_grade_id = grade
            line.volume_reference_uom_id = reference_uom
            line.volume_conversion_ratio = (
                grade_volume / line.product_qty if line.product_qty else 0.0
            )
            line.order_line_grade_volume = grade_volume
            line.order_line_grade_volume_label = (
                f"{line.order_id._lpo_report_format_float(grade_volume, 2)} {reference_uom.name}"
                if reference_uom
                else line.order_id._lpo_report_format_float(grade_volume, 2)
            )

    @api.onchange('product_id', 'product_qty', 'product_uom')
    def _onchange_lpo_grade_volume_fields(self):
        self._compute_lpo_grade_volume_fields()

    def _get_rfq_bill_price_check_count(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'purchase_net_price_compute.rfq_bill_price_check_count',
            '3'
        )
        try:
            return max(int(value or 0), 0)
        except ValueError:
            return 0

    def _get_lowest_recent_bill_price(self):
        self.ensure_one()

        bill_count = self._get_rfq_bill_price_check_count()
        if not bill_count or not self.product_id or not self.order_id.partner_id:
            return False

        order = self.order_id
        bill_lines = self.env['account.move.line'].search([
            ('move_id.move_type', '=', 'in_invoice'),
            ('move_id.state', '=', 'posted'),
            ('move_id.partner_id', '=', order.partner_id.id),
            ('company_id', '=', order.company_id.id),
            ('product_id', '=', self.product_id.id),
            ('display_type', '=', 'product'),
            ('quantity', '!=', 0),
        ], order='date desc, move_id desc, id desc')

        selected_bill_ids = []
        prices = []
        for bill_line in bill_lines:
            bill = bill_line.move_id
            if bill.id not in selected_bill_ids:
                if len(selected_bill_ids) >= bill_count:
                    continue
                selected_bill_ids.append(bill.id)

            price = (
                bill_line.net_price
                if 'net_price' in bill_line._fields and bill_line.net_price
                else bill_line.price_unit
            )
            if price <= 0:
                continue

            if bill_line.product_uom_id and self.product_uom and bill_line.product_uom_id != self.product_uom:
                price = bill_line.product_uom_id._compute_price(price, self.product_uom)

            if bill_line.currency_id and order.currency_id and bill_line.currency_id != order.currency_id:
                price = bill_line.currency_id._convert(
                    price,
                    order.currency_id,
                    order.company_id,
                    bill.invoice_date or bill.date or fields.Date.context_today(self),
                )

            prices.append(price)

        if not prices:
            _logger.info(
                "No recent posted bill prices found for %s (id=%s) / vendor %s (id=%s) / company %s",
                self.product_id.display_name,
                self.product_id.id,
                order.partner_id.display_name,
                order.partner_id.id,
                order.company_id.id,
            )
            return False

        lowest_price = min(prices)
        _logger.info(
            "Recent posted bill prices for %s (id=%s) / vendor %s from bills %s: %s; selected lowest=%s",
            self.product_id.display_name,
            self.product_id.id,
            order.partner_id.display_name,
            selected_bill_ids,
            prices,
            lowest_price,
        )
        return lowest_price

    def _apply_lowest_recent_bill_price(self):
        for line in self:
            if line.order_id.state not in ('draft', 'sent'):
                continue
            lowest_price = line._get_lowest_recent_bill_price()
            if lowest_price:
                _logger.info(
                    "Using lowest recent bill price for %s on RFQ %s: %s",
                    line.product_id.display_name,
                    line.order_id.name or 'New',
                    lowest_price,
                )
                if line.id:
                    line.with_context(skip_rfq_bill_price=True).write({
                        'price_unit': lowest_price,
                    })
                else:
                    line.price_unit = lowest_price

    @api.depends(
        'product_id',
        'product_qty',
        'product_uom',
        'company_id',
        'order_id.partner_id',
        'order_id.currency_id',
        'use_custom_pricing',
    )
    def _compute_price_unit_and_date_planned_and_name(self):
        # Run standard Odoo logic first (sets price_unit from product.supplierinfo
        # or standard_price, and sets date_planned / name).
        super()._compute_price_unit_and_date_planned_and_name()

        # Post-correction for template-level vendor prices: Odoo's standard
        # compute may resolve a supplierinfo line without product_id, which can
        # assign the same template price to every variant.
        for line in self:
            if not line.product_id or line.invoice_lines or not line.company_id:
                continue
            params = line._get_select_sellers_params()
            seller = line.product_id._select_seller(
                partner_id=line.partner_id,
                quantity=line.product_qty,
                date=(line.order_id.date_order and line.order_id.date_order.date()
                      or fields.Date.context_today(line)),
                uom_id=line.product_uom,
                params=params,
            )
            # seller.product_id is False for template-level entries → same price
            # for all variants. Replace with this variant's own standard_price.
            if seller and not seller.product_id and line.product_id.standard_price:
                line.price_unit = line.product_id.standard_price

        self._apply_lowest_recent_bill_price()

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

    def _product_id_change(self):
        res = super()._product_id_change()
        self._apply_lowest_recent_bill_price()
        self._compute_net_price()
        return res

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

            # Only use a pricing rule's price_unit when the rule targets this
            # specific variant (product_id is set). Template-level rules
            # (product_id = False) apply discount/freight to all variants but
            # must NOT override the per-variant cost price, otherwise every
            # variant in the matrix gets the same price as the first one.
            if (line.pricing_rule_id
                    and line.pricing_rule_id.price_unit > 0
                    and line.pricing_rule_id.product_id):
                line.price_unit = line.pricing_rule_id.price_unit

            line._apply_lowest_recent_bill_price()

            # Recalculate net_price to reflect new discount and freight
            line._compute_net_price()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get('skip_rfq_bill_price'):
            rfq_lines = lines.filtered(
                lambda line: (
                    line.order_id.state in ('draft', 'sent')
                    and line.product_id
                    and line.order_id.partner_id
                )
            )
            rfq_lines._apply_lowest_recent_bill_price()
            rfq_lines._compute_net_price()
        if not self.env.context.get('skip_lpo_grade_volume_line_chatter'):
            lines.mapped('order_id')._post_lpo_grade_volume_summary_change({})
        return lines

    def write(self, vals):
        grade_volume_trigger_fields = {
            'product_id',
            'product_qty',
            'product_uom',
            'display_type',
            'order_id',
            'price_unit',
            'discount',
            'taxes_id',
            'net_price',
            'price_subtotal',
            'price_tax',
            'price_total',
        }
        previous_summaries = {}
        if (
            not self.env.context.get('skip_lpo_grade_volume_line_chatter')
            and grade_volume_trigger_fields.intersection(vals)
        ):
            previous_summaries = {
                order.id: order.lpo_grade_volume_summary
                for order in self.mapped('order_id')
            }

        res = super().write(vals)
        trigger_fields = {
            'product_id',
            'product_qty',
            'product_uom',
            'order_id',
            'price_unit',
        }
        if not self.env.context.get('skip_rfq_bill_price') and trigger_fields.intersection(vals):
            rfq_lines = self.filtered(
                lambda line: (
                    line.order_id.state in ('draft', 'sent')
                    and line.product_id
                    and line.order_id.partner_id
                )
            )
            rfq_lines._apply_lowest_recent_bill_price()
            rfq_lines._compute_net_price()
        if previous_summaries:
            self.mapped('order_id')._post_lpo_grade_volume_summary_change(previous_summaries)
        return res

    def unlink(self):
        previous_summaries = {}
        if not self.env.context.get('skip_lpo_grade_volume_line_chatter'):
            previous_summaries = {
                order.id: order.lpo_grade_volume_summary
                for order in self.mapped('order_id')
            }
        orders = self.mapped('order_id')
        result = super().unlink()
        if previous_summaries:
            orders._post_lpo_grade_volume_summary_change(previous_summaries)
        return result

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
