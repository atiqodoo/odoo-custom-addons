# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


_logger = logging.getLogger(__name__)
VARIANCE_LOG_HEAD = '[VPC_VARIANCE]'
ALLOCATION_LOG_HEAD = '[VPC_ALLOCATION]'


class VendorBillVariancePolicyMixin(models.AbstractModel):
    _name = 'vendor.bill.variance.policy.mixin'
    _description = 'Vendor Bill Invoice Variance Policy'

    variance_warning_dismiss_count = fields.Integer(
        string='Variance Warning Dismiss Count',
        default=0,
        copy=False,
    )
    allowed_invoice_variance_amount = fields.Float(
        string='Allowed Invoice Variance',
        compute='_compute_invoice_variance_policy',
    )
    required_variance_dismiss_count = fields.Integer(
        string='Required Variance Dismiss Count',
        compute='_compute_invoice_variance_policy',
    )
    block_invoice_variance_above_allowed = fields.Boolean(
        string='Block Invoice Variance Above Allowed',
        compute='_compute_invoice_variance_policy',
    )
    variance_policy_calculated_total = fields.Float(
        string='Policy Calculated Total',
        compute='_compute_invoice_variance_policy',
    )
    variance_policy_vendor_final_total = fields.Float(
        string='Policy Vendor Final Total',
        compute='_compute_invoice_variance_policy',
    )
    variance_policy_amount = fields.Float(
        string='Policy Invoice Variance',
        compute='_compute_invoice_variance_policy',
    )
    variance_policy_abs_amount = fields.Float(
        string='Policy Absolute Invoice Variance',
        compute='_compute_invoice_variance_policy',
    )
    variance_policy_exceeds_allowed = fields.Boolean(
        string='Invoice Variance Exceeds Allowed',
        compute='_compute_invoice_variance_policy',
    )
    variance_policy_requires_ack = fields.Boolean(
        string='Invoice Variance Requires Acknowledgement',
        compute='_compute_invoice_variance_policy',
    )
    variance_policy_acknowledged = fields.Boolean(
        string='Invoice Variance Acknowledged',
        compute='_compute_invoice_variance_policy',
    )
    variance_policy_message = fields.Text(
        string='Invoice Variance Message',
        compute='_compute_invoice_variance_policy',
    )
    invoice_variance_allocation_mode = fields.Selection(
        [
            ('none', 'No Invoice Total Allocation'),
            ('absorb_into_cost', 'Absorb Variance Into Product Cost'),
        ],
        string='Invoice Variance Allocation Mode',
        compute='_compute_invoice_variance_policy',
    )
    invoice_variance_allocation_enabled = fields.Boolean(
        string='Invoice Variance Allocation Enabled',
        compute='_compute_invoice_variance_policy',
    )
    require_vendor_invoice_final_total = fields.Boolean(
        string='Require Vendor Invoice Final Total',
        compute='_compute_invoice_variance_policy',
    )

    def _get_variance_policy_vendor(self):
        self.ensure_one()
        if 'partner_id' in self._fields and self.partner_id:
            return self.partner_id.commercial_partner_id
        if 'purchase_id' in self._fields and self.purchase_id:
            return self.purchase_id.partner_id.commercial_partner_id
        return self.env['res.partner']

    def _get_variance_policy_purchase_ids(self):
        self.ensure_one()
        if 'purchase_ids' in self._fields:
            return self.purchase_ids
        if 'purchase_id' in self._fields and self.purchase_id:
            return self.purchase_id
        return self.env['purchase.order']

    def _get_variance_policy_profile(self):
        self.ensure_one()
        if 'vendor_invoice_profile' in self._fields and self.vendor_invoice_profile:
            return self.vendor_invoice_profile
        vendor = self._get_variance_policy_vendor()
        return vendor.get_vendor_invoice_profile() if vendor else False

    def _get_variance_policy_calculated_total(self):
        self.ensure_one()
        return self.invoice_total_vat_incl if 'invoice_total_vat_incl' in self._fields else 0.0

    def _get_variance_policy_vendor_final_total(self):
        self.ensure_one()
        if (
            'is_gamma_profile' in self._fields
            and self.is_gamma_profile
            and 'gamma_vendor_invoice_final_total' in self._fields
        ):
            return self.gamma_vendor_invoice_final_total or 0.0
        if 'vendor_invoice_final_total' in self._fields:
            return self.vendor_invoice_final_total or 0.0
        return 0.0

    def _get_variance_policy_values(self, calculated_total=None):
        self.ensure_one()
        vendor = self._get_variance_policy_vendor()
        policy = (
            vendor.get_invoice_variance_policy()
            if vendor and hasattr(vendor, 'get_invoice_variance_policy')
            else {
                'allowed_amount': 0.0,
                'dismiss_clicks_required': 1,
                'block_above_allowed': True,
                'require_vendor_invoice_final_total': True,
                'allocation_mode': 'absorb_into_cost',
            }
        )
        calculated_total = (
            calculated_total
            if calculated_total is not None
            else self._get_variance_policy_calculated_total()
        )
        vendor_total = self._get_variance_policy_vendor_final_total()
        variance = calculated_total - vendor_total if vendor_total else 0.0
        abs_variance = abs(variance)
        allowed = policy['allowed_amount']
        required = policy['dismiss_clicks_required']
        exceeds = bool(vendor_total and abs_variance > allowed)
        requires_ack = bool(exceeds and policy['block_above_allowed'])
        acknowledged = self.variance_warning_dismiss_count >= required
        allocation_mode = policy.get('allocation_mode') or 'absorb_into_cost'
        allocation_ratio = (
            vendor_total / calculated_total
            if calculated_total and vendor_total and allocation_mode == 'absorb_into_cost'
            else 1.0
        )
        allocation_enabled = bool(
            vendor_total
            and calculated_total
            and allocation_mode == 'absorb_into_cost'
        )
        return {
            'vendor': vendor,
            'calculated_total': calculated_total,
            'vendor_total': vendor_total,
            'variance': variance,
            'abs_variance': abs_variance,
            'allowed': allowed,
            'required': required,
            'block': policy['block_above_allowed'],
            'require_final_total': policy.get('require_vendor_invoice_final_total', True),
            'exceeds': exceeds,
            'requires_ack': requires_ack,
            'acknowledged': acknowledged,
            'allocation_mode': allocation_mode,
            'allocation_ratio': allocation_ratio,
            'allocation_enabled': allocation_enabled,
        }

    def _compute_invoice_variance_policy(self):
        for wizard in self:
            values = wizard._get_variance_policy_values()
            wizard.allowed_invoice_variance_amount = values['allowed']
            wizard.required_variance_dismiss_count = values['required']
            wizard.block_invoice_variance_above_allowed = values['block']
            wizard.variance_policy_calculated_total = values['calculated_total']
            wizard.variance_policy_vendor_final_total = values['vendor_total']
            wizard.variance_policy_amount = values['variance']
            wizard.variance_policy_abs_amount = values['abs_variance']
            wizard.variance_policy_exceeds_allowed = values['exceeds']
            wizard.variance_policy_requires_ack = values['requires_ack']
            wizard.variance_policy_acknowledged = values['acknowledged']
            wizard.invoice_variance_allocation_mode = values['allocation_mode']
            wizard.invoice_variance_allocation_enabled = values['allocation_enabled']
            wizard.require_vendor_invoice_final_total = values['require_final_total']
            wizard.variance_policy_message = _(
                'Calculated Total: %(calculated).2f\n'
                'Vendor Invoice Total: %(vendor_total).2f\n'
                'Variance: %(variance).2f\n'
                'Allowed Variance: %(allowed).2f\n'
                'Dismissals Required: %(required)s\n'
                'Dismissals Done: %(done)s',
                calculated=values['calculated_total'],
                vendor_total=values['vendor_total'],
                variance=values['variance'],
                allowed=values['allowed'],
                required=values['required'],
                done=wizard.variance_warning_dismiss_count,
            )

    def _validate_required_vendor_invoice_final_total(self):
        self.ensure_one()
        values = self._get_variance_policy_values()
        if values['require_final_total'] and not values['vendor_total']:
            _logger.warning(
                '%s missing_vendor_final_total wizard_model=%s wizard_id=%s vendor_id=%s '
                'profile=%s required=%s',
                VARIANCE_LOG_HEAD,
                self._name,
                self.id,
                values['vendor'].id if values['vendor'] else False,
                self._get_variance_policy_profile(),
                values['require_final_total'],
            )
            raise ValidationError(_('Vendor Invoice Final Total must be greater than zero.'))

    def action_dismiss_invoice_variance_warning(self):
        for wizard in self:
            before = wizard.variance_warning_dismiss_count
            wizard.variance_warning_dismiss_count = before + 1
            values = wizard._get_variance_policy_values()
            _logger.warning(
                '%s dismiss wizard_model=%s wizard_id=%s vendor_id=%s before=%s after=%s '
                'required=%s variance=%s allowed=%s user_id=%s',
                VARIANCE_LOG_HEAD,
                wizard._name,
                wizard.id,
                values['vendor'].id if values['vendor'] else False,
                before,
                wizard.variance_warning_dismiss_count,
                values['required'],
                values['variance'],
                values['allowed'],
                wizard.env.user.id,
            )
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': {'dialog_size': 'extra-large'},
        }

    def _check_invoice_variance_policy(self):
        self.ensure_one()
        values = self._get_variance_policy_values()
        _logger.info(
            '%s check wizard_model=%s wizard_id=%s vendor_id=%s calculated=%s vendor_total=%s '
            'variance=%s abs_variance=%s allowed=%s block=%s dismissed=%s required=%s',
            VARIANCE_LOG_HEAD,
            self._name,
            self.id,
            values['vendor'].id if values['vendor'] else False,
            values['calculated_total'],
            values['vendor_total'],
            values['variance'],
            values['abs_variance'],
            values['allowed'],
            values['block'],
            self.variance_warning_dismiss_count,
            values['required'],
        )
        if values['requires_ack'] and not values['acknowledged']:
            _logger.warning(
                '%s blocked wizard_model=%s wizard_id=%s vendor_id=%s variance=%s allowed=%s '
                'dismissed=%s required=%s',
                VARIANCE_LOG_HEAD,
                self._name,
                self.id,
                values['vendor'].id if values['vendor'] else False,
                values['variance'],
                values['allowed'],
                self.variance_warning_dismiss_count,
                values['required'],
            )
            raise ValidationError(_(
                'Invoice variance exceeds this vendor allowed amount.\n\n'
                '%(message)s\n\nDismiss this warning %(remaining)s more time(s) before creating the bill.',
                message=self.variance_policy_message,
                remaining=max(values['required'] - self.variance_warning_dismiss_count, 0),
            ))

    def _get_invoice_allocation_values(self):
        self.ensure_one()
        values = self._get_variance_policy_values()
        _logger.info(
            '%s ratio_computed wizard_model=%s wizard_id=%s vendor_id=%s calculated=%s '
            'vendor_total=%s variance=%s mode=%s enabled=%s ratio=%s',
            ALLOCATION_LOG_HEAD,
            self._name,
            self.id,
            values['vendor'].id if values['vendor'] else False,
            values['calculated_total'],
            values['vendor_total'],
            values['variance'],
            values['allocation_mode'],
            values['allocation_enabled'],
            values['allocation_ratio'],
        )
        return values

    def _get_invoice_allocation_ratio(self):
        self.ensure_one()
        return self._get_invoice_allocation_values()['allocation_ratio']

    def _get_invoice_final_total_tolerance(self, bill):
        self.ensure_one()
        rounding = bill.currency_id.rounding or self.currency_id.rounding or 0.01
        invoice_line_count = len(bill.invoice_line_ids.filtered(
            lambda item: item.display_type not in ('line_section', 'line_note')
        ))
        return max(rounding, rounding * max(invoice_line_count, 1), 0.50)

    def _apply_invoice_allocation_to_unit_price(self, base_unit_price, line=False):
        self.ensure_one()
        values = self._get_invoice_allocation_values()
        allocated_unit = (
            (base_unit_price or 0.0) * values['allocation_ratio']
            if values['allocation_enabled']
            else (base_unit_price or 0.0)
        )
        _logger.info(
            '%s line_allocated wizard_model=%s wizard_id=%s line_model=%s line_id=%s '
            'mode=%s enabled=%s ratio=%s base_unit=%s allocated_unit=%s',
            ALLOCATION_LOG_HEAD,
            self._name,
            self.id,
            line._name if line else False,
            line.id if line else False,
            values['allocation_mode'],
            values['allocation_enabled'],
            values['allocation_ratio'],
            base_unit_price,
            allocated_unit,
        )
        return allocated_unit

    def _apply_invoice_final_total_rounding(self, bill):
        self.ensure_one()
        values = self._get_invoice_allocation_values()
        if not values['allocation_enabled']:
            return

        rounding = bill.currency_id.rounding or self.currency_id.rounding or 0.01
        tolerance = self._get_invoice_final_total_tolerance(bill)
        invoice_lines = bill.invoice_line_ids.filtered(
            lambda item: item.display_type not in ('line_section', 'line_note')
            and item.quantity
        )
        if not invoice_lines:
            return

        adjustment_line = invoice_lines.sorted(lambda item: abs(item.quantity or 0.0))[0]
        for attempt in range(3):
            delta_incl = values['vendor_total'] - bill.amount_total
            if float_compare(delta_incl, 0.0, precision_rounding=rounding) == 0:
                return
            if abs(delta_incl) <= tolerance + 0.0000001:
                _logger.info(
                    '%s payable_rounding_tolerance_accepted wizard_model=%s wizard_id=%s '
                    'bill_id=%s current_total=%s vendor_total=%s delta_incl=%s '
                    'rounding=%s tolerance=%s',
                    ALLOCATION_LOG_HEAD,
                    self._name,
                    self.id,
                    bill.id,
                    bill.amount_total,
                    values['vendor_total'],
                    delta_incl,
                    rounding,
                    tolerance,
                )
                return
            if float_is_zero(adjustment_line.quantity, precision_rounding=rounding):
                return

            tax_factor = 1.0
            if adjustment_line.tax_ids:
                tax_result = adjustment_line.tax_ids.compute_all(
                    1.0,
                    currency=bill.currency_id,
                    quantity=1.0,
                    product=adjustment_line.product_id,
                    partner=bill.partner_id,
                )
                tax_factor = tax_result['total_included'] or 1.0

            unit_delta = delta_incl / tax_factor / adjustment_line.quantity
            _logger.info(
                '%s payable_rounding_adjustment wizard_model=%s wizard_id=%s bill_id=%s '
                'attempt=%s current_total=%s vendor_total=%s delta_incl=%s '
                'line_id=%s old_unit=%s unit_delta=%s',
                ALLOCATION_LOG_HEAD,
                self._name,
                self.id,
                bill.id,
                attempt + 1,
                bill.amount_total,
                values['vendor_total'],
                delta_incl,
                adjustment_line.id,
                adjustment_line.price_unit,
                unit_delta,
            )
            adjustment_line.with_context(check_move_validity=False).write({
                'price_unit': adjustment_line.price_unit + unit_delta,
            })
            if hasattr(adjustment_line, '_compute_vendor_final_unit_price_vat_incl'):
                adjustment_line._compute_vendor_final_unit_price_vat_incl()
            bill.invalidate_recordset()
            adjustment_line.invalidate_recordset()
            _logger.info(
                '%s payable_rounding_after wizard_model=%s wizard_id=%s bill_id=%s '
                'attempt=%s adjusted_line_id=%s new_unit=%s new_total=%s',
                ALLOCATION_LOG_HEAD,
                self._name,
                self.id,
                bill.id,
                attempt + 1,
                adjustment_line.id,
                adjustment_line.price_unit,
                bill.amount_total,
            )

    def _validate_invoice_final_total_allocation(self, bill):
        self.ensure_one()
        values = self._get_invoice_allocation_values()
        if not values['allocation_enabled']:
            return
        rounding = bill.currency_id.rounding or self.currency_id.rounding or 0.01
        tolerance = self._get_invoice_final_total_tolerance(bill)
        difference = bill.amount_total - values['vendor_total']
        comparison = float_compare(difference, 0.0, precision_rounding=rounding)
        _logger.info(
            '%s payable_validated wizard_model=%s wizard_id=%s bill_id=%s '
            'bill_total=%s vendor_total=%s difference=%s rounding=%s tolerance=%s '
            'comparison=%s',
            ALLOCATION_LOG_HEAD,
            self._name,
            self.id,
            bill.id,
            bill.amount_total,
            values['vendor_total'],
            difference,
            rounding,
            tolerance,
            comparison,
        )
        if comparison and abs(difference) > tolerance + 0.0000001:
            raise ValidationError(_(
                'Generated bill payable amount was not allocated to the Vendor Invoice Final Total.\n\n'
                'Generated Bill Total: %(generated).2f\n'
                'Vendor Invoice Final Total: %(vendor_total).2f\n'
                'Difference: %(difference).2f\n\n'
                'Review the wizard line values before creating the bill.',
                generated=bill.amount_total,
                vendor_total=values['vendor_total'],
                difference=difference,
            ))

    def _check_invoice_variance_policy_for_bill(self, bill):
        self.ensure_one()
        values = self._get_variance_policy_values(calculated_total=bill.amount_total)
        _logger.info(
            '%s bill_check wizard_model=%s wizard_id=%s bill_id=%s vendor_id=%s '
            'bill_total=%s vendor_total=%s variance=%s abs_variance=%s allowed=%s '
            'block=%s dismissed=%s required=%s',
            VARIANCE_LOG_HEAD,
            self._name,
            self.id,
            bill.id,
            values['vendor'].id if values['vendor'] else False,
            values['calculated_total'],
            values['vendor_total'],
            values['variance'],
            values['abs_variance'],
            values['allowed'],
            values['block'],
            self.variance_warning_dismiss_count,
            values['required'],
        )
        if values['requires_ack'] and not values['acknowledged']:
            _logger.warning(
                '%s bill_blocked wizard_model=%s wizard_id=%s bill_id=%s vendor_id=%s '
                'bill_total=%s vendor_total=%s variance=%s allowed=%s dismissed=%s required=%s',
                VARIANCE_LOG_HEAD,
                self._name,
                self.id,
                bill.id,
                values['vendor'].id if values['vendor'] else False,
                values['calculated_total'],
                values['vendor_total'],
                values['variance'],
                values['allowed'],
                self.variance_warning_dismiss_count,
                values['required'],
            )
            raise ValidationError(_(
                'Generated bill total still exceeds this vendor allowed invoice variance.\n\n'
                'Bill Total: %(bill_total).2f\n'
                'Vendor Invoice Total: %(vendor_total).2f\n'
                'Variance: %(variance).2f\n'
                'Allowed Variance: %(allowed).2f\n\n'
                'Dismiss this warning %(remaining)s more time(s) before creating the bill.',
                bill_total=values['calculated_total'],
                vendor_total=values['vendor_total'],
                variance=values['variance'],
                allowed=values['allowed'],
                remaining=max(values['required'] - self.variance_warning_dismiss_count, 0),
            ))

    def _prepare_invoice_variance_audit_line_snapshot(self):
        self.ensure_one()
        line_values = []
        for line in self.line_ids:
            line_values.append({
                'product': line.product_id.display_name if line.product_id else False,
                'purchase_order': line.purchase_id.name if 'purchase_id' in line._fields and line.purchase_id else False,
                'quantity': line.product_qty,
                'vendor_list_unit_price': getattr(line, 'vendor_price', 0.0),
                'vendor_line_total': getattr(line, 'vendor_line_total', 0.0),
                'discount_percentage': getattr(line, 'applied_discount', 0.0),
                'freight_percentage': getattr(line, 'applied_freight', 0.0),
                'tint_type': getattr(line, 'gamma_tint_type', False),
                'tint_percentage': getattr(line, 'gamma_tint_percentage', 0.0),
                'computed_unit_excl_vat': line._get_effective_bill_unit_price() if hasattr(line, '_get_effective_bill_unit_price') else 0.0,
                'computed_unit_vat_incl': getattr(line, 'final_unit_price_incl_vat', 0.0) or getattr(line, 'unit_price_vat_incl', 0.0),
                'computed_line_total_vat_incl': getattr(line, 'final_line_total_vat_incl', 0.0) or getattr(line, 'line_total_vat_incl', 0.0),
                'promised_cost_vat_incl': getattr(line, 'vendor_promised_cost_vat_incl', 0.0),
                'promised_cost_difference_vat_incl': getattr(line, 'promised_cost_difference_vat_incl', 0.0),
            })
        return line_values

    def _log_invoice_variance_audit(self, bill):
        self.ensure_one()
        values = self._get_variance_policy_values()
        if not values['vendor_total'] or not values['abs_variance']:
            _logger.info(
                '%s audit_skip wizard_model=%s wizard_id=%s bill_id=%s reason=no_variance',
                VARIANCE_LOG_HEAD,
                self._name,
                self.id,
                bill.id,
            )
            return self.env['vendor.bill.invoice.variance.audit']

        purchases = self._get_variance_policy_purchase_ids()
        audit = self.env['vendor.bill.invoice.variance.audit'].create({
            'name': _('Invoice Variance Audit - %s') % (bill.display_name or bill.name or bill.id),
            'bill_id': bill.id,
            'vendor_id': values['vendor'].id if values['vendor'] else False,
            'company_id': bill.company_id.id,
            'currency_id': bill.currency_id.id,
            'purchase_id': purchases[:1].id if len(purchases) == 1 else False,
            'purchase_ids': [(6, 0, purchases.ids)],
            'wizard_model': self._name,
            'wizard_id': self.id,
            'vendor_invoice_profile': self._get_variance_policy_profile(),
            'calculated_total_vat_incl': values['calculated_total'],
            'vendor_invoice_final_total': values['vendor_total'],
            'variance_amount': values['variance'],
            'absolute_variance_amount': values['abs_variance'],
            'allowed_variance_amount': values['allowed'],
            'block_above_allowed': values['block'],
            'exceeded_allowed_amount': values['exceeds'],
            'dismiss_clicks_required': values['required'],
            'dismiss_clicks_done': self.variance_warning_dismiss_count,
            'created_by_id': self.env.user.id,
            'wizard_snapshot_json': {
                'wizard_model': self._name,
                'wizard_id': self.id,
                'profile': self._get_variance_policy_profile(),
                'calculated_total': values['calculated_total'],
                'vendor_total': values['vendor_total'],
                'variance': values['variance'],
                'allowed': values['allowed'],
            },
            'line_snapshot_json': self._prepare_invoice_variance_audit_line_snapshot(),
        })
        _logger.warning(
            '%s audit_created audit_id=%s bill_id=%s wizard_model=%s wizard_id=%s vendor_id=%s '
            'variance=%s allowed=%s exceeded=%s dismissed=%s required=%s user_id=%s',
            VARIANCE_LOG_HEAD,
            audit.id,
            bill.id,
            self._name,
            self.id,
            values['vendor'].id if values['vendor'] else False,
            values['variance'],
            values['allowed'],
            values['exceeds'],
            self.variance_warning_dismiss_count,
            values['required'],
            self.env.user.id,
        )
        return audit
