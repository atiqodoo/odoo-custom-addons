import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from ..services.promotion_registry import get_calculator
from .res_partner import VENDOR_PROFILE_GAMMA


_logger = logging.getLogger(__name__)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    vendor_invoice_profile = fields.Selection(
        related='order_id.partner_id.vendor_invoice_profile',
        string='Vendor Profile',
        readonly=True,
    )
    promotion_id = fields.Many2one(
        'vendor.purchase.promotion',
        string='Promotion',
        index=True,
        copy=False,
        ondelete='restrict',
    )
    promotion_foc_qty = fields.Float(
        string='Promised FOC Qty',
        copy=False,
        readonly=True,
    )
    promotion_total_expected_qty = fields.Float(
        string='Total Expected Qty',
        compute='_compute_promotion_total_expected_qty',
    )
    is_promotion_foc = fields.Boolean(
        string='FOC Promotion Line',
        default=False,
        copy=False,
        index=True,
    )
    promotion_parent_line_id = fields.Many2one(
        'purchase.order.line',
        string='Charged Promotion Line',
        copy=False,
        index=True,
        ondelete='cascade',
    )
    promotion_foc_line_ids = fields.One2many(
        'purchase.order.line',
        'promotion_parent_line_id',
        string='FOC Lines',
        copy=False,
    )
    promotion_application_id = fields.Many2one(
        'vendor.purchase.promotion.application',
        string='Promotion Application',
        compute='_compute_promotion_application_id',
        readonly=True,
    )

    gamma_list_unit_price = fields.Monetary(
        string='Gamma List Unit Price',
        currency_field='currency_id',
        copy=False,
    )
    gamma_discount_percentage = fields.Float(
        string='Gamma Discount %',
        copy=False,
    )
    gamma_tint_type = fields.Selection(
        [
            ('not_tinted', 'Not Tinted'),
            ('factory', 'Factory'),
            ('showroom_branch', 'Showroom/Branch'),
            ('custom', 'Custom'),
        ],
        string='Gamma Tinting',
        default='not_tinted',
        copy=False,
    )
    gamma_tint_percentage = fields.Float(
        string='Gamma Tint %',
        default=0.0,
        copy=False,
    )
    gamma_gross_total = fields.Monetary(
        string='Gamma Gross',
        compute='_compute_gamma_amounts',
        currency_field='currency_id',
    )
    gamma_discount_amount = fields.Monetary(
        string='Gamma Discount Amount',
        compute='_compute_gamma_amounts',
        currency_field='currency_id',
    )
    gamma_tint_charge = fields.Monetary(
        string='Gamma Tint Charge',
        compute='_compute_gamma_amounts',
        currency_field='currency_id',
    )
    gamma_subtotal_excl_vat = fields.Monetary(
        string='Gamma Subtotal Excl. VAT',
        compute='_compute_gamma_amounts',
        currency_field='currency_id',
    )
    gamma_unit_cost_excl_vat = fields.Monetary(
        string='Gamma Unit Cost Excl. VAT',
        compute='_compute_gamma_amounts',
        currency_field='currency_id',
    )

    @api.depends('product_qty', 'promotion_foc_qty')
    def _compute_promotion_total_expected_qty(self):
        for line in self:
            line.promotion_total_expected_qty = (
                line.product_qty if line.is_promotion_foc
                else line.product_qty + line.promotion_foc_qty
            )

    def _compute_promotion_application_id(self):
        applications = self.env['vendor.purchase.promotion.application'].search([
            '|',
            ('charged_line_id', 'in', self.ids),
            ('foc_line_id', 'in', self.ids),
        ]) if self.ids else self.env['vendor.purchase.promotion.application']
        by_line = {}
        for application in applications:
            by_line[application.charged_line_id.id] = application
            by_line[application.foc_line_id.id] = application
        for line in self:
            line.promotion_application_id = by_line.get(line.id, False)

    @api.depends(
        'vendor_invoice_profile',
        'product_qty',
        'gamma_list_unit_price',
        'gamma_discount_percentage',
        'gamma_tint_percentage',
        'is_promotion_foc',
    )
    def _compute_gamma_amounts(self):
        calculator = get_calculator(VENDOR_PROFILE_GAMMA)
        for line in self:
            if line.vendor_invoice_profile != VENDOR_PROFILE_GAMMA or line.is_promotion_foc:
                line.gamma_gross_total = 0.0
                line.gamma_discount_amount = 0.0
                line.gamma_tint_charge = 0.0
                line.gamma_subtotal_excl_vat = 0.0
                line.gamma_unit_cost_excl_vat = 0.0
                continue
            try:
                result = calculator.calculate_unit(
                    quantity=line.product_qty,
                    list_unit_price=line.gamma_list_unit_price,
                    discount_percentage=line.gamma_discount_percentage,
                    tint_percentage=line.gamma_tint_percentage,
                )
            except ValueError:
                result = {
                    'gross_total': 0.0,
                    'discount_amount': 0.0,
                    'tint_charge': 0.0,
                    'subtotal_excl_vat': 0.0,
                    'unit_cost_excl_vat': 0.0,
                }
            line.gamma_gross_total = result['gross_total']
            line.gamma_discount_amount = result['discount_amount']
            line.gamma_tint_charge = result['tint_charge']
            line.gamma_subtotal_excl_vat = result['subtotal_excl_vat']
            line.gamma_unit_cost_excl_vat = result['unit_cost_excl_vat']

    @api.onchange('gamma_tint_type')
    def _onchange_gamma_tint_type(self):
        rates = get_calculator(VENDOR_PROFILE_GAMMA).TINT_RATES
        for line in self:
            if line.gamma_tint_type in rates:
                line.gamma_tint_percentage = rates[line.gamma_tint_type]

    @api.onchange('product_id', 'product_qty', 'order_id.partner_id')
    def _onchange_vendor_promotion(self):
        for line in self:
            if line.is_promotion_foc or not line.product_id or not line.order_id.partner_id:
                continue
            rule = self.env['vendor.purchase.promotion'].resolve_rule(
                line.order_id,
                line.product_id,
                line.product_qty,
            )
            line.promotion_id = rule
            line.promotion_foc_qty = rule.calculate_foc_qty(line.product_qty) if rule else 0.0
            if line.vendor_invoice_profile == VENDOR_PROFILE_GAMMA:
                if not line.gamma_list_unit_price:
                    line.gamma_list_unit_price = line.price_unit
                if rule:
                    if rule.override_discount:
                        line.gamma_discount_percentage = rule.discount_percentage
                    line.gamma_tint_type = rule.default_tint_type
                    line.gamma_tint_percentage = rule.default_tint_percentage

    @api.onchange(
        'gamma_list_unit_price',
        'gamma_discount_percentage',
        'gamma_tint_percentage',
    )
    def _onchange_gamma_pricing(self):
        for line in self.filtered(
            lambda item: item.vendor_invoice_profile == VENDOR_PROFILE_GAMMA
            and not item.is_promotion_foc
        ):
            line._compute_gamma_amounts()
            line.price_unit = line.gamma_unit_cost_excl_vat
            line.discount = 0.0

    def _prepare_gamma_pricing(self):
        for line in self.filtered(
            lambda item: item.vendor_invoice_profile == VENDOR_PROFILE_GAMMA
            and not item.is_promotion_foc
        ):
            if line.gamma_list_unit_price <= 0:
                line.gamma_list_unit_price = line.price_unit
            calculator = get_calculator(VENDOR_PROFILE_GAMMA)
            try:
                result = calculator.calculate_unit(
                    quantity=line.product_qty,
                    list_unit_price=line.gamma_list_unit_price,
                    discount_percentage=line.gamma_discount_percentage,
                    tint_percentage=line.gamma_tint_percentage,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            if line.product_qty <= 0:
                raise ValidationError(_('Charged quantity must be greater than zero for %s.') % line.product_id.display_name)
            line.with_context(skip_rfq_bill_price=True).write({
                'price_unit': result['unit_cost_excl_vat'],
                'discount': 0.0,
            })
            _logger.info(
                '[VPP_GAMMA_RFQ] priced po_id=%s line_id=%s product_id=%s charged_qty=%s '
                'list_unit=%s discount_pct=%s tint_type=%s tint_pct=%s unit_cost_excl=%s subtotal=%s',
                line.order_id.id,
                line.id,
                line.product_id.id,
                line.product_qty,
                line.gamma_list_unit_price,
                line.gamma_discount_percentage,
                line.gamma_tint_type,
                line.gamma_tint_percentage,
                result['unit_cost_excl_vat'],
                result['subtotal_excl_vat'],
            )

    @api.depends(
        'invoice_lines.move_id.state',
        'invoice_lines.quantity',
        'qty_received',
        'product_uom_qty',
        'order_id.state',
        'is_promotion_foc',
    )
    def _compute_qty_invoiced(self):
        super()._compute_qty_invoiced()
        for line in self.filtered('is_promotion_foc'):
            line.qty_to_invoice = 0.0

