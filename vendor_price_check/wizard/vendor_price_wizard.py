# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_is_zero


_logger = logging.getLogger(__name__)


class VendorPriceWizard(models.TransientModel):
    _name = 'vendor.price.wizard'
    _inherit = ['vendor.bill.wizard.display.mixin', 'vendor.bill.variance.policy.mixin']
    _description = 'Vendor Price Wizard'

    purchase_id = fields.Many2one('purchase.order', string='Purchase Order', required=True)
    bill_id = fields.Many2one('account.move', string='Vendor Bill')
    line_ids = fields.One2many('vendor.price.wizard.line', 'wizard_id', string='Lines')
    currency_id = fields.Many2one(
        'res.currency',
        related='purchase_id.currency_id',
        readonly=True,
    )
    invoice_total_vat_incl = fields.Monetary(
        string='Invoice Total (VAT Incl.)',
        compute='_compute_invoice_total_vat_incl',
        currency_field='currency_id',
    )
    vendor_invoice_final_total = fields.Monetary(
        string='Vendor Invoice Final Total (VAT Incl.)',
        currency_field='currency_id',
        help='Enter the total amount printed on the vendor invoice, including VAT.',
    )
    promised_cost_discrepancy_approved = fields.Boolean(
        string='Promised Cost Discrepancy Approved',
        readonly=True,
    )
    promised_cost_discrepancy_approved_by_id = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
    )
    has_promised_cost_discrepancy = fields.Boolean(
        string='Has Promised Cost Discrepancy',
        compute='_compute_has_promised_cost_discrepancy',
    )

    # Extension hooks keep profile-specific calculation code out of this core flow.
    def _validate_invoice_profile_inputs(self):
        self.ensure_one()
        self._validate_required_vendor_invoice_final_total()

    def _prepare_profile_bill_vals(self):
        self.ensure_one()
        values = self._get_variance_policy_values()
        return {
            'vendor_invoice_profile': self._get_variance_policy_profile(),
            'vendor_calculated_total_vat_incl': values['calculated_total'],
            'vendor_invoice_final_total': values['vendor_total'],
            'vendor_invoice_variance_amount': values['variance'],
            'vendor_invoice_variance_percentage': (
                values['variance'] / values['calculated_total'] * 100.0
                if values['calculated_total']
                else 0.0
            ),
        }

    def _validate_profile_bill_result(self, bill):
        self.ensure_one()

    @api.depends('line_ids.line_total_vat_incl')
    def _compute_invoice_total_vat_incl(self):
        for wizard in self:
            wizard.invoice_total_vat_incl = sum(wizard.line_ids.mapped('line_total_vat_incl'))

    @api.depends(
        'line_ids.vendor_promised_cost_vat_incl',
        'line_ids.unit_price_vat_incl',
        'line_ids.promised_cost_difference_vat_incl',
    )
    def _compute_has_promised_cost_discrepancy(self):
        for wizard in self:
            wizard.has_promised_cost_discrepancy = bool(wizard._get_promised_cost_discrepancy_lines())

    def _get_price_discrepancy_approver(self):
        approver_id = self.env['ir.config_parameter'].sudo().get_param(
            'vendor_price_check.price_check_approver_id',
            default=False,
        )
        return self.env['res.users'].browse(int(approver_id)) if approver_id else self.env['res.users']

    def _get_promised_cost_discrepancy_lines(self):
        self.ensure_one()
        precision = self.currency_id.rounding if self.currency_id else 0.01
        return self.line_ids.filtered(
            lambda line: (
                line.vendor_promised_cost_vat_incl
                and abs(line.promised_cost_difference_vat_incl) > precision
            )
        )

    def action_approve_promised_cost_discrepancy(self):
        self.ensure_one()
        approver = self._get_price_discrepancy_approver()
        if not approver:
            raise ValidationError(_(
                'Please configure a Price Discrepancy Approver in Purchase settings before approving.'
            ))
        if self.env.user != approver:
            raise ValidationError(
                _('Only %(approver)s can approve promised cost discrepancies.')
                % {'approver': approver.display_name}
            )
        if not self._get_promised_cost_discrepancy_lines():
            raise ValidationError(_('There are no promised cost discrepancies to approve.'))

        self.write({
            'promised_cost_discrepancy_approved': True,
            'promised_cost_discrepancy_approved_by_id': self.env.user.id,
        })
        _logger.info(
            '[VPC_PROMISE] approved wizard_id=%s po_id=%s approver_id=%s',
            self.id,
            self.purchase_id.id,
            self.env.user.id,
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'vendor.price.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': {'dialog_size': 'extra-large'},
        }

    def _check_promised_cost_discrepancies(self):
        self.ensure_one()
        discrepancy_lines = self._get_promised_cost_discrepancy_lines()
        if not discrepancy_lines or self.promised_cost_discrepancy_approved:
            return

        approver = self._get_price_discrepancy_approver()
        details = '\n'.join(
            _('- %(product)s: promised %(promised).2f, unit + VAT %(actual).2f, difference %(difference).2f')
            % {
                'product': line.product_id.display_name,
                'promised': line.vendor_promised_cost_vat_incl,
                'actual': line._get_promised_comparison_unit_vat_incl(),
                'difference': line.promised_cost_difference_vat_incl,
            }
            for line in discrepancy_lines
        )
        approver_message = (
            _('Configured approver: %s') % approver.display_name
            if approver
            else _('No Price Discrepancy Approver is configured in Purchase settings.')
        )
        _logger.warning(
            '[VPC_PROMISE] approval_required wizard_id=%s po_id=%s line_ids=%s',
            self.id,
            self.purchase_id.id,
            discrepancy_lines.ids,
        )
        raise ValidationError(
            _('Vendor promised cost discrepancy detected. Approval is required before creating the bill.\n\n'
              '%(details)s\n\n%(approver_message)s')
            % {'details': details, 'approver_message': approver_message}
        )

    def _get_billable_received_qty(self, purchase_line):
        received_to_bill = max(
            (purchase_line.qty_received or 0.0) - (purchase_line.qty_invoiced or 0.0),
            0.0,
        )
        rounding = purchase_line.product_uom.rounding if purchase_line.product_uom else 0.01
        return 0.0 if float_is_zero(received_to_bill, precision_rounding=rounding) else received_to_bill

    def action_create_bill(self):
        self.ensure_one()
        _logger.info(
            '[VPC_WIZARD] bill_create_start wizard_id=%s po_id=%s po=%s vendor_id=%s lines=%s',
            self.id,
            self.purchase_id.id,
            self.purchase_id.name,
            self.purchase_id.partner_id.id,
            len(self.line_ids),
        )

        for line in self.line_ids:
            _logger.debug(
                '[VPC_WIZARD] line_validate wizard_line_id=%s purchase_line_id=%s product_id=%s '
                'vendor_price=%s calculated_subtotal=%s',
                line.id,
                line.purchase_line_id.id,
                line.product_id.id,
                line.vendor_price,
                line.calculated_subtotal,
            )
            line._validate_for_bill()

        self._validate_invoice_profile_inputs()
        self._check_invoice_variance_policy()
        self._check_promised_cost_discrepancies()

        profile_bill_vals = self._prepare_profile_bill_vals()
        bill_vals = {
            'move_type': 'in_invoice',
            'partner_id': self.purchase_id.partner_id.id,
            'purchase_id': self.purchase_id.id,
            'invoice_origin': self.purchase_id.name,
            'currency_id': self.purchase_id.currency_id.id,
            'invoice_line_ids': [],
            **profile_bill_vals,
        }

        valid_lines = self.line_ids.filtered(lambda line: line.product_id and line.purchase_line_id)
        wizard_vendor_prices = {
            line.product_id.id: line._get_effective_bill_unit_price()
            for line in valid_lines
        }
        wizard_vendor_prices_by_purchase_line = {
            line.purchase_line_id.id: line._get_effective_bill_unit_price()
            for line in valid_lines
        }

        for line in valid_lines:
            billable_qty = self._get_billable_received_qty(line.purchase_line_id)
            if not billable_qty:
                _logger.info(
                    '[VPC_WIZARD] line_skipped_no_qty purchase_line_id=%s product_id=%s '
                    'received=%s invoiced=%s',
                    line.purchase_line_id.id,
                    line.product_id.id,
                    line.purchase_line_id.qty_received,
                    line.purchase_line_id.qty_invoiced,
                )
                continue

            price_unit = line._get_effective_bill_unit_price()
            _logger.info(
                '[VPC_WIZARD] bill_line_prepare wizard_line_id=%s purchase_line_id=%s product_id=%s '
                'qty=%s vendor_price=%s bill_unit_excl_vat=%s custom_pricing=%s',
                line.id,
                line.purchase_line_id.id,
                line.product_id.id,
                billable_qty,
                line.vendor_price,
                price_unit,
                line.use_custom_pricing,
            )
            bill_line_vals = {
                'product_id': line.product_id.id,
                'quantity': billable_qty,
                'product_uom_id': line.purchase_line_id.product_uom.id,
                'price_unit': price_unit,
                'tax_ids': [(6, 0, line.purchase_line_id.taxes_id.ids)],
                'purchase_line_id': line.purchase_line_id.id,
                'use_custom_pricing': line.use_custom_pricing,
                'net_price': price_unit,
                'applied_discount': line._get_effective_bill_discount(),
                'applied_freight': line.applied_freight,
                'vpc_from_vendor_price_wizard': True,
                **line._prepare_profile_bill_line_vals(),
            }
            bill_vals['invoice_line_ids'].append((0, 0, bill_line_vals))

        if not bill_vals['invoice_line_ids']:
            raise ValidationError(_(
                'There are no validated received quantities left to invoice for this purchase order.'
            ))

        context = {
            'wizard_vendor_prices': wizard_vendor_prices,
            'wizard_vendor_prices_by_purchase_line': wizard_vendor_prices_by_purchase_line,
        }
        if self.bill_id:
            _logger.info(
                '[VPC_WIZARD] updating_bill wizard_id=%s bill_id=%s',
                self.id,
                self.bill_id.id,
            )
            self.bill_id.with_context(**context).write({
                'invoice_line_ids': [(5, 0, 0)] + bill_vals['invoice_line_ids'],
                **profile_bill_vals,
            })
            bill = self.bill_id
        else:
            _logger.info('[VPC_WIZARD] creating_new_bill wizard_id=%s', self.id)
            bill = self.env['account.move'].with_context(**context).create(bill_vals)

        self._apply_invoice_final_total_rounding(bill)
        self._validate_profile_bill_result(bill)
        self._validate_invoice_final_total_allocation(bill)
        self._check_invoice_variance_policy_for_bill(bill)
        self._log_invoice_variance_audit(bill)
        discrepancies = bill._check_vendor_bill_prices()
        if discrepancies:
            _logger.warning(
                '[VPC_WIZARD] historical_discrepancies bill_id=%s count=%s',
                bill.id,
                len(discrepancies),
            )
        else:
            _logger.info(
                '[VPC_WIZARD] bill_create_complete wizard_id=%s bill_id=%s amount_total=%s',
                self.id,
                bill.id,
                bill.amount_total,
            )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': bill.id,
            'target': 'current',
        }
