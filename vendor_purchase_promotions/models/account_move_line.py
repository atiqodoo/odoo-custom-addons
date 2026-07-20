import logging

from odoo import fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    gamma_invoice_list_unit_price = fields.Monetary(
        string='Gamma List Unit Price',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    gamma_invoice_discount_percentage = fields.Float(
        string='Gamma Discount %',
        readonly=True,
        copy=False,
    )
    gamma_invoice_tint_type = fields.Selection(
        [
            ('not_tinted', 'Not Tinted'),
            ('factory', 'Factory'),
            ('showroom_branch', 'Showroom/Branch'),
            ('custom', 'Custom'),
        ],
        string='Gamma Tinting',
        readonly=True,
        copy=False,
    )
    gamma_invoice_tint_percentage = fields.Float(
        string='Gamma Tint %',
        readonly=True,
        copy=False,
    )
    gamma_invoice_gross_total = fields.Monetary(
        string='Gamma Gross',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    gamma_invoice_discount_amount = fields.Monetary(
        string='Gamma Discount Amount',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    gamma_invoice_tint_charge = fields.Monetary(
        string='Gamma Tint Charge',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    gamma_invoice_subtotal_excl_vat = fields.Monetary(
        string='Gamma Subtotal Excl. VAT',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )

    def reconcile(self):
        held_payable_lines = self.filtered(
            lambda line: line.account_id.account_type == 'liability_payable'
            and line.move_id.promotion_payment_hold
        )
        if held_payable_lines and not self.env.context.get('skip_vendor_promotion_hold'):
            bills = held_payable_lines.move_id
            _logger.warning(
                '[VPP_PAYMENT] reconciliation_blocked bill_ids=%s line_ids=%s user_id=%s',
                bills.ids,
                held_payable_lines.ids,
                self.env.user.id,
            )
            raise ValidationError(_(
                'Payment/reconciliation is blocked for vendor bill(s): %(bills)s. '
                'Complete or formally waive the outstanding FOC promotion first.'
            ) % {'bills': ', '.join(bills.mapped('display_name'))})
        return super().reconcile()

