from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .audit import TOKEN, operation, require_group


class ChequeReason(models.Model):
    _name = 'account.cheque.reason'
    _description = 'Outgoing Cheque Exception Reason'

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    allow_represent = fields.Boolean(string='Allow Re-presentation', default=False)


class ChequeAttempt(models.Model):
    _name = 'account.cheque.attempt'
    _description = 'Outgoing Cheque Banking Attempt'
    _inherit = ['mail.thread']
    _check_company_auto = True
    _order = 'id desc'

    name = fields.Char(compute='_compute_name', store=True)
    bank_code = fields.Char(string='Bank Code at Confirmation', readonly=True)
    leaf_id = fields.Many2one('account.cheque.leaf', required=True, check_company=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='leaf_id.company_id', store=True)
    payment_id = fields.Many2one('account.payment', required=True, check_company=True, ondelete='restrict')
    number = fields.Integer(required=True)
    partner_id = fields.Many2one(related='payment_id.partner_id', store=True)
    currency_id = fields.Many2one(related='payment_id.currency_id')
    amount = fields.Monetary(related='payment_id.amount', store=True)
    state = fields.Selection([('reserved', 'Reserved'), ('pending', 'Awaiting Clearance'), ('cleared', 'Cleared'), ('reported', 'Returned / Correction Pending'), ('corrected', 'Failure Accounted'), ('void', 'Voided'), ('review', 'Bank Evidence Changed')], default='reserved', readonly=True, tracking=True)
    reason_id = fields.Many2one('account.cheque.reason', readonly=True, ondelete='restrict')
    note = fields.Text(readonly=True)
    bank_statement_id = fields.Many2one('account.bank.statement.line', readonly=True, check_company=True, ondelete='restrict')
    return_statement_id = fields.Many2one('account.bank.statement.line', readonly=True, check_company=True, ondelete='restrict')
    reversal_move_id = fields.Many2one('account.move', readonly=True, check_company=True, ondelete='restrict')
    original_debt_ids = fields.Many2many('account.move.line', readonly=True, check_company=True)
    planned_debt_ids = fields.Many2many('account.move.line', 'cheque_attempt_planned_debt_rel', 'attempt_id', 'line_id', readonly=True, check_company=True)
    delivered_date = fields.Date(readonly=True)
    receipt_reference = fields.Char(readonly=True)
    approved_by_id = fields.Many2one('res.users', readonly=True)
    approved_date = fields.Datetime(readonly=True)
    signed_by_id = fields.Many2one('res.users', readonly=True)
    signed_date = fields.Date(readonly=True)
    stop_state = fields.Selection([('none', 'Not Requested'), ('requested', 'Requested'), ('confirmed', 'Confirmed by Bank')], default='none', readonly=True)
    stop_reference = fields.Char(readonly=True)

    _sql_constraints = [
        ('leaf_attempt_unique', 'unique(leaf_id, number)', 'This attempt number already exists.'),
        ('payment_unique', 'unique(payment_id)', 'A payment can belong to only one cheque attempt.'),
        ('bank_debit_unique', 'unique(bank_statement_id)', 'This bank debit already belongs to a cheque attempt.'),
        ('bank_return_unique', 'unique(return_statement_id)', 'This bank return already belongs to a cheque attempt.'),
    ]

    @api.depends('leaf_id.number', 'number')
    def _compute_name(self):
        for attempt in self:
            attempt.name = _('%(cheque)s / Attempt %(number)s', cheque=attempt.leaf_id.number, number=attempt.number)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_cheque_capability') is not TOKEN:
            raise UserError(_('Banking attempts are created by the cheque payment workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('_cheque_capability') is not TOKEN:
            raise UserError(_('Use the cheque workflow to change a banking attempt.'))
        return super().write(vals)

    def unlink(self):
        raise UserError(_('Banking attempts cannot be deleted.'))

    def _update(self, vals):
        return self.with_context(_cheque_capability=TOKEN).write(vals)

    def _lines(self):
        self.ensure_one()
        payment = self.payment_id
        liquidity = payment.move_id.line_ids.filtered(lambda line: line.account_id == payment.outstanding_account_id)
        payable = payment.move_id.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        if len(liquidity) != 1 or len(payable) != 1 or payment.currency_id.compare_amounts(payable.debit, payment.amount):
            raise ValidationError(_('The cheque requires one exact payable debit and one outstanding-payment credit. Separate write-offs from this cheque payment.'))
        return liquidity, payable

    def _bank_evidence_valid(self, statement):
        self.ensure_one()
        payment = self.payment_id
        if payment.move_id.state != 'posted' or payment.move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted') or not statement or statement.company_id != self.company_id or statement.journal_id != payment.journal_id or statement.move_id.state != 'posted' or not statement.is_reconciled or statement.move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted'):
            return False
        if self.currency_id.compare_amounts(statement.amount, -payment.amount):
            return False
        if statement.currency_id != self.currency_id or payment.cheque_date > fields.Date.context_today(self) or statement.date < payment.cheque_date:
            return False
        try:
            liquidity, payable = self._lines()
        except ValidationError:
            return False
        matched = liquidity.matched_debit_ids.debit_move_id
        evidence = statement.move_id.line_ids.filtered(lambda line: line.account_id == liquidity.account_id and line.balance > 0)
        return bool(len(evidence) == 1 and liquidity.reconciled and evidence.reconciled and evidence in matched and not self.currency_id.compare_amounts(evidence.debit, payment.amount))

    def _confirm_clearance(self, statement):
        self.ensure_one()
        if self.state not in ('pending', 'review') or not self._bank_evidence_valid(statement):
            raise UserError(_('Select the reconciled bank debit matched to this exact cheque payment and principal.'))
        self._update({'state': 'cleared', 'bank_statement_id': statement.id})
        self.leaf_id._set({'state': 'cleared'}, 'cleared')

    def _correct_failure(self, date, note, statement=False):
        self.ensure_one()
        if self.state == 'corrected':
            return
        if self.state != 'reported':
            raise UserError(_('Report the cheque return before correcting its accounting.'))
        payment = self.payment_id
        if date <= self.company_id._get_user_fiscal_lock_date(payment.journal_id):
            raise UserError(_('The correction date is locked. Select an open accounting date.'))
        liquidity, payable = self._lines()
        if payment.move_id.state != 'posted' or payment.move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted'):
            raise UserError(_('The original payment must be posted and must not already have a reversal.'))
        was_debited = bool(liquidity.matched_debit_ids)
        return_line = self.env['account.move.line']
        if was_debited:
            if not self._bank_evidence_valid(self.bank_statement_id):
                raise UserError(_('Verify the original clearance evidence before correcting a payment already matched at the bank.'))
            if not statement or statement.journal_id != payment.journal_id or statement.company_id != self.company_id or statement.currency_id != self.currency_id or statement.move_id.state != 'posted' or not statement.is_reconciled or self.currency_id.compare_amounts(statement.amount, payment.amount) or statement.move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted'):
                raise UserError(_('A reconciled positive bank return against outstanding payments is required for a previously debited cheque.'))
            return_line = statement.move_id.line_ids.filtered(lambda line: line.account_id == liquidity.account_id and line.credit > 0)
            if len(return_line) != 1 or self.currency_id.compare_amounts(return_line.credit, payment.amount) or return_line.reconciled:
                raise UserError(_('The bank return must contain the exact, unallocated cheque principal on the outstanding-payments account.'))
        elif statement:
            raise UserError(_('An uncleared cheque needs no principal bank refund. Record bank fees separately.'))
        debts = payable.matched_credit_ids.credit_move_id
        payable.remove_move_reconcile()
        reversal = payment.move_id._reverse_moves([{'date': date, 'ref': _('Cheque payment correction')}], cancel=False)
        if reversal.state != 'posted':
            reversal.action_post()
        reverse_payable = reversal.line_ids.filtered(lambda line: line.account_id == payable.account_id)
        remaining_payable = (payable | reverse_payable).filtered(lambda line: not line.reconciled)
        if remaining_payable:
            remaining_payable.reconcile()
        reverse_liquidity = reversal.line_ids.filtered(lambda line: line.account_id == liquidity.account_id)
        remaining_liquidity = (reverse_liquidity | (return_line if was_debited else liquidity)).filtered(lambda line: not line.reconciled)
        if remaining_liquidity:
            remaining_liquidity.reconcile()
        self._update({'state': 'corrected', 'reversal_move_id': reversal.id, 'return_statement_id': statement.id if statement else False, 'original_debt_ids': [(6, 0, debts.ids)]})
        self.leaf_id._set({'state': 'returned'}, 'failure_accounted', note)

    @api.model
    def _cron_review_evidence(self):
        # Never repeat postings when bank evidence is subsequently changed.
        attempts = self.search([('state', '=', 'cleared'), ('company_id', 'in', self.env.companies.ids)])
        with operation(attempts, 'EVIDENCE_REVIEW'):
            for attempt in attempts:
                attempt.leaf_id._lock()
                if attempt.state == 'cleared' and not attempt._bank_evidence_valid(attempt.bank_statement_id):
                    attempt._update({'state': 'review'})
                    if attempt.leaf_id.current_attempt_id == attempt:
                        attempt.leaf_id._set({'state': 'review'}, 'bank_evidence_changed')
