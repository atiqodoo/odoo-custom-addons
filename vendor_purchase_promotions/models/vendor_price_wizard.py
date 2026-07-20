import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare

from .res_partner import VENDOR_PROFILE_GAMMA


_logger = logging.getLogger(__name__)


class VendorPriceWizard(models.TransientModel):
    _inherit = 'vendor.price.wizard'

    vendor_invoice_profile = fields.Selection(
        selection_add=[(VENDOR_PROFILE_GAMMA, 'Gamma Paints Invoice')],
        ondelete={VENDOR_PROFILE_GAMMA: 'cascade'},
    )
    is_gamma_profile = fields.Boolean(
        compute='_compute_is_gamma_profile',
    )
    gamma_vendor_invoice_final_total = fields.Monetary(
        string='Gamma Invoice Final Total (VAT Incl.)',
        currency_field='currency_id',
    )
    gamma_invoice_difference = fields.Monetary(
        string='Gamma Invoice Difference',
        compute='_compute_gamma_invoice_summary',
        currency_field='currency_id',
    )
    gamma_invoice_status = fields.Char(
        compute='_compute_gamma_invoice_summary',
    )
    gamma_promotion_application_ids = fields.Many2many(
        'vendor.purchase.promotion.application',
        compute='_compute_gamma_promotion_applications',
        string='Promotion Commitments',
    )
    gamma_promised_foc_qty = fields.Float(
        compute='_compute_gamma_promotion_applications',
    )
    gamma_received_foc_qty = fields.Float(
        compute='_compute_gamma_promotion_applications',
    )
    gamma_outstanding_foc_qty = fields.Float(
        compute='_compute_gamma_promotion_applications',
    )

    @api.depends('vendor_invoice_profile')
    def _compute_is_gamma_profile(self):
        for wizard in self:
            wizard.is_gamma_profile = wizard.vendor_invoice_profile == VENDOR_PROFILE_GAMMA

    @api.depends('invoice_total_vat_incl', 'gamma_vendor_invoice_final_total', 'is_gamma_profile')
    def _compute_gamma_invoice_summary(self):
        for wizard in self:
            if not wizard.is_gamma_profile:
                wizard.gamma_invoice_difference = 0.0
                wizard.gamma_invoice_status = _('Not a Gamma invoice')
                continue
            difference = (
                (wizard.invoice_total_vat_incl or 0.0)
                - (wizard.gamma_vendor_invoice_final_total or 0.0)
            )
            wizard.gamma_invoice_difference = difference
            if not wizard.gamma_vendor_invoice_final_total:
                wizard.gamma_invoice_status = _('Enter the Gamma invoice final total')
            elif abs(difference) <= (wizard.currency_id.rounding or 0.01):
                wizard.gamma_invoice_status = _('Invoice total matches')
            elif difference > 0:
                wizard.gamma_invoice_status = _('Calculated total is above the Gamma invoice')
            else:
                wizard.gamma_invoice_status = _('Calculated total is below the Gamma invoice')

    @api.depends(
        'purchase_id',
        'purchase_id.promotion_application_ids.promised_foc_qty',
        'purchase_id.promotion_application_ids.received_foc_qty',
        'purchase_id.promotion_application_ids.outstanding_foc_qty',
    )
    def _compute_gamma_promotion_applications(self):
        for wizard in self:
            applications = wizard.purchase_id.promotion_application_ids
            wizard.gamma_promotion_application_ids = applications
            wizard.gamma_promised_foc_qty = sum(applications.mapped('promised_foc_qty'))
            wizard.gamma_received_foc_qty = sum(applications.mapped('received_foc_qty'))
            wizard.gamma_outstanding_foc_qty = sum(applications.mapped('outstanding_foc_qty'))

    def _validate_invoice_profile_inputs(self):
        super()._validate_invoice_profile_inputs()
        if not self.is_gamma_profile:
            return
        if self.gamma_vendor_invoice_final_total <= 0:
            raise ValidationError(_('Gamma Invoice Final Total must be greater than zero.'))
        comparison = float_compare(
            self.invoice_total_vat_incl,
            self.gamma_vendor_invoice_final_total,
            precision_rounding=self.currency_id.rounding or 0.01,
        )
        if comparison:
            raise ValidationError(_(
                'Calculated Gamma total (%(calculated).2f) does not match the printed invoice total '
                '(%(vendor).2f). Correct the invoice price, discount, tint charge, taxes, or quantity.'
            ) % {
                'calculated': self.invoice_total_vat_incl,
                'vendor': self.gamma_vendor_invoice_final_total,
            })
        _logger.info(
            '[VPP_GAMMA_BILL] validation wizard_id=%s po_id=%s total=%s promised_foc=%s '
            'received_foc=%s outstanding_foc=%s',
            self.id,
            self.purchase_id.id,
            self.invoice_total_vat_incl,
            self.gamma_promised_foc_qty,
            self.gamma_received_foc_qty,
            self.gamma_outstanding_foc_qty,
        )

    def _prepare_profile_bill_vals(self):
        values = super()._prepare_profile_bill_vals()
        if self.is_gamma_profile:
            applications = self.gamma_promotion_application_ids
            all_foc_received = bool(applications) and not any(
                application.outstanding_foc_qty > 0 for application in applications
            )
            values.update({
                'vendor_invoice_profile': VENDOR_PROFILE_GAMMA,
                'gamma_vendor_calculated_total_vat_incl': self.invoice_total_vat_incl,
                'gamma_vendor_invoice_final_total': self.gamma_vendor_invoice_final_total,
                'promotion_application_ids': [(6, 0, applications.ids)],
                'promotion_release_state': (
                    'released' if all_foc_received
                    else 'hold' if applications
                    else 'not_required'
                ),
                'promotion_release_reason': (
                    _('Automatically released: every promised FOC unit was received.')
                    if all_foc_received else False
                ),
            })
        return values

    def _validate_profile_bill_result(self, bill):
        super()._validate_profile_bill_result(bill)
        if not self.is_gamma_profile:
            return
        comparison = float_compare(
            bill.amount_total,
            self.gamma_vendor_invoice_final_total,
            precision_rounding=self.currency_id.rounding or 0.01,
        )
        if comparison:
            raise ValidationError(_(
                'Generated bill total (%(generated).2f) does not match the Gamma invoice total '
                '(%(vendor).2f).'
            ) % {
                'generated': bill.amount_total,
                'vendor': self.gamma_vendor_invoice_final_total,
            })
        bill._sync_promotion_payment_hold()
        _logger.info(
            '[VPP_GAMMA_BILL] created wizard_id=%s bill_id=%s po_id=%s amount_total=%s '
            'application_ids=%s hold=%s',
            self.id,
            bill.id,
            self.purchase_id.id,
            bill.amount_total,
            bill.promotion_application_ids.ids,
            bill.promotion_payment_hold,
        )
