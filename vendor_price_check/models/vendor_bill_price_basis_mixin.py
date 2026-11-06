import hashlib
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare, float_round

from odoo.addons.purchase_net_price_compute.models.vendor_invoice_profile import (
    VENDOR_INVOICE_PROFILE_STANDARD,
    VENDOR_PRICE_BASIS_SELECTION,
)


_logger = logging.getLogger(__name__)


class VendorBillPriceBasisMixin(models.AbstractModel):
    _name = 'vendor.bill.price.basis.mixin'
    _description = 'Shared Vendor Bill Price Entry Basis'

    vendor_price_basis = fields.Selection(
        VENDOR_PRICE_BASIS_SELECTION,
        string='Vendor Price Basis',
        default='excluded',
        required=True,
        help='Basis of the entered vendor unit/list prices, before discount and freight. '
             'If printed prices already include these adjustments, enter zero discount and freight. '
             'The final invoice total always includes VAT.',
    )
    supports_vendor_price_basis = fields.Boolean(compute='_compute_supports_vendor_price_basis')
    price_basis_review_signature = fields.Char(readonly=True, copy=False)

    def _get_price_basis_vendor(self):
        """Concrete wizards return their commercial vendor."""
        raise NotImplementedError()

    def _get_price_basis_orders(self):
        """Concrete wizards return the source purchase orders."""
        raise NotImplementedError()

    def _supports_vendor_price_basis(self):
        """Profiles may explicitly opt into standard price normalization."""
        self.ensure_one()
        vendor = self._get_price_basis_vendor()
        return bool(vendor and vendor.get_vendor_invoice_profile() == VENDOR_INVOICE_PROFILE_STANDARD)

    @api.depends('vendor_invoice_profile')
    def _compute_supports_vendor_price_basis(self):
        for wizard in self:
            wizard.supports_vendor_price_basis = wizard._supports_vendor_price_basis()

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wizard, values in zip(wizards, vals_list):
            if 'vendor_price_basis' not in values and wizard._supports_vendor_price_basis():
                wizard.vendor_price_basis = wizard._get_price_basis_vendor().get_vendor_bill_price_basis()
        return wizards

    @api.constrains('vendor_price_basis')
    def _check_vendor_price_basis(self):
        for wizard in self:
            if wizard.vendor_price_basis == 'included' and not wizard._supports_vendor_price_basis():
                _logger.warning(
                    '[VPC][PRICE_BASIS][ERROR] wizard_model=%s wizard_id=%s reason=formula_profile',
                    wizard._name, wizard.id,
                )
                raise ValidationError(_('VAT-inclusive entry is unavailable for this vendor invoice formula.'))

    def _price_basis_reset_values(self):
        return {
            'promised_cost_discrepancy_approved': False,
            'promised_cost_discrepancy_approved_by_id': False,
            'variance_warning_dismiss_count': 0,
            'price_basis_review_signature': False,
        }

    @api.onchange('vendor_price_basis')
    def _onchange_vendor_price_basis(self):
        for wizard in self:
            wizard.update(wizard._price_basis_reset_values())

    def write(self, vals):
        if {'vendor_price_basis', 'vendor_invoice_final_total', 'gamma_vendor_invoice_final_total',
            'purchase_id', 'purchase_ids', 'partner_id', 'vendor_invoice_profile'}.intersection(vals):
            vals = dict(vals, **self._price_basis_reset_values())
        return super().write(vals)

    def _validate_price_basis(self):
        self.ensure_one()
        _logger.debug('[VPC][PRICE_BASIS][START] wizard_model=%s wizard_id=%s', self._name, self.id)
        try:
            self._validate_price_basis_inputs()
        except Exception:
            _logger.debug(
                '[VPC][PRICE_BASIS][ERROR] wizard_model=%s wizard_id=%s outcome=validation_failed',
                self._name, self.id, exc_info=True,
            )
            raise
        _logger.debug('[VPC][PRICE_BASIS][END] wizard_model=%s wizard_id=%s outcome=validated', self._name, self.id)

    def _validate_price_basis_inputs(self):
        self._check_vendor_price_basis()
        vendor = self._get_price_basis_vendor()
        if self.vendor_invoice_profile != vendor.get_vendor_invoice_profile():
            raise ValidationError(_('The vendor invoice formula changed. Reopen the bill wizard.'))
        orders = self._get_price_basis_orders()
        if len(orders.company_id) != 1 or orders.company_id not in self.env.companies:
            raise ValidationError(_('Source purchase orders must belong to one allowed company.'))
        if orders.currency_id != self.currency_id or orders.partner_id.commercial_partner_id != vendor:
            raise ValidationError(_('Source purchase orders must match the wizard vendor and currency.'))
        if self.bill_id and (
            self.bill_id.state != 'draft' or self.bill_id.move_type != 'in_invoice'
            or self.bill_id.company_id != orders.company_id
            or self.bill_id.partner_id.commercial_partner_id != vendor
            or self.bill_id.currency_id != self.currency_id
        ):
            raise ValidationError(_('Only a matching draft vendor bill can be updated.'))
        for line in self.line_ids:
            if 'include_line' in line._fields and not line.include_line:
                continue
            purchase_line = line.purchase_line_id
            if purchase_line.order_id not in orders or line.product_id != purchase_line.product_id:
                raise ValidationError(_('Each bill line must match a product on a source purchase order.'))
            if line.currency_id != self.currency_id:
                raise ValidationError(_('Bill line currency must match the wizard currency.'))
            remaining = purchase_line.order_id._get_invoice_wizard_received_qty(purchase_line)
            comparison = float_compare(line.product_qty, remaining, precision_rounding=purchase_line.product_uom.rounding)
            if comparison > 0 or ('include_line' not in line._fields and comparison != 0):
                raise ValidationError(_('Received uninvoiced quantities changed. Reopen or reload the bill wizard.'))
        self._invalidate_stale_price_basis_review()
        if self.vendor_price_basis == 'included':
            self._validate_inclusive_bill_precision()

    def _get_price_basis_review_signature(self):
        self.ensure_one()
        values = [self.vendor_price_basis, self._get_price_basis_vendor().get_vendor_invoice_profile(),
                  self._get_variance_policy_vendor_final_total(), self.currency_id.rounding]
        for line in self.line_ids.sorted('id'):
            taxes = line.purchase_line_id.taxes_id.flatten_taxes_hierarchy()
            values.append([
                line.id, line.purchase_line_id.id, line.vendor_price, line.product_qty,
                line.applied_discount, line.applied_freight,
                line._get_effective_bill_unit_price(),
                [(tax.id, tax.amount, tax.amount_type, tax.price_include, tax.sequence,
                  tax.include_base_amount, tax.is_base_affected) for tax in taxes],
            ])
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def _remember_price_basis_review(self):
        for wizard in self:
            wizard.price_basis_review_signature = wizard._get_price_basis_review_signature()

    def _invalidate_stale_price_basis_review(self):
        for wizard in self:
            if (wizard.promised_cost_discrepancy_approved or wizard.variance_warning_dismiss_count) and (
                wizard.price_basis_review_signature != wizard._get_price_basis_review_signature()
            ):
                wizard.write(wizard._price_basis_reset_values())

    def _validate_inclusive_bill_precision(self):
        """Respect native unit-price precision without silently changing global settings."""
        precision = self.env['decimal.precision'].precision_get('Product Price')
        for line in self.line_ids:
            if 'include_line' in line._fields and not line.include_line:
                continue
            unit = line._get_effective_bill_unit_price()
            rounded_unit = float_round(unit, precision_digits=precision)
            purchase_line = line.purchase_line_id
            expected = purchase_line._get_price_with_configured_vat(
                unit, quantity=line.product_qty, currency=self.currency_id,
                partner=self._get_price_basis_vendor(),
            )
            actual = purchase_line._get_price_with_configured_vat(
                rounded_unit, quantity=line.product_qty, currency=self.currency_id,
                partner=self._get_price_basis_vendor(),
            )
            if self.currency_id.compare_amounts(expected, actual):
                _logger.warning(
                    '[VPC][PRICE_BASIS][ERROR] wizard_model=%s wizard_id=%s purchase_line_id=%s '
                    'reason=insufficient_product_price_precision digits=%s',
                    self._name, self.id, purchase_line.id, precision,
                )
                raise ValidationError(_(
                    'Product Price precision (%(digits)s decimal places) would change the VAT-inclusive '
                    'total for %(product)s. Increase Product Price decimal accuracy in Settings '
                    'and reopen the wizard before creating the bill.'
                ) % {'digits': precision, 'product': line.product_id.display_name})

    def _get_price_basis_audit_value(self):
        self.ensure_one()
        return self.vendor_price_basis if self._supports_vendor_price_basis() else 'profile'

    def _get_standard_bill_unit_price(self, line, round_exclusive=False):
        """Normalize list price once, then apply discount/freight on the exclusive base.

        The caller selects legacy rounding for exclusive input. Included input
        retains precision until Odoo computes the actual bill line taxes.
        """
        self.ensure_one()
        unit = line.vendor_price or 0.0
        if self.vendor_price_basis == 'included' and self._supports_vendor_price_basis():
            purchase_line = line.purchase_line_id
            taxes = purchase_line.taxes_id
            _logger.debug(
                '[VPC][PRICE_NORMALIZE][START] wizard_model=%s wizard_id=%s purchase_line_id=%s '
                'company_id=%s tax_ids=%s basis=%s',
                self._name, self.id, purchase_line.id, purchase_line.company_id.id,
                taxes.ids, self.vendor_price_basis,
            )
            try:
                self._validate_inclusive_price_taxes(purchase_line)
                quantity = line.product_qty or 1.0
                result = taxes.with_company(purchase_line.company_id).with_context(
                    force_price_include=True, round_base=False,
                ).compute_all(
                    unit, currency=line.currency_id, quantity=quantity,
                    product=line.product_id, partner=self._get_price_basis_vendor(),
                    rounding_method='round_globally',
                )
                unit = result['total_excluded'] / quantity
            except Exception:
                _logger.debug(
                    '[VPC][PRICE_NORMALIZE][ERROR] wizard_model=%s wizard_id=%s purchase_line_id=%s',
                    self._name, self.id, purchase_line.id, exc_info=True,
                )
                raise
            _logger.debug(
                '[VPC][PRICE_NORMALIZE][END] wizard_model=%s wizard_id=%s purchase_line_id=%s outcome=normalized',
                self._name, self.id, purchase_line.id,
            )
        unit *= (1 - (line.applied_discount or 0.0) / 100.0)
        unit *= (1 + (line.applied_freight or 0.0) / 100.0)
        return round(unit, 2) if round_exclusive and self.vendor_price_basis == 'excluded' else unit

    def _validate_inclusive_price_taxes(self, purchase_line):
        if not purchase_line or not purchase_line.taxes_id:
            raise ValidationError(_('Configure purchase taxes (including explicit zero/exempt taxes) before using VAT-inclusive entry.'))
        taxes = purchase_line.taxes_id.flatten_taxes_hierarchy()
        if any(tax.company_id != purchase_line.company_id for tax in taxes):
            raise ValidationError(_('Purchase taxes must belong to the purchase order company.'))
        if any(taxes.mapped('price_include')):
            raise ValidationError(_(
                'This wizard stores exclusive bill prices. VAT-inclusive entry requires tax-excluded '
                'purchase taxes. Review the tax configuration before continuing.'
            ))


class VendorBillPriceBasisLineMixin(models.AbstractModel):
    _name = 'vendor.bill.price.basis.line.mixin'
    _description = 'Vendor Bill Price Entry Approval Invalidation'

    def _price_basis_input_fields(self):
        return {
            'vendor_price', 'vendor_line_total', 'product_qty', 'include_line',
            'applied_discount', 'applied_freight', 'purchase_line_id',
            'gamma_tint_type', 'gamma_tint_percentage',
        }

    def _reset_price_basis_approvals(self):
        wizards = self.mapped('wizard_id')
        if wizards:
            wizards.write(wizards._price_basis_reset_values())

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._reset_price_basis_approvals()
        return lines

    def write(self, vals):
        wizards = self.mapped('wizard_id')
        result = super().write(vals)
        if self._price_basis_input_fields().intersection(vals) or 'wizard_id' in vals:
            wizards |= self.mapped('wizard_id')
            wizards.write(wizards._price_basis_reset_values())
        return result

    def unlink(self):
        self._reset_price_basis_approvals()
        return super().unlink()
