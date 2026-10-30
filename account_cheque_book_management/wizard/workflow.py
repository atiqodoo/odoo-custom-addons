from odoo import fields, models, _
from odoo.exceptions import UserError
from ..models.audit import TOKEN, operation, require_group


class ChequeWorkflow(models.TransientModel):
    _name = 'account.cheque.workflow'
    _description = 'Cheque Lifecycle Action'
    _check_company_auto = True

    leaf_id = fields.Many2one('account.cheque.leaf', required=True, check_company=True)
    company_id = fields.Many2one(related='leaf_id.company_id')
    action = fields.Selection([
        ('damage', 'Mark Unused Leaf Damaged'), ('void', 'Void / Cancel Recovered Cheque'),
        ('sign', 'Confirm Authorised Signature'), ('deliver', 'Record Handover / Vendor Receipt'), ('clear', 'Confirm Bank Clearance'),
        ('report', 'Report Bank Return'), ('correct', 'Confirm Return Accounting'),
        ('represent', 'Re-present Same Cheque'), ('replace', 'Issue Replacement Cheque'),
        ('stop_request', 'Request Stop-Payment'), ('stop_confirm', 'Confirm Bank Stop-Payment'),
    ], required=True, default='report')
    date = fields.Date(required=True, default=fields.Date.context_today)
    note = fields.Text(required=True)
    reference = fields.Char(string='Receipt / Bank Reference')
    reason_id = fields.Many2one('account.cheque.reason')
    statement_id = fields.Many2one('account.bank.statement.line', check_company=True)
    replacement_leaf_id = fields.Many2one('account.cheque.leaf', check_company=True)
    replacement_amount = fields.Monetary(help='Required for replacements. Recheck unpaid balances and other payments before approval.')
    currency_id = fields.Many2one(related='company_id.currency_id')
    instrument_recovered = fields.Boolean(string='Original Physical Cheque Recovered / Destroyed')
    cheque_copy = fields.Binary(string='Completed Cheque Copy', attachment=False)
    cheque_copy_filename = fields.Char()

    def action_apply(self):
        self.ensure_one()
        leaf = self.leaf_id
        group = 'group_cheque_user' if self.action in ('damage', 'deliver', 'report', 'stop_request') else 'group_cheque_accountant'
        require_group(leaf, group)
        if not (self.note or '').strip():
            raise UserError(_('Record a reason or supporting explanation.'))
        with operation(leaf, self.action.upper()):
            (leaf | self.replacement_leaf_id)._lock()
            # Dispatch to a small operation method; extensions can add actions.
            handler = getattr(self, '_apply_' + self.action, None)
            if not handler:
                raise UserError(_('Unsupported cheque operation.'))
            result = handler()
        return result or {'type': 'ir.actions.act_window_close'}

    def _attempt(self):
        attempt = self.leaf_id.current_attempt_id
        if not attempt:
            raise UserError(_('This leaf has no payment attempt.'))
        return attempt

    def _apply_damage(self):
        if self.leaf_id.state != 'available':
            raise UserError(_('Only an unused available leaf can be marked damaged.'))
        self.leaf_id._set({'state': 'damaged'}, 'damaged', self.note)

    def _apply_deliver(self):
        attempt = self._attempt()
        if attempt.state != 'pending' or attempt.delivered_date or not self.reference or not attempt.signed_by_id:
            raise UserError(_('Confirm the signature, then record a receipt reference for a posted cheque not already handed over.'))
        attempt._update({'delivered_date': self.date, 'receipt_reference': self.reference})
        self.leaf_id._set({}, 'handed_over', self.note)

    def _apply_sign(self):
        attempt = self._attempt()
        if attempt.state != 'pending' or attempt.signed_by_id:
            raise UserError(_('Only an unsigned posted cheque can be signed.'))
        attempt._update({'signed_by_id': self.env.uid, 'signed_date': self.date})
        self.leaf_id._set({}, 'signature_confirmed', self.note)

    def _apply_clear(self):
        self._attempt()._confirm_clearance(self.statement_id)

    def _apply_report(self):
        attempt = self._attempt()
        if attempt.state not in ('pending', 'cleared', 'review') or not self.reason_id:
            raise UserError(_('Select a return reason for an issued or cleared cheque.'))
        if self.statement_id:
            attempt._confirm_clearance(self.statement_id)
        attempt._update({'state': 'reported', 'reason_id': self.reason_id.id, 'note': self.note})
        self.leaf_id._set({'state': 'returned'}, 'return_reported', self.note)

    def _apply_correct(self):
        self._attempt()._correct_failure(self.date, self.note, self.statement_id)

    def _apply_stop_request(self):
        attempt = self._attempt()
        if attempt.state in ('cleared', 'void') or attempt.stop_state != 'none':
            raise UserError(_('Stop-payment cannot be requested for this cheque.'))
        attempt._update({'stop_state': 'requested'})
        self.leaf_id._set({}, 'stop_requested', self.note)

    def _apply_stop_confirm(self):
        attempt = self._attempt()
        if attempt.stop_state != 'requested' or not self.reference:
            raise UserError(_('A pending stop request and bank confirmation reference are required.'))
        attempt._update({'stop_state': 'confirmed', 'stop_reference': self.reference})
        self.leaf_id._set({}, 'stop_confirmed', self.note)

    def _apply_void(self):
        leaf = self.leaf_id
        attempt = leaf.current_attempt_id
        if not attempt:
            if leaf.state != 'available':
                raise UserError(_('This leaf cannot be cancelled.'))
        else:
            if attempt.state not in ('reserved', 'pending', 'corrected'):
                raise UserError(_('Correct any returned cheque accounting before cancellation.'))
            if not self.instrument_recovered and attempt.stop_state != 'confirmed':
                raise UserError(_('Recover the physical cheque or obtain confirmed bank stop-payment first.'))
            if attempt.state == 'pending':
                liquidity, payable = attempt._lines()
                if liquidity.matched_debit_ids:
                    raise UserError(_('Use the bank return workflow for a cheque already debited by the bank.'))
                attempt._update({'state': 'reported'})
                attempt._correct_failure(self.date, self.note)
            attempt._update({'state': 'void'})
        leaf._set({'state': 'cancelled'}, 'cancelled', self.note)

    def _new_payment(self, target, amount, date):
        if not self.cheque_copy:
            raise UserError(_('Attach a copy of the completed cheque for this re-presentation or replacement.'))
        attempt = self._attempt()
        payment = attempt.payment_id
        new_payment = self.env['account.payment'].create({
            'payment_type': 'outbound', 'partner_type': 'supplier', 'partner_id': payment.partner_id.id,
            'journal_id': target.journal_id.id,
            'payment_method_line_id': payment.payment_method_line_id.id,
            'currency_id': payment.currency_id.id, 'amount': amount, 'date': date,
            'cheque_date': payment.cheque_date if target == self.leaf_id else date,
            'cheque_book_id': target.book_id.id, 'cheque_leaf_id': target.id,
            'cheque_copy': self.with_context(bin_size=False).cheque_copy,
            'cheque_copy_filename': self.cheque_copy_filename,
        })
        debts = attempt.original_debt_ids.filtered(lambda line: line.parent_state == 'posted' and not line.reconciled and line.amount_residual < 0)
        new_payment.cheque_leaf_id.current_attempt_id._update({'planned_debt_ids': [(6, 0, debts.ids)]})
        if not new_payment.journal_id.cheque_separate_approval:
            new_payment.action_post()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.payment', 'res_id': new_payment.id, 'view_mode': 'form'}

    def _apply_represent(self):
        attempt = self._attempt()
        if attempt.state != 'corrected' or not attempt.reason_id.allow_represent or attempt.stop_state != 'none' or self.leaf_id.state != 'returned':
            raise UserError(_('Re-presentation requires corrected return accounting, a permitted reason and no stop-payment or replacement.'))
        validity = self.leaf_id.journal_id.cheque_validity_days
        cheque_date = attempt.payment_id.cheque_date
        if self.date < cheque_date or (validity and (self.date - cheque_date).days > validity):
            raise UserError(_('This cheque is postdated or outside the configured validity period. Obtain an authorised replacement.'))
        debts = attempt.original_debt_ids.filtered(lambda line: line.parent_state == 'posted' and not line.reconciled and line.amount_residual < 0)
        if attempt.original_debt_ids and self.currency_id.compare_amounts(attempt.amount, -sum(debts.mapped('amount_residual'))) > 0:
            raise UserError(_('Other payments have reduced the original unpaid bills. Issue a replacement for the remaining balance.'))
        self.leaf_id._set({'state': 'available'}, 'represent_authorised', self.note)
        return self._new_payment(self.leaf_id, attempt.amount, self.date)

    def _apply_replace(self):
        attempt = self._attempt()
        target = self.replacement_leaf_id
        if attempt.state not in ('corrected', 'void') or self.leaf_id.state not in ('returned', 'cancelled'):
            raise UserError(_('Resolve the original payment accounting before issuing a replacement.'))
        if not self.instrument_recovered and attempt.stop_state != 'confirmed':
            raise UserError(_('Recover the original instrument or confirm bank stop-payment before replacement.'))
        if not target or target == self.leaf_id or target.journal_id != self.leaf_id.journal_id or target.state != 'available' or target.replacement_for_id:
            raise UserError(_('Choose an unused replacement leaf from the same bank journal.'))
        if self.replacement_amount <= 0 or self.replacement_amount > attempt.amount:
            raise UserError(_('Enter the remaining amount to replace, greater than zero and no higher than the original principal.'))
        debts = attempt.original_debt_ids.filtered(lambda line: line.parent_state == 'posted' and not line.reconciled and line.amount_residual < 0)
        if attempt.original_debt_ids and self.currency_id.compare_amounts(self.replacement_amount, -sum(debts.mapped('amount_residual'))) > 0:
            raise UserError(_('The replacement exceeds the unpaid balance of the original bills.'))
        target._set({'replacement_for_id': self.leaf_id.id}, 'replacement_reserved', self.note)
        result = self._new_payment(target, self.replacement_amount, self.date)
        self.leaf_id._set({'state': 'replaced'}, 'replaced', self.note)
        return result
