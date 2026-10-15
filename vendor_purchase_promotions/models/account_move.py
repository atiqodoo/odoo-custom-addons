import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from .res_partner import VENDOR_PROFILE_GAMMA


_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    vendor_invoice_profile = fields.Selection(
        selection_add=[(VENDOR_PROFILE_GAMMA, 'Gamma Paints Invoice')],
        ondelete={VENDOR_PROFILE_GAMMA: 'set default'},
    )
    gamma_vendor_calculated_total_vat_incl = fields.Monetary(
        string='Gamma Calculated Total (VAT Incl.)',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    gamma_vendor_invoice_final_total = fields.Monetary(
        string='Gamma Invoice Final Total',
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    promotion_application_ids = fields.Many2many(
        'vendor.purchase.promotion.application',
        'vendor_promotion_application_bill_rel',
        'bill_id',
        'application_id',
        string='Promotion Commitments',
        copy=False,
        readonly=True,
    )
    promotion_release_state = fields.Selection(
        [
            ('not_required', 'Not Required'),
            ('hold', 'On Hold'),
            ('released', 'Released After Fulfilment'),
            ('waived', 'Released by Waiver'),
        ],
        default='not_required',
        required=True,
        copy=False,
        index=True,
    )
    promotion_payment_hold = fields.Boolean(
        string='Promotion Payment Hold',
        compute='_compute_promotion_payment_hold',
        store=True,
        copy=False,
    )
    promotion_hold_reason = fields.Char(
        compute='_compute_promotion_payment_hold',
        store=True,
        copy=False,
    )
    promotion_release_reason = fields.Text(
        string='Release/Waiver Reason',
        copy=False,
        tracking=True,
    )
    promotion_release_approved_by_id = fields.Many2one(
        'res.users',
        string='Promotion Release Approved By',
        readonly=True,
        copy=False,
    )
    promotion_release_approved_at = fields.Datetime(
        string='Promotion Release Approved At',
        readonly=True,
        copy=False,
    )
    promotion_promised_foc_qty = fields.Float(
        compute='_compute_promotion_foc_totals',
    )
    promotion_received_foc_qty = fields.Float(
        compute='_compute_promotion_foc_totals',
    )
    promotion_outstanding_foc_qty = fields.Float(
        compute='_compute_promotion_foc_totals',
    )

    @api.depends(
        'promotion_application_ids',
        'promotion_application_ids.outstanding_foc_qty',
        'promotion_release_state',
    )
    def _compute_promotion_payment_hold(self):
        for move in self:
            outstanding = sum(move.promotion_application_ids.mapped('outstanding_foc_qty'))
            hold = bool(
                move.promotion_application_ids
                and move.promotion_release_state == 'hold'
                and outstanding > 0
            )
            move.promotion_payment_hold = hold
            if hold:
                move.promotion_hold_reason = _(
                    '%(quantity)s FOC unit(s) require fulfilment or authorized waiver.'
                ) % {'quantity': outstanding}
            else:
                move.promotion_hold_reason = False

    @api.depends(
        'promotion_application_ids.promised_foc_qty',
        'promotion_application_ids.received_foc_qty',
        'promotion_application_ids.outstanding_foc_qty',
    )
    def _compute_promotion_foc_totals(self):
        for move in self:
            move.promotion_promised_foc_qty = sum(
                move.promotion_application_ids.mapped('promised_foc_qty')
            )
            move.promotion_received_foc_qty = sum(
                move.promotion_application_ids.mapped('received_foc_qty')
            )
            move.promotion_outstanding_foc_qty = sum(
                move.promotion_application_ids.mapped('outstanding_foc_qty')
            )

    def _sync_promotion_payment_hold(self):
        for move in self:
            outstanding = sum(move.promotion_application_ids.mapped('outstanding_foc_qty'))
            if (
                move.promotion_application_ids
                and move.promotion_release_state == 'hold'
                and outstanding <= 0
            ):
                move.write({
                    'promotion_release_state': 'released',
                    'promotion_release_reason': _(
                        'Automatically released: every promised FOC unit was received.'
                    ),
                    'promotion_release_approved_at': fields.Datetime.now(),
                })
                _logger.info(
                    '[VPP_HOLD] auto_released_fulfilled bill_id=%s applications=%s',
                    move.id,
                    move.promotion_application_ids.ids,
                )
            move._compute_promotion_payment_hold()
            if move.promotion_payment_hold:
                if move.payment_state not in ('paid', 'in_payment'):
                    move.payment_state = 'blocked'
                    _logger.info(
                        '[VPP_HOLD] applied bill_id=%s applications=%s outstanding_foc=%s',
                        move.id,
                        move.promotion_application_ids.ids,
                        move.promotion_outstanding_foc_qty,
                    )
            elif move.payment_state == 'blocked':
                move.payment_state = 'not_paid'
                self.env.add_to_compute(move._fields['payment_state'], move)
                _logger.info(
                    '[VPP_HOLD] released bill_id=%s release_state=%s approver_id=%s',
                    move.id,
                    move.promotion_release_state,
                    move.promotion_release_approved_by_id.id,
                )

    def _is_eligible_for_vendor_price_history(self):
        self.ensure_one()
        eligible = super()._is_eligible_for_vendor_price_history()
        if eligible and self.promotion_payment_hold:
            _logger.info(
                '[VPP_PRICE_HISTORY_ELIGIBILITY] bill_id=%s promotion_hold=%s release_state=%s eligible=False',
                self.id,
                self.promotion_payment_hold,
                self.promotion_release_state,
            )
            return False
        return eligible

    def _check_promotion_release_access(self):
        if not (
            self.env.user.has_group('account.group_account_manager')
            or self.env.user.has_group('purchase.group_purchase_manager')
        ):
            raise AccessError(_(
                'Only an Accounting Manager or Purchase Manager can release a promotion payment hold.'
            ))

    def action_approve_promotion_release(self):
        for move in self:
            move._check_promotion_release_access()
            if not move.promotion_application_ids:
                raise ValidationError(_('This bill has no promotion commitments.'))
            incomplete = move.promotion_application_ids.filtered(
                lambda application: application.fulfillment_state != 'fulfilled'
            )
            if incomplete:
                raise ValidationError(_(
                    'FOC fulfilment is incomplete. Outstanding quantity: %(quantity)s. '
                    'Use an authorized waiver if payment must be released early.'
                ) % {'quantity': sum(incomplete.mapped('outstanding_foc_qty'))})
            move.write({
                'promotion_release_state': 'released',
                'promotion_release_approved_by_id': self.env.user.id,
                'promotion_release_approved_at': fields.Datetime.now(),
            })
            move._sync_promotion_payment_hold()
            _logger.info(
                '[VPP_APPROVAL] fulfilled_release bill_id=%s approver_id=%s application_ids=%s',
                move.id,
                self.env.user.id,
                move.promotion_application_ids.ids,
            )
        return True

    def action_waive_promotion_hold(self):
        for move in self:
            move._check_promotion_release_access()
            if not move.promotion_release_reason:
                raise ValidationError(_('Enter a release/waiver reason before approving early payment.'))
            move.write({
                'promotion_release_state': 'waived',
                'promotion_release_approved_by_id': self.env.user.id,
                'promotion_release_approved_at': fields.Datetime.now(),
            })
            move._sync_promotion_payment_hold()
            _logger.warning(
                '[VPP_APPROVAL] waiver bill_id=%s approver_id=%s outstanding_foc=%s reason=%s',
                move.id,
                self.env.user.id,
                move.promotion_outstanding_foc_qty,
                move.promotion_release_reason,
            )
        return True

    def _check_promotion_payment_allowed(self):
        held = self.filtered('promotion_payment_hold')
        if held:
            _logger.warning(
                '[VPP_PAYMENT] blocked bill_ids=%s user_id=%s reasons=%s',
                held.ids,
                self.env.user.id,
                held.mapped('promotion_hold_reason'),
            )
            raise ValidationError(_(
                'Payment is blocked for: %(bills)s. Complete the FOC commitment or obtain an '
                'authorized promotion waiver.'
            ) % {'bills': ', '.join(held.mapped('display_name'))})

    def action_register_payment(self):
        self._check_promotion_payment_allowed()
        return super().action_register_payment()

    def action_force_register_payment(self):
        self._check_promotion_payment_allowed()
        return super().action_force_register_payment()

    def js_assign_outstanding_line(self, line_id):
        self._check_promotion_payment_allowed()
        return super().js_assign_outstanding_line(line_id)

    def action_toggle_block_payment(self):
        for move in self:
            if move.promotion_payment_hold and move.payment_state == 'blocked':
                raise ValidationError(_(
                    'This payment hold is controlled by a vendor promotion. Use the promotion '
                    'fulfilment approval or waiver action.'
                ))
        return super().action_toggle_block_payment()
