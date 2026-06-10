import logging
import re
from hashlib import sha1

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

_log = logging.getLogger(__name__)

MPESA_REF_RE = re.compile(r'^[A-Z0-9]{10}$')


class MpesaTransaction(models.Model):
    _inherit = 'mpesa.transaction'

    entry_source = fields.Selection(
        [
            ('bridge', 'Bridge SMS'),
            ('manual', 'Manual Entry'),
        ],
        string='Entry Source',
        default='bridge',
        required=True,
        index=True,
        readonly=True,
    )
    manual_created_by_id = fields.Many2one(
        'res.users', 'Manual Entry User', readonly=True, ondelete='set null',
    )
    manual_created_at = fields.Datetime('Manual Entry Time', readonly=True)
    manual_reason = fields.Text('Manual Entry Reason', readonly=True)

    @api.constrains('mpesa_ref')
    def _check_mpesa_ref_format(self):
        for rec in self:
            ref = (rec.mpesa_ref or '').strip().upper()
            if ref and not MPESA_REF_RE.match(ref):
                raise ValidationError(_('M-Pesa reference must be exactly 10 uppercase letters/numbers.'))


class MpesaManualSmsWizard(models.TransientModel):
    _name = 'mpesa.manual.sms.wizard'
    _description = 'Manual M-Pesa SMS Entry'

    mpesa_ref = fields.Char('M-Pesa Reference', required=True)
    amount = fields.Monetary('Amount (Ksh)', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.ref('base.KES', raise_if_not_found=False),
        required=True,
    )
    transaction_date = fields.Datetime(
        'Transaction Date',
        required=True,
        default=fields.Datetime.now,
        help='Use the date/time shown on the customer SMS or Safaricom statement.',
    )
    sender_name = fields.Char('Sender Name', required=True)
    sender_phone = fields.Char('Sender Phone')
    partner_id = fields.Many2one('res.partner', 'Customer')
    transaction_cost = fields.Monetary('Transaction Cost', currency_field='currency_id', default=0.0)
    utility_balance = fields.Monetary('Till Balance After', currency_field='currency_id')
    reason = fields.Text(
        'Reason / Evidence',
        required=True,
        help='Record why this was entered manually, such as network delay, bridge outage, parse error, or statement proof.',
    )

    @api.onchange('mpesa_ref')
    def _onchange_mpesa_ref(self):
        if self.mpesa_ref:
            self.mpesa_ref = self.mpesa_ref.strip().upper().replace(' ', '')

    @api.onchange('sender_phone')
    def _onchange_sender_phone(self):
        if self.sender_phone:
            self.sender_phone = self._normalise_phone(self.sender_phone)

    @api.constrains('mpesa_ref')
    def _check_mpesa_ref(self):
        for rec in self:
            ref = (rec.mpesa_ref or '').strip().upper()
            if not MPESA_REF_RE.match(ref):
                raise ValidationError(_('M-Pesa reference must be exactly 10 uppercase letters/numbers.'))

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Amount must be greater than zero.'))

    def action_create_manual_sms(self):
        self.ensure_one()
        self._check_manual_entry_access()

        ref = self.mpesa_ref.strip().upper()
        existing = self.env['mpesa.transaction'].sudo().search([('mpesa_ref', '=', ref)], limit=1)
        if existing:
            _log.warning(
                "Manual M-Pesa entry rejected duplicate ref=%s user=%s existing_id=%s",
                ref, self.env.user.login, existing.id,
            )
            raise ValidationError(_('M-Pesa reference already exists. Open the existing transaction instead.'))

        sender_phone = self._normalise_phone(self.sender_phone)
        queue_id = self._manual_queue_id(ref)
        raw_text = self._manual_raw_text(ref)
        _log.info(
            "Manual M-Pesa entry requested ref=%s amount=%.2f phone=%s user=%s partner_id=%s",
            ref, self.amount, sender_phone or '', self.env.user.login, self.partner_id.id or False,
        )

        raw_log = self.env['mpesa.sms.raw.log'].sudo().create({
            'queue_id': queue_id,
            'raw_text': raw_text,
            'source_phone': sender_phone or 'MANUAL',
            'received_at': fields.Datetime.now(),
            'modem_index': -1,
            'parse_status': 'success',
        })

        txn = self.env['mpesa.transaction'].sudo().create({
            'mpesa_ref': ref,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'sender_name': self.sender_name,
            'sender_phone': sender_phone,
            'transaction_date': self.transaction_date,
            'utility_balance': self.utility_balance,
            'transaction_cost': self.transaction_cost,
            'partner_id': self.partner_id.id or False,
            'raw_log_id': raw_log.id,
            'state': 'new' if self.partner_id else 'unmatched',
            'entry_source': 'manual',
            'manual_created_by_id': self.env.user.id,
            'manual_created_at': fields.Datetime.now(),
            'manual_reason': self.reason,
        })
        raw_log.mark_parsed(txn)

        if hasattr(txn, 'message_post'):
            txn.message_post(
                body=_(
                    'Manual M-Pesa SMS entry created by %(user)s.<br/>Reason: %(reason)s',
                    user=self.env.user.display_name,
                    reason=self.reason,
                ),
                subtype_xmlid='mail.mt_note',
            )
        _log.warning(
            "Manual M-Pesa transaction created txn_id=%s raw_log_id=%s ref=%s amount=%.2f user=%s reason=%s",
            txn.id, raw_log.id, ref, self.amount, self.env.user.login, self.reason[:200],
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mpesa.transaction',
            'res_id': txn.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _check_manual_entry_access(self):
        if not (
            self.env.user.has_group('mpesa_c2b_sms.group_mpesa_manual_entry')
            or self.env.user.has_group('mpesa_c2b_sms.group_mpesa_manager')
        ):
            raise AccessError(_('You are not authorized to create manual M-Pesa SMS entries.'))

    def _manual_queue_id(self, ref):
        source = f"manual|{ref}|{self.env.uid}|{fields.Datetime.now()}"
        return 'manual-%s' % sha1(source.encode('utf-8')).hexdigest()[:16]

    @staticmethod
    def _normalise_phone(phone):
        digits = re.sub(r'\D', '', phone or '')
        if len(digits) == 12 and digits.startswith('254'):
            return digits
        if len(digits) == 10 and digits.startswith('0'):
            return '254' + digits[1:]
        if len(digits) == 9 and digits[0] in ('7', '1'):
            return '254' + digits
        return digits

    def _manual_raw_text(self, ref):
        date_text = fields.Datetime.to_datetime(self.transaction_date).strftime('%d/%m/%y at %I:%M %p')
        sender = self.sender_name.strip()
        phone = self._normalise_phone(self.sender_phone)
        phone_part = f" {phone}" if phone else ""
        balance = self.utility_balance or 0.0
        cost = self.transaction_cost or 0.0
        return (
            f"{ref} Confirmed. on {date_text} Ksh{self.amount:,.2f} received from "
            f"{sender}{phone_part}. New Utility balance is Ksh{balance:,.2f}. "
            f"Transaction cost, Ksh{cost:,.2f}. MANUAL ENTRY by {self.env.user.login}. "
            f"Reason: {self.reason}"
        )
