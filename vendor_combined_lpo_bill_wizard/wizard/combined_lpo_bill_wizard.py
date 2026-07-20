# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare

from odoo.addons.purchase_net_price_compute.models.vendor_invoice_profile import (
    VENDOR_INVOICE_PROFILE_CROWN,
)
from odoo.addons.vendor_purchase_promotions.models.res_partner import VENDOR_PROFILE_GAMMA

from ..services.bill_builder import CombinedLpoBillBuilder
from ..services.debug_payload import wizard_payload
from ..services.eligibility import CombinedLpoEligibilityService
from ..services.profile_adapter import CombinedLpoProfileAdapter, PROFILE_SELECTION


_logger = logging.getLogger(__name__)


class CombinedLpoBillWizard(models.TransientModel):
    _name = 'combined.lpo.bill.wizard'
    _description = 'Combined LPO Vendor Bill Wizard'

    partner_id = fields.Many2one('res.partner', string='Vendor', required=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, readonly=True)
    purchase_ids = fields.Many2many(
        'purchase.order',
        'combined_lpo_bill_wizard_purchase_rel',
        'wizard_id',
        'purchase_id',
        string='Source LPOs',
        required=True,
    )
    bill_id = fields.Many2one(
        'account.move',
        string='Draft Bill to Update',
        domain="[('move_type','=','in_invoice'), ('state','=','draft'), ('partner_id','=',partner_id)]",
    )
    vendor_invoice_profile = fields.Selection(
        selection=PROFILE_SELECTION,
        string='Invoice Calculation Profile',
        required=True,
        readonly=True,
    )
    is_crown_profile = fields.Boolean(compute='_compute_profile_flags')
    is_gamma_profile = fields.Boolean(compute='_compute_profile_flags')
    vendor_invoice_reference = fields.Char(string='Vendor Invoice Reference')
    invoice_date = fields.Date(
        string='Invoice Date',
        default=fields.Date.context_today,
        required=True,
    )
    vendor_invoice_final_total = fields.Monetary(
        string='Vendor Invoice Final Total (VAT Incl.)',
        currency_field='currency_id',
    )
    line_ids = fields.One2many(
        'combined.lpo.bill.wizard.line',
        'wizard_id',
        string='Bill Lines',
    )
    invoice_total_vat_incl = fields.Monetary(
        string='Calculated Total (VAT Incl.)',
        compute='_compute_totals',
        currency_field='currency_id',
    )
    invoice_variance_amount = fields.Monetary(
        string='Invoice Variance',
        compute='_compute_totals',
        currency_field='currency_id',
    )
    invoice_variance_percentage = fields.Float(
        string='Invoice Variance %',
        compute='_compute_totals',
    )
    invoice_allocation_ratio = fields.Float(
        string='Invoice Allocation Ratio',
        compute='_compute_totals',
        digits=(16, 10),
    )
    invoice_status = fields.Char(
        string='Invoice Status',
        compute='_compute_totals',
    )
    gamma_promotion_application_ids = fields.Many2many(
        'vendor.purchase.promotion.application',
        compute='_compute_gamma_promotion_totals',
        string='Promotion Commitments',
    )
    gamma_promised_foc_qty = fields.Float(compute='_compute_gamma_promotion_totals')
    gamma_received_foc_qty = fields.Float(compute='_compute_gamma_promotion_totals')
    gamma_outstanding_foc_qty = fields.Float(compute='_compute_gamma_promotion_totals')
    promised_cost_discrepancy_approved = fields.Boolean(
        string='Promised Cost Discrepancy Approved',
        readonly=True,
    )
    promised_cost_discrepancy_approved_by_id = fields.Many2one(
        'res.users',
        string='Promised Cost Approved By',
        readonly=True,
    )
    has_promised_cost_discrepancy = fields.Boolean(
        string='Has Promised Cost Discrepancy',
        compute='_compute_has_promised_cost_discrepancy',
    )

    @api.depends('vendor_invoice_profile')
    def _compute_profile_flags(self):
        for wizard in self:
            wizard.is_crown_profile = wizard.vendor_invoice_profile == VENDOR_INVOICE_PROFILE_CROWN
            wizard.is_gamma_profile = wizard.vendor_invoice_profile == VENDOR_PROFILE_GAMMA

    @api.depends(
        'line_ids.include_line',
        'line_ids.line_total_vat_incl',
        'vendor_invoice_final_total',
        'vendor_invoice_profile',
    )
    def _compute_totals(self):
        for wizard in self:
            included_lines = wizard.line_ids.filtered('include_line')
            calculated_total = sum(included_lines.mapped('line_total_vat_incl'))
            wizard.invoice_total_vat_incl = calculated_total
            if wizard.vendor_invoice_final_total:
                variance = calculated_total - wizard.vendor_invoice_final_total
                ratio = (
                    wizard.vendor_invoice_final_total / calculated_total
                    if calculated_total else 1.0
                )
                variance_pct = variance / calculated_total * 100.0 if calculated_total else 0.0
            else:
                variance = 0.0
                ratio = 1.0
                variance_pct = 0.0
            wizard.invoice_variance_amount = variance
            wizard.invoice_variance_percentage = variance_pct
            wizard.invoice_allocation_ratio = ratio

            if not wizard.vendor_invoice_final_total:
                wizard.invoice_status = _('Enter the vendor invoice final total')
            else:
                comparison = float_compare(
                    calculated_total,
                    wizard.vendor_invoice_final_total,
                    precision_rounding=wizard.currency_id.rounding or 0.01,
                )
                if comparison == 0:
                    wizard.invoice_status = _('Invoice total matches')
                elif comparison > 0:
                    wizard.invoice_status = _('Calculated total is above the vendor invoice')
                else:
                    wizard.invoice_status = _('Calculated total is below the vendor invoice')

    @api.depends(
        'purchase_ids',
        'purchase_ids.promotion_application_ids.promised_foc_qty',
        'purchase_ids.promotion_application_ids.received_foc_qty',
        'purchase_ids.promotion_application_ids.outstanding_foc_qty',
    )
    def _compute_gamma_promotion_totals(self):
        for wizard in self:
            applications = wizard.purchase_ids.mapped('promotion_application_ids')
            wizard.gamma_promotion_application_ids = applications
            wizard.gamma_promised_foc_qty = sum(applications.mapped('promised_foc_qty'))
            wizard.gamma_received_foc_qty = sum(applications.mapped('received_foc_qty'))
            wizard.gamma_outstanding_foc_qty = sum(applications.mapped('outstanding_foc_qty'))

    @api.depends(
        'line_ids.include_line',
        'line_ids.vendor_promised_cost_vat_incl',
        'line_ids.unit_price_vat_incl',
        'line_ids.promised_cost_difference_vat_incl',
    )
    def _compute_has_promised_cost_discrepancy(self):
        for wizard in self:
            wizard.has_promised_cost_discrepancy = bool(wizard._get_promised_cost_discrepancy_lines())

    def _profile_adapter(self):
        self.ensure_one()
        return CombinedLpoProfileAdapter(self)

    def _debug_payload(self):
        self.ensure_one()
        return wizard_payload(self)

    def _get_invoice_origin_text(self):
        self.ensure_one()
        return ', '.join(self.purchase_ids.sorted('name').mapped('name'))

    def _format_debug_summary(self):
        self.ensure_one()
        lines = [
            'Combined LPO Bill Wizard',
            'Wizard ID: %s' % self.id,
            'Vendor: %s (%s)' % (self.partner_id.display_name, self.partner_id.id),
            'Profile: %s' % self.vendor_invoice_profile,
            'LPOs: %s' % self._get_invoice_origin_text(),
            'Line Count: %s' % len(self.line_ids.filtered('include_line')),
            'Calculated Total: %s' % self.invoice_total_vat_incl,
            'Vendor Final Total: %s' % self.vendor_invoice_final_total,
            'Variance: %s' % self.invoice_variance_amount,
            'FOC Outstanding: %s' % self.gamma_outstanding_foc_qty,
        ]
        return '\n'.join(lines)

    def action_reload_lines(self):
        self.ensure_one()
        _logger.info('[CLPO_AUTOCOMPLETE] reload_start payload=%s', self._debug_payload())
        self.line_ids.unlink()
        commands = []
        eligibility = CombinedLpoEligibilityService(self.env)
        for purchase_line, qty in eligibility.iter_eligible_purchase_lines(self.purchase_ids):
            values = self._prepare_wizard_line_vals(purchase_line, qty)
            commands.append((0, 0, values))
            _logger.info(
                '[CLPO_AUTOCOMPLETE] line_added wizard_id=%s purchase_line_id=%s po=%s '
                'product_id=%s qty=%s',
                self.id,
                purchase_line.id,
                purchase_line.order_id.name,
                purchase_line.product_id.id,
                qty,
            )
        if not commands:
            _logger.warning(
                '[CLPO_AUTOCOMPLETE] no_lines wizard_id=%s purchase_ids=%s',
                self.id,
                self.purchase_ids.ids,
            )
            raise ValidationError(_('No received uninvoiced payable lines were found for the selected LPOs.'))
        self.write({'line_ids': commands})
        _logger.info(
            '[CLPO_AUTOCOMPLETE] reload_complete wizard_id=%s line_count=%s',
            self.id,
            len(commands),
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'combined.lpo.bill.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def _prepare_wizard_line_vals(self, purchase_line, qty):
        self.ensure_one()
        profile = self.vendor_invoice_profile
        vendor_price = False
        applied_discount = purchase_line.applied_discount or 0.0
        applied_freight = purchase_line.applied_freight or 0.0
        gamma_tint_type = 'not_tinted'
        gamma_tint_percentage = 0.0

        if profile == VENDOR_PROFILE_GAMMA:
            vendor_price = purchase_line.gamma_list_unit_price or purchase_line.price_unit
            applied_discount = purchase_line.gamma_discount_percentage or 0.0
            applied_freight = 0.0
            gamma_tint_type = purchase_line.gamma_tint_type or 'not_tinted'
            gamma_tint_percentage = purchase_line.gamma_tint_percentage or 0.0

        return {
            'purchase_id': purchase_line.order_id.id,
            'purchase_line_id': purchase_line.id,
            'product_id': purchase_line.product_id.id,
            'product_qty': qty,
            'max_billable_qty': qty,
            'product_uom_id': purchase_line.product_uom.id,
            'po_unit_price': purchase_line.price_unit,
            'vendor_price': vendor_price,
            'applied_discount': applied_discount,
            'applied_freight': applied_freight,
            'gamma_tint_type': gamma_tint_type,
            'gamma_tint_percentage': gamma_tint_percentage,
            'currency_id': self.currency_id.id,
        }

    def _validate_source_scope(self):
        self.ensure_one()
        if len(self.purchase_ids.mapped('partner_id.commercial_partner_id')) != 1:
            raise ValidationError(_('All selected LPOs must belong to the same vendor.'))
        if len(self.purchase_ids.mapped('company_id')) != 1:
            raise ValidationError(_('All selected LPOs must belong to the same company.'))
        if len(self.purchase_ids.mapped('currency_id')) != 1:
            raise ValidationError(_('All selected LPOs must use the same currency.'))
        profiles = {order.partner_id.get_vendor_invoice_profile() for order in self.purchase_ids}
        if profiles != {self.vendor_invoice_profile}:
            raise ValidationError(_('Selected LPO vendor profiles changed. Reload the combined bill wizard.'))
        not_billable = self.purchase_ids.filtered(lambda order: not order.has_combined_lpo_billable_qty)
        if not_billable:
            _logger.warning(
                '[CLPO_VALIDATE] blocked reason=no_billable_qty wizard_id=%s purchase_ids=%s names=%s',
                self.id,
                not_billable.ids,
                not_billable.mapped('name'),
            )
            raise ValidationError(_(
                'Remove these already fully billed/no-quantity LPOs before continuing: %s'
            ) % ', '.join(not_billable.mapped('name')))

    def _get_price_discrepancy_approver(self):
        approver_id = self.env['ir.config_parameter'].sudo().get_param(
            'vendor_price_check.price_check_approver_id',
            default=False,
        )
        return self.env['res.users'].browse(int(approver_id)) if approver_id else self.env['res.users']

    def _get_promised_cost_discrepancy_lines(self):
        self.ensure_one()
        precision = self.currency_id.rounding if self.currency_id else 0.01
        lines = self.line_ids.filtered(
            lambda line: (
                line.include_line
                and line.vendor_promised_cost_vat_incl
                and abs(line.promised_cost_difference_vat_incl) > precision
            )
        )
        _logger.info(
            '[CLPO_PROMISE] discrepancy_scan wizard_id=%s line_ids=%s precision=%s',
            self.id,
            lines.ids,
            precision,
        )
        return lines

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
        discrepancy_lines = self._get_promised_cost_discrepancy_lines()
        if not discrepancy_lines:
            raise ValidationError(_('There are no promised cost discrepancies to approve.'))

        self.write({
            'promised_cost_discrepancy_approved': True,
            'promised_cost_discrepancy_approved_by_id': self.env.user.id,
        })
        _logger.info(
            '[CLPO_PROMISE] approved wizard_id=%s purchase_ids=%s approver_id=%s line_ids=%s',
            self.id,
            self.purchase_ids.ids,
            self.env.user.id,
            discrepancy_lines.ids,
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'combined.lpo.bill.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def _check_promised_cost_discrepancies(self):
        self.ensure_one()
        discrepancy_lines = self._get_promised_cost_discrepancy_lines()
        if not discrepancy_lines or self.promised_cost_discrepancy_approved:
            return

        approver = self._get_price_discrepancy_approver()
        details = '\n'.join(
            _('- %(po)s / %(product)s: promised %(promised).2f, unit + VAT %(actual).2f, difference %(difference).2f')
            % {
                'po': line.purchase_id.name,
                'product': line.product_id.display_name,
                'promised': line.vendor_promised_cost_vat_incl,
                'actual': line.unit_price_vat_incl,
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
            '[CLPO_PROMISE] approval_required wizard_id=%s purchase_ids=%s line_ids=%s',
            self.id,
            self.purchase_ids.ids,
            discrepancy_lines.ids,
        )
        raise ValidationError(
            _('Vendor promised cost discrepancy detected. Approval is required before creating the combined bill.\n\n'
              '%(details)s\n\n%(approver_message)s')
            % {'details': details, 'approver_message': approver_message}
        )

    def _check_duplicate_vendor_reference(self):
        self.ensure_one()
        if not self.vendor_invoice_reference:
            return
        domain = [
            ('move_type', '=', 'in_invoice'),
            ('partner_id', '=', self.partner_id.id),
            ('ref', '=', self.vendor_invoice_reference),
            ('state', '!=', 'cancel'),
        ]
        if self.bill_id:
            domain.append(('id', '!=', self.bill_id.id))
        existing = self.env['account.move'].search(domain, limit=1)
        if existing:
            _logger.warning(
                '[CLPO_VALIDATE] blocked reason=duplicate_vendor_reference wizard_id=%s '
                'ref=%s existing_bill_id=%s',
                self.id,
                self.vendor_invoice_reference,
                existing.id,
            )
            raise ValidationError(_(
                'Vendor invoice reference %(reference)s already exists on bill %(bill)s.'
            ) % {
                'reference': self.vendor_invoice_reference,
                'bill': existing.display_name,
            })

    def _validate_created_bill(self, bill):
        self.ensure_one()
        comparison = float_compare(
            bill.amount_total,
            self.vendor_invoice_final_total,
            precision_rounding=self.currency_id.rounding or 0.01,
        )
        _logger.info(
            '[CLPO_VALIDATE] generated_bill_total wizard_id=%s bill_id=%s generated=%s '
            'vendor_total=%s comparison=%s',
            self.id,
            bill.id,
            bill.amount_total,
            self.vendor_invoice_final_total,
            comparison,
        )
        if comparison:
            raise ValidationError(_(
                'Generated bill total (%(generated).2f) does not match the vendor invoice '
                'final total (%(vendor).2f).'
            ) % {
                'generated': bill.amount_total,
                'vendor': self.vendor_invoice_final_total,
            })

    def action_create_bill(self):
        self.ensure_one()
        _logger.info('[CLPO_VALIDATE] create_start payload=%s', self._debug_payload())
        try:
            self._validate_source_scope()
            self._check_duplicate_vendor_reference()
            self._profile_adapter().validate_wizard()
            self._check_promised_cost_discrepancies()
            bill = CombinedLpoBillBuilder(self).create_or_update_bill()
        except Exception:
            _logger.exception(
                '[CLPO_ERROR] create_bill_failed wizard_id=%s vendor_id=%s purchase_ids=%s',
                self.id,
                self.partner_id.id,
                self.purchase_ids.ids,
            )
            raise
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': bill.id,
            'target': 'current',
        }
