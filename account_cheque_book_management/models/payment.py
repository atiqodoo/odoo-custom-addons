from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .audit import TOKEN, operation, require_group


class ChequePayment(models.Model):
    _inherit = 'account.payment'

    cheque_managed = fields.Boolean(compute='_compute_cheque_managed')
    cheque_book_id = fields.Many2one('account.cheque.book', check_company=True, copy=False, ondelete='restrict')
    cheque_leaf_id = fields.Many2one('account.cheque.leaf', check_company=True, copy=False, ondelete='restrict')
    cheque_date = fields.Date(copy=False, default=fields.Date.context_today)
    cheque_copy = fields.Binary(string='Completed Cheque Copy', attachment=True, copy=False,
        help='Upload a scan or photograph of the completed cheque being paid. Required before confirmation.')
    cheque_copy_filename = fields.Char(string='Cheque Copy Filename', copy=False)
    cheque_attempt_ids = fields.One2many('account.cheque.attempt', 'payment_id', readonly=True)
    check_manual_sequencing = fields.Boolean(related=None, compute='_compute_cheque_sequencing')

    @api.depends('journal_id.check_manual_sequencing', 'cheque_leaf_id')
    def _compute_cheque_sequencing(self):
        for payment in self:
            payment.check_manual_sequencing = payment.journal_id.check_manual_sequencing and not payment.cheque_leaf_id

    @api.depends('journal_id.cheque_book_enabled', 'payment_method_code', 'payment_type', 'partner_type')
    def _compute_cheque_managed(self):
        for payment in self:
            payment.cheque_managed = bool(payment.journal_id.cheque_book_enabled and payment.payment_method_code == 'check_printing' and payment.payment_type == 'outbound' and payment.partner_type == 'supplier')

    @api.onchange('journal_id', 'payment_method_line_id')
    def _onchange_cheque_journal(self):
        if not self.cheque_managed or self.cheque_book_id.journal_id != self.journal_id:
            self.cheque_book_id = False
            self.cheque_leaf_id = False

    @api.onchange('cheque_book_id')
    def _onchange_cheque_book(self):
        if self.cheque_leaf_id.book_id != self.cheque_book_id:
            self.cheque_leaf_id = False

    @api.constrains('cheque_leaf_id', 'cheque_book_id', 'journal_id', 'company_id', 'payment_method_line_id', 'payment_type', 'partner_type', 'currency_id', 'amount', 'cheque_date')
    def _check_cheque(self):
        for payment in self:
            if payment.cheque_leaf_id or payment.cheque_book_id:
                if not payment.cheque_managed or not payment.cheque_leaf_id or payment.cheque_leaf_id.book_id != payment.cheque_book_id or payment.cheque_book_id.journal_id != payment.journal_id:
                    raise ValidationError(_('Select a leaf from the selected journal and book for an outgoing vendor Checks payment.'))
                if payment.currency_id != payment.company_id.currency_id or (payment.journal_id.currency_id and payment.journal_id.currency_id != payment.company_id.currency_id) or payment.amount <= 0:
                    raise ValidationError(_('Managed cheques currently require a positive company-currency amount.'))
                if not payment.cheque_date or not payment.partner_id:
                    raise ValidationError(_('A vendor and cheque date are required.'))
            elif payment.cheque_managed:
                raise ValidationError(_('Select a cheque book, available leaf and cheque date.'))

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('cheque_leaf_id') and vals.get('state', 'draft') != 'draft' for vals in vals_list):
            raise UserError(_('Create a draft cheque payment and confirm it through the workflow.'))
        with operation(self, 'PAYMENT_CREATE'):
            leaves = self.env['account.cheque.leaf'].browse([vals['cheque_leaf_id'] for vals in vals_list if vals.get('cheque_leaf_id')])
            if leaves:
                require_group(leaves, 'group_cheque_user')
                # Lock before payment insertion acquires foreign-key key-share
                # locks, otherwise simultaneous reservations can deadlock.
                leaves._lock()
            payments = super(ChequePayment, self.with_context(_cheque_capability=TOKEN)).create(vals_list).with_env(self.env)
            for payment in payments.filtered(lambda p: p.cheque_leaf_id and p.state == 'in_process' and p.move_id.state == 'draft'):
                payment.with_context(_cheque_capability=TOKEN).write({'state': 'draft'})
            for payment in payments.filtered(lambda p: p.cheque_leaf_id and not p.cheque_attempt_ids):
                payment._reserve_cheque()
            return payments

    def _reserve_cheque(self):
        self.ensure_one()
        leaf = self.cheque_leaf_id
        require_group(leaf, 'group_cheque_user')
        leaf._lock()
        if leaf.book_id.state != 'active' or leaf.state != 'available':
            raise UserError(_('This leaf is unavailable or its book is not active. Choose another leaf.'))
        previous = leaf.attempt_ids
        attempt = self.env['account.cheque.attempt'].with_context(_cheque_capability=TOKEN).create({
            'leaf_id': leaf.id, 'payment_id': self.id, 'number': max(previous.mapped('number'), default=0) + 1,
        })
        leaf._set({'state': 'reserved', 'current_attempt_id': attempt.id}, 'reserved')

    def write(self, vals):
        protected = {'cheque_book_id', 'cheque_leaf_id', 'cheque_date', 'journal_id', 'company_id', 'partner_id', 'partner_type', 'payment_type', 'payment_method_line_id', 'amount', 'currency_id', 'date', 'destination_account_id', 'outstanding_account_id'}
        managed = self.filtered('cheque_leaf_id')
        if {'cheque_copy', 'cheque_copy_filename'}.intersection(vals):
            managed._check_cheque_copy_editable()
        if (self.env.context.get('_cheque_capability') is TOKEN
                and set(vals) == {'outstanding_account_id'}
                and all(payment.state == 'draft' and not payment.move_id for payment in managed)):
            protected.discard('outstanding_account_id')
        if vals.get('cheque_leaf_id') and not managed:
            leaves = self.env['account.cheque.leaf'].browse(vals['cheque_leaf_id'])
            require_group(leaves, 'group_cheque_user')
            leaves._lock()
        if 'move_id' in vals and any(payment.move_id and payment.move_id.id != vals['move_id'] for payment in managed):
            raise UserError(_('The accounting entry of a physical cheque cannot be replaced.'))
        if managed and protected.intersection(vals):
            if any(self._fields[key].type != 'many2one' and record[key] != vals[key] or self._fields[key].type == 'many2one' and record[key].id != (vals[key] or False) for record in managed for key in protected.intersection(vals)):
                raise UserError(_('Reserved cheque payment details are protected. Void the cheque and prepare another payment.'))
        if 'state' in vals and self.env.context.get('_cheque_capability') is not TOKEN:
            if managed.filtered(lambda p: p.state != vals['state']):
                raise UserError(_('Use the cheque confirmation or exception workflow to change this payment state.'))
        result = super().write(vals)
        # Also covers assigning a leaf to an existing ordinary draft payment.
        for payment in self.filtered(lambda p: p.cheque_leaf_id and not p.cheque_attempt_ids):
            payment._reserve_cheque()
        return result

    def unlink(self):
        if self.filtered('cheque_leaf_id'):
            raise UserError(_('Payments tied to physical leaves cannot be deleted.'))
        return super().unlink()

    @api.depends('journal_id', 'payment_method_line_id', 'cheque_leaf_id')
    def _compute_check_number(self):
        managed = self.filtered('cheque_leaf_id')
        super(ChequePayment, self - managed)._compute_check_number()
        for payment in managed:
            payment.check_number = payment.cheque_leaf_id.number

    def _inverse_check_number(self):
        managed = self.filtered('cheque_leaf_id')
        if any(payment.check_number != payment.cheque_leaf_id.number for payment in managed):
            raise ValidationError(_('The cheque number must match its reserved physical leaf.'))
        return super(ChequePayment, self - managed)._inverse_check_number()

    def action_post(self):
        managed = self.filtered('cheque_leaf_id')
        if not managed:
            return super().action_post()
        with operation(managed, 'PAYMENT_POST'):
            require_group(managed.cheque_leaf_id, 'group_cheque_accountant')
            managed.cheque_leaf_id._lock()
            for payment in managed:
                payment._check_cheque()
                payment._check_cheque_copy()
                payment._refresh_draft_cheque_outstanding_account()
                if payment.journal_id.cheque_separate_approval and payment.create_uid == self.env.user:
                    raise UserError(_('A different authorised accountant must approve this cheque payment.'))
                if payment.cheque_leaf_id.current_attempt_id.payment_id != payment or payment.cheque_leaf_id.state != 'reserved':
                    raise UserError(_('Only the current reserved cheque can be posted.'))
                if not payment.outstanding_account_id or payment.outstanding_account_id == payment.journal_id.default_account_id or not payment.outstanding_account_id.reconcile:
                    raise UserError(_('Configure a separate reconcilable outstanding-payments account on the Checks method.'))
                if payment.cheque_book_id.state != 'active':
                    raise UserError(_('The cheque book must be active.'))
            # Managed physical numbers do not use automatic journal sequencing.
            result = super(ChequePayment, self.with_context(_cheque_capability=TOKEN)).action_post()
            for payment in managed:
                if not payment.move_id or payment.move_id.state != 'posted':
                    raise UserError(_('The managed cheque must have a posted accounting entry.'))
                payment.cheque_leaf_id.current_attempt_id._lines()
                attempt = payment.cheque_leaf_id.current_attempt_id
                if attempt.planned_debt_ids:
                    payable = payment.move_id.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
                    debts = attempt.planned_debt_ids.filtered(lambda line: line.parent_state == 'posted' and not line.reconciled and line.account_id == payable.account_id and line.amount_residual < 0)
                    if payment.currency_id.compare_amounts(payment.amount, -sum(debts.mapped('amount_residual'))) > 0:
                        raise UserError(_('The original bills have changed. Review the cheque amount before approval.'))
                    (debts | payable).reconcile()
                payment.cheque_leaf_id.current_attempt_id._update({'state': 'pending', 'approved_by_id': self.env.uid, 'approved_date': fields.Datetime.now(), 'bank_code': payment.cheque_book_id.bank_code})
                payment.cheque_leaf_id._set({'state': 'issued'}, 'payment_posted')
            return result

    def _check_cheque_copy(self):
        for payment in self.filtered('cheque_leaf_id'):
            if not payment.with_context(bin_size=False).cheque_copy:
                raise UserError(_('Attach a copy of the completed cheque before confirming this payment.'))

    def _check_cheque_copy_editable(self):
        if not self:
            return
        self.cheque_leaf_id._lock()
        self.invalidate_recordset(['state', 'move_id'])
        if any(payment.state != 'draft' or payment.move_id.state == 'posted'
               or payment.cheque_attempt_ids.filtered(lambda attempt: attempt.state != 'reserved')
               for payment in self):
            raise UserError(_('The cheque copy is audit evidence and cannot be changed after confirmation or cancellation.'))

    def _refresh_draft_cheque_outstanding_account(self):
        """Core only depends on the method ID, not its configured account.

        A draft saved before journal setup can therefore retain a stale value.
        Refresh only before any accounting entry exists; preserve posted history.
        """
        self.ensure_one()
        if self.cheque_leaf_id and self.state == 'draft' and not self.move_id:
            account = self.payment_method_line_id.payment_account_id
            if self.outstanding_account_id != account:
                with operation(self, 'DRAFT_ACCOUNT_REFRESH'):
                    self.with_context(_cheque_capability=TOKEN).write({'outstanding_account_id': account.id})

    def print_checks(self):
        managed = self.filtered('cheque_leaf_id')
        if managed:
            if managed != self:
                raise UserError(_('Print managed and ordinary cheques separately.'))
            if any(p.state != 'in_process' or p.is_sent or p.cheque_leaf_id.current_attempt_id.payment_id != p for p in managed):
                raise UserError(_('Only current, posted, unsent cheques can be printed.'))
            with operation(managed, 'PRINT'):
                return managed.do_print_checks()
        return super().print_checks()

    def do_print_checks(self):
        managed = self.filtered('cheque_leaf_id')
        if managed:
            require_group(managed.cheque_leaf_id, 'group_cheque_user')
            managed.cheque_leaf_id._lock()
            if any(payment.is_sent or payment.cheque_leaf_id.current_attempt_id.payment_id != payment or payment.cheque_leaf_id.current_attempt_id.state != 'pending' for payment in managed):
                raise UserError(_('Only a current, approved, unsent cheque can be printed.'))
        return super().do_print_checks()
