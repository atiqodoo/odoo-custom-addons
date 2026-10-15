import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

_log = logging.getLogger(__name__)


class MpesaTransactionFreeze(models.Model):
    _name = 'mpesa.transaction.freeze'
    _description = 'M-Pesa Manual Transaction Freeze'
    _order = 'create_date desc, id desc'
    _rec_name = 'transaction_id'

    transaction_id = fields.Many2one(
        'mpesa.transaction',
        'M-Pesa Transaction',
        required=True,
        index=True,
        ondelete='cascade',
    )
    amount = fields.Monetary(required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        related='transaction_id.currency_id',
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [('active', 'Active'), ('released', 'Released')],
        default='active',
        required=True,
        index=True,
    )
    reason = fields.Text()
    frozen_by_employee_id = fields.Many2one('hr.employee', readonly=True, ondelete='set null')
    frozen_by_user_id = fields.Many2one('res.users', readonly=True, ondelete='set null')
    frozen_at = fields.Datetime(readonly=True)
    unfrozen_by_employee_id = fields.Many2one('hr.employee', readonly=True, ondelete='set null')
    unfrozen_by_user_id = fields.Many2one('res.users', readonly=True, ondelete='set null')
    unfrozen_at = fields.Datetime(readonly=True)

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if float_compare(
                rec.amount or 0.0,
                0.0,
                precision_rounding=rec.currency_id.rounding or 0.01,
            ) <= 0:
                raise ValidationError(_('Frozen amount must be greater than zero.'))

    def action_release(self, employee=False, amount=False):
        now = fields.Datetime.now()
        remaining_to_release = float(amount or 0.0)
        for rec in self.filtered(lambda freeze: freeze.state == 'active'):
            release_amount = rec.amount
            if remaining_to_release:
                if float_compare(
                    remaining_to_release,
                    0.0,
                    precision_rounding=rec.currency_id.rounding or 0.01,
                ) <= 0:
                    break
                release_amount = min(rec.amount, remaining_to_release)
            _log.info(
                "M-Pesa manual freeze release: freeze_id=%s txn_id=%s ref=%s "
                "release_amount=%.2f original_active_amount=%.2f employee=%s user=%s",
                rec.id,
                rec.transaction_id.id,
                rec.transaction_id.mpesa_ref,
                release_amount,
                rec.amount,
                employee.id if employee else False,
                self.env.uid,
            )
            if float_compare(
                release_amount,
                rec.amount,
                precision_rounding=rec.currency_id.rounding or 0.01,
            ) >= 0:
                rec.write({
                    'state': 'released',
                    'unfrozen_by_employee_id': employee.id if employee else False,
                    'unfrozen_by_user_id': self.env.uid,
                    'unfrozen_at': now,
                })
            else:
                rec.write({'amount': rec.amount - release_amount})
                self.sudo().create({
                    'transaction_id': rec.transaction_id.id,
                    'amount': release_amount,
                    'state': 'released',
                    'reason': rec.reason,
                    'frozen_by_employee_id': rec.frozen_by_employee_id.id,
                    'frozen_by_user_id': rec.frozen_by_user_id.id,
                    'frozen_at': rec.frozen_at,
                    'unfrozen_by_employee_id': employee.id if employee else False,
                    'unfrozen_by_user_id': self.env.uid,
                    'unfrozen_at': now,
                })
            if remaining_to_release:
                remaining_to_release = max(remaining_to_release - release_amount, 0.0)


class MpesaTransaction(models.Model):
    _inherit = 'mpesa.transaction'

    manual_freeze_ids = fields.One2many(
        'mpesa.transaction.freeze',
        'transaction_id',
        'Manual Freezes',
        readonly=True,
    )
    amount_manually_frozen = fields.Monetary(
        'Amount Manually Frozen',
        currency_field='currency_id',
        compute='_compute_amount_manually_frozen',
        store=True,
        help='Amount intentionally frozen from backend SMS review and unavailable to POS.',
    )
    is_manually_frozen = fields.Boolean(
        'Manually Frozen',
        compute='_compute_is_manually_frozen',
        store=True,
    )

    @api.depends('manual_freeze_ids.amount', 'manual_freeze_ids.state')
    def _compute_amount_manually_frozen(self):
        for rec in self:
            active_freezes = rec.manual_freeze_ids.filtered(lambda freeze: freeze.state == 'active')
            rec.amount_manually_frozen = sum(active_freezes.mapped('amount'))

    @api.depends('amount_manually_frozen')
    def _compute_is_manually_frozen(self):
        for rec in self:
            rec.is_manually_frozen = bool(rec.amount_manually_frozen)

    @api.depends(
        'amount',
        'amount_used',
        'amount_refunded',
        'amount_reversed',
        'amount_frozen',
        'amount_manually_frozen',
    )
    def _compute_amount_remaining(self):
        for rec in self:
            rec.amount_remaining = max(
                (rec.amount or 0.0)
                - (rec.amount_used or 0.0)
                - (rec.amount_refunded or 0.0)
                - (rec.amount_reversed or 0.0)
                - (rec.amount_frozen or 0.0)
                - (rec.amount_manually_frozen or 0.0),
                0.0,
            )

    def _available_state(self):
        self.ensure_one()
        if self.amount_manually_frozen and not self.amount_remaining:
            if self.amount_used:
                return 'partial_pos'
            return 'new' if self.partner_id else 'unmatched'
        return super()._available_state()

    def action_open_freeze_wizard(self):
        self.ensure_one()
        _log.debug(
            "Opening M-Pesa freeze wizard: txn_id=%s ref=%s remaining=%.2f user=%s",
            self.id,
            self.mpesa_ref,
            self.amount_remaining,
            self.env.uid,
        )
        return self._mpesa_freeze_wizard_action('freeze')

    def action_open_unfreeze_wizard(self):
        self.ensure_one()
        _log.debug(
            "Opening M-Pesa unfreeze wizard: txn_id=%s ref=%s manual_frozen=%.2f user=%s",
            self.id,
            self.mpesa_ref,
            self.amount_manually_frozen,
            self.env.uid,
        )
        return self._mpesa_freeze_wizard_action('unfreeze')

    def _mpesa_freeze_wizard_action(self, operation):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Freeze M-Pesa Balance') if operation == 'freeze' else _('Unfreeze M-Pesa Balance'),
            'res_model': 'mpesa.transaction.freeze.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_transaction_id': self.id,
                'default_operation': operation,
            },
        }

    def _mpesa_log_freeze_authorization(self, operation, approved, employee=False, message=False):
        try:
            Log = self.env['sbl.pos.authorization.log'].sudo()
        except KeyError:
            return
        for rec in self:
            Log.sbl_log_authorization({
                'action_key': 'mpesa_sms_%s' % operation,
                'action_label': 'M-Pesa SMS %s' % ('Freeze' if operation == 'freeze' else 'Unfreeze'),
                'status': 'approved' if approved else 'denied',
                'supervisor_id': employee.id if employee else False,
                'message': message or '%s ref=%s amount_remaining=%.2f manual_frozen=%.2f' % (
                    operation,
                    rec.mpesa_ref,
                    rec.amount_remaining,
                    rec.amount_manually_frozen,
                ),
            })

    def _mpesa_authorize_freeze_pin(self, pin, operation):
        self.ensure_one()
        _log.warning(
            "M-Pesa %s authorization denied because no authorization provider is installed: "
            "txn_id=%s ref=%s user=%s",
            operation,
            self.id,
            self.mpesa_ref,
            self.env.uid,
        )
        message = _('No employee authorization provider is installed for M-Pesa freeze operations.')
        self._mpesa_log_freeze_authorization(operation, False, message=message)
        return {'approved': False, 'message': message, 'employee_id': False}

    def _mpesa_freeze_remaining(self, employee=False, reason=False, amount=False):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM mpesa_transaction WHERE id = %s FOR UPDATE NOWAIT",
            (self.id,),
        )
        remaining = self.amount_remaining or 0.0
        precision = self.currency_id.rounding or 0.01
        if float_compare(remaining, 0.0, precision_rounding=precision) <= 0:
            raise ValidationError(_('There is no remaining M-Pesa amount to freeze.'))
        freeze_amount = float(amount or remaining)
        if float_compare(freeze_amount, 0.0, precision_rounding=precision) <= 0:
            raise ValidationError(_('Freeze amount must be greater than zero.'))
        if float_compare(freeze_amount, remaining, precision_rounding=precision) > 0:
            raise ValidationError(_(
                'Freeze amount %(amount).2f is higher than available transaction balance %(available).2f.'
            ) % {
                'amount': freeze_amount,
                'available': remaining,
            })

        freeze = self.env['mpesa.transaction.freeze'].sudo().create({
            'transaction_id': self.id,
            'amount': freeze_amount,
            'reason': reason,
            'frozen_by_employee_id': employee.id if employee else False,
            'frozen_by_user_id': self.env.uid,
            'frozen_at': fields.Datetime.now(),
        })
        _log.info(
            "M-Pesa manual freeze created: freeze_id=%s txn_id=%s ref=%s amount=%.2f "
            "available_before=%.2f employee=%s user=%s reason=%s",
            freeze.id,
            self.id,
            self.mpesa_ref,
            freeze_amount,
            remaining,
            employee.id if employee else False,
            self.env.uid,
            reason or '',
        )
        self.write({'state': self._available_state()})
        _log.debug(
            "M-Pesa manual freeze state refresh: txn_id=%s ref=%s state=%s "
            "remaining=%.2f manual_frozen=%.2f",
            self.id,
            self.mpesa_ref,
            self.state,
            self.amount_remaining,
            self.amount_manually_frozen,
        )
        return freeze

    def _mpesa_unfreeze_active(self, employee=False, amount=False):
        self.ensure_one()
        active_freezes = self.manual_freeze_ids.filtered(lambda freeze: freeze.state == 'active')
        if not active_freezes:
            raise ValidationError(_('There is no active manual freeze to release.'))
        frozen_amount = self.amount_manually_frozen or 0.0
        precision = self.currency_id.rounding or 0.01
        release_amount = float(amount or frozen_amount)
        if float_compare(release_amount, 0.0, precision_rounding=precision) <= 0:
            raise ValidationError(_('Unfreeze amount must be greater than zero.'))
        if float_compare(release_amount, frozen_amount, precision_rounding=precision) > 0:
            raise ValidationError(_(
                'Unfreeze amount %(amount).2f is higher than manually frozen balance %(frozen).2f.'
            ) % {
                'amount': release_amount,
                'frozen': frozen_amount,
            })
        active_freezes.sorted('create_date').sudo().action_release(
            employee=employee,
            amount=release_amount,
        )
        _log.info(
            "M-Pesa manual freezes released: txn_id=%s ref=%s amount=%.2f "
            "frozen_before=%.2f count=%d employee=%s user=%s",
            self.id,
            self.mpesa_ref,
            release_amount,
            frozen_amount,
            len(active_freezes),
            employee.id if employee else False,
            self.env.uid,
        )
        self.write({'state': self._available_state()})
        _log.debug(
            "M-Pesa manual unfreeze state refresh: txn_id=%s ref=%s state=%s "
            "remaining=%.2f manual_frozen=%.2f",
            self.id,
            self.mpesa_ref,
            self.state,
            self.amount_remaining,
            self.amount_manually_frozen,
        )
        return True
