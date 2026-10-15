import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from ..services.promotion_registry import get_calculator
from .res_partner import VENDOR_PROFILE_GAMMA


_logger = logging.getLogger(__name__)


class VendorPriceWizardLine(models.TransientModel):
    _inherit = 'vendor.price.wizard.line'

    gamma_tint_type = fields.Selection(
        [
            ('not_tinted', 'Not Tinted'),
            ('factory', 'Factory'),
            ('showroom_branch', 'Showroom/Branch'),
            ('custom', 'Custom'),
        ],
        string='Gamma Tinting',
        default='not_tinted',
    )
    gamma_tint_percentage = fields.Float(string='Gamma Tint %')
    gamma_gross_total = fields.Monetary(
        string='Gamma Gross',
        compute='_compute_gamma_invoice_amounts',
        store=True,
        currency_field='currency_id',
    )
    gamma_discount_amount = fields.Monetary(
        string='Gamma Discount',
        compute='_compute_gamma_invoice_amounts',
        store=True,
        currency_field='currency_id',
    )
    gamma_tint_charge = fields.Monetary(
        string='Gamma Tint Charge',
        compute='_compute_gamma_invoice_amounts',
        store=True,
        currency_field='currency_id',
    )
    gamma_subtotal_excl_vat = fields.Monetary(
        string='Gamma Subtotal Excl. VAT',
        compute='_compute_gamma_invoice_amounts',
        store=True,
        currency_field='currency_id',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            purchase_line = self.env['purchase.order.line'].browse(vals.get('purchase_line_id'))
            if (
                purchase_line
                and purchase_line.order_id.partner_id.vendor_invoice_profile == VENDOR_PROFILE_GAMMA
            ):
                if not vals.get('vendor_price'):
                    vals['vendor_price'] = (
                        purchase_line.gamma_list_unit_price or purchase_line.price_unit
                    )
                vals['applied_discount'] = purchase_line.gamma_discount_percentage
                vals['applied_freight'] = 0.0
                vals['gamma_tint_type'] = purchase_line.gamma_tint_type
                vals['gamma_tint_percentage'] = purchase_line.gamma_tint_percentage
                _logger.debug(
                    '[VPP_GAMMA_WIZARD] initialize purchase_line_id=%s received_to_bill=%s '
                    'list_unit=%s discount_pct=%s tint_type=%s tint_pct=%s',
                    purchase_line.id,
                    vals.get('product_qty'),
                    vals['vendor_price'],
                    vals['applied_discount'],
                    vals['gamma_tint_type'],
                    vals['gamma_tint_percentage'],
                )
        return super().create(vals_list)

    def _is_gamma_profile(self):
        self.ensure_one()
        return self.wizard_id.vendor_invoice_profile == VENDOR_PROFILE_GAMMA

    @api.onchange('gamma_tint_type')
    def _onchange_gamma_tint_type(self):
        rates = get_calculator(VENDOR_PROFILE_GAMMA).TINT_RATES
        for line in self:
            if line.gamma_tint_type in rates:
                line.gamma_tint_percentage = rates[line.gamma_tint_type]

    @api.depends(
        'vendor_price',
        'applied_discount',
        'gamma_tint_percentage',
        'product_qty',
        'wizard_id.vendor_invoice_profile',
    )
    def _compute_gamma_invoice_amounts(self):
        calculator = get_calculator(VENDOR_PROFILE_GAMMA)
        for line in self:
            if not line._is_gamma_profile():
                line.gamma_gross_total = 0.0
                line.gamma_discount_amount = 0.0
                line.gamma_tint_charge = 0.0
                line.gamma_subtotal_excl_vat = 0.0
                continue
            try:
                result = calculator.calculate_unit(
                    quantity=line.product_qty,
                    list_unit_price=line.vendor_price,
                    discount_percentage=line.applied_discount,
                    tint_percentage=line.gamma_tint_percentage,
                )
            except ValueError:
                result = {
                    'gross_total': 0.0,
                    'discount_amount': 0.0,
                    'tint_charge': 0.0,
                    'subtotal_excl_vat': 0.0,
                }
            line.gamma_gross_total = result['gross_total']
            line.gamma_discount_amount = result['discount_amount']
            line.gamma_tint_charge = result['tint_charge']
            line.gamma_subtotal_excl_vat = result['subtotal_excl_vat']

    @api.depends(
        'vendor_price',
        'applied_discount',
        'applied_freight',
        'gamma_tint_percentage',
        'wizard_id.vendor_invoice_profile',
    )
    def _compute_calculated_subtotal(self):
        super()._compute_calculated_subtotal()
        calculator = get_calculator(VENDOR_PROFILE_GAMMA)
        for line in self.filtered(lambda item: item._is_gamma_profile()):
            try:
                result = calculator.calculate_unit(
                    quantity=1.0,
                    list_unit_price=line.vendor_price,
                    discount_percentage=line.applied_discount,
                    tint_percentage=line.gamma_tint_percentage,
                )
            except ValueError:
                line.calculated_subtotal = 0.0
                continue
            line.calculated_subtotal = result['unit_cost_excl_vat']
            _logger.debug(
                '[VPP_GAMMA_WIZARD] subtotal line_id=%s product_id=%s received_charged_qty=%s '
                'list_unit=%s discount_pct=%s tint_pct=%s bill_unit_excl=%s',
                line.id,
                line.product_id.id,
                line.product_qty,
                line.vendor_price,
                line.applied_discount,
                line.gamma_tint_percentage,
                line.calculated_subtotal,
            )

    @api.onchange(
        'vendor_price',
        'applied_discount',
        'gamma_tint_percentage',
    )
    def _onchange_gamma_pricing(self):
        self._compute_calculated_subtotal()
        self._compute_gamma_invoice_amounts()

    def _validate_for_bill(self):
        super()._validate_for_bill()
        if not self._is_gamma_profile():
            return
        if self.product_qty <= 0:
            raise ValidationError(
                _('Received charged quantity must be greater than zero for %s.')
                % self.product_id.display_name
            )
        if not 0.0 <= self.applied_discount <= 100.0:
            raise ValidationError(_('Gamma discount must be between 0 and 100 percent.'))
        if self.gamma_tint_percentage < 0:
            raise ValidationError(_('Gamma tint percentage cannot be negative.'))
        if not self.purchase_line_id.taxes_id:
            raise ValidationError(
                _('Configure purchase VAT/taxes for %s before creating the Gamma bill.')
                % self.product_id.display_name
            )

    def _get_effective_bill_unit_price(self):
        self.ensure_one()
        if self._is_gamma_profile():
            return self.wizard_id._apply_invoice_allocation_to_unit_price(
                self.calculated_subtotal,
                line=self,
            )
        return super()._get_effective_bill_unit_price()

    def _get_effective_bill_discount(self):
        self.ensure_one()
        if self._is_gamma_profile():
            return self.applied_discount
        return super()._get_effective_bill_discount()

    def _prepare_profile_bill_line_vals(self):
        values = super()._prepare_profile_bill_line_vals()
        if self._is_gamma_profile():
            values.update({
                'gamma_invoice_list_unit_price': self.vendor_price,
                'gamma_invoice_discount_percentage': self.applied_discount,
                'gamma_invoice_tint_type': self.gamma_tint_type,
                'gamma_invoice_tint_percentage': self.gamma_tint_percentage,
                'gamma_invoice_gross_total': self.gamma_gross_total,
                'gamma_invoice_discount_amount': self.gamma_discount_amount,
                'gamma_invoice_tint_charge': self.gamma_tint_charge,
                'gamma_invoice_subtotal_excl_vat': self.gamma_subtotal_excl_vat,
            })
        return values
