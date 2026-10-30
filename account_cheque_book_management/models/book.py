from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .audit import TOKEN, operation, require_group


class ChequeJournal(models.Model):
    _inherit = 'account.journal'

    cheque_book_enabled = fields.Boolean(string='Manage Physical Cheque Books')
    cheque_book_ids = fields.One2many('account.cheque.book', 'journal_id')
    cheque_validity_days = fields.Integer(string='Cheque Validity (Days)', help='Company review policy. Zero leaves validity checks to the accountant.')
    cheque_separate_approval = fields.Boolean(string='Require Separate Preparer and Approver')

    @api.constrains('cheque_validity_days')
    def _check_validity(self):
        if any(journal.cheque_validity_days < 0 for journal in self):
            raise ValidationError(_('Cheque validity days cannot be negative.'))

    @api.constrains('cheque_book_enabled', 'type', 'bank_account_id')
    def _check_cheque_configuration(self):
        for journal in self.filtered('cheque_book_enabled'):
            if journal.type != 'bank' or not journal.bank_account_id:
                raise ValidationError(_('Cheque books require a bank journal with a company bank account.'))

    def write(self, vals):
        protected = {'bank_account_id', 'company_id', 'cheque_book_enabled', 'type'}.intersection(vals)
        if protected:
            with operation(self, 'JOURNAL_CONFIGURATION'):
                changed = self.filtered(lambda journal: any(
                    (journal[field].id if self._fields[field].type == 'many2one' else journal[field])
                    != (vals[field] or False)
                    for field in protected
                ))
                if changed and self.env['account.cheque.book'].search_count([
                    ('journal_id', 'in', changed.ids), ('state', '!=', 'draft'),
                ]):
                    raise UserError(_('Bank identity and cheque management cannot change after book activation.'))
                return super().write(vals)
        return super().write(vals)


class ChequeBook(models.Model):
    _name = 'account.cheque.book'
    _description = 'Company Cheque Book'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    journal_id = fields.Many2one('account.journal', required=True, check_company=True, ondelete='restrict', domain="[('type','=','bank'),('company_id','=',company_id),('cheque_book_enabled','=',True)]")
    bank_account_id = fields.Many2one(related='journal_id.bank_account_id', store=True)
    bank_code = fields.Char(string='Bank Code', tracking=True,
        help='Bank/branch code exactly as printed on this cheque book. Preserve leading zeros and separators; this is not the account number or SWIFT code.')
    first_number = fields.Char(required=True)
    leaf_count = fields.Integer(required=True)
    last_number = fields.Char(compute='_compute_last_number')
    received_date = fields.Date(default=fields.Date.context_today, required=True)
    custodian_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user)
    state = fields.Selection([('draft', 'Draft'), ('active', 'Active'), ('suspended', 'Suspended'), ('closed', 'Closed')], default='draft', readonly=True, tracking=True)
    leaf_ids = fields.One2many('account.cheque.leaf', 'book_id', readonly=True)
    available_count = fields.Integer(compute='_compute_counts')
    outstanding_count = fields.Integer(compute='_compute_counts')

    @api.depends('first_number', 'leaf_count')
    def _compute_last_number(self):
        for book in self:
            book.last_number = str(int(book.first_number) + book.leaf_count - 1).zfill(len(book.first_number)) if book.first_number and book.first_number.isascii() and book.first_number.isdecimal() and book.leaf_count > 0 else False

    @api.depends('leaf_ids.state')
    def _compute_counts(self):
        for book in self:
            book.available_count = len(book.leaf_ids.filtered(lambda leaf: leaf.state == 'available'))
            book.outstanding_count = len(book.leaf_ids.filtered(lambda leaf: leaf.state in ('reserved', 'issued', 'returned', 'review')))

    @api.constrains('first_number', 'leaf_count', 'journal_id', 'company_id')
    def _check_range(self):
        for book in self:
            if not book.first_number or not book.first_number.isascii() or not book.first_number.isdecimal() or book.leaf_count <= 0:
                raise ValidationError(_('Enter a numeric first cheque number and a positive number of leaves.'))
            if not book.journal_id.cheque_book_enabled or book.journal_id.bank_account_id.partner_id != book.company_id.partner_id:
                raise ValidationError(_('Select a cheque-enabled journal with a bank account owned by this company.'))

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('state', 'draft') != 'draft' or vals.get('leaf_ids') for vals in vals_list):
            raise UserError(_('Create a draft book and activate it to generate leaves.'))
        with operation(self, 'BOOK_CREATE'):
            return super().create(vals_list)

    def write(self, vals):
        if 'bank_code' in vals and any(book.bank_code != (vals['bank_code'] or False) for book in self):
            require_group(self, 'group_cheque_manager')
            with operation(self, 'BOOK_BANK_CODE'):
                return self._write_book_values(vals)
        return self._write_book_values(vals)

    def _write_book_values(self, vals):
        if 'state' in vals and self.env.context.get('_cheque_capability') is not TOKEN:
            raise UserError(_('Use the book workflow buttons.'))
        if 'leaf_ids' in vals or (self.filtered(lambda b: b.state != 'draft') and {'journal_id', 'company_id', 'first_number', 'leaf_count'}.intersection(vals)):
            raise UserError(_('An activated book range and bank identity cannot be edited.'))
        return super().write(vals)

    def unlink(self):
        if any(book.state != 'draft' for book in self):
            raise UserError(_('Activated cheque books cannot be deleted.'))
        return super().unlink()

    def _lock(self):
        self.check_access('write')
        self.env.cr.execute('SELECT id FROM account_cheque_book WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
        self.invalidate_recordset()

    def action_activate(self):
        require_group(self, 'group_cheque_manager')
        with operation(self, 'BOOK_ACTIVATE'):
            self._lock()
            for book in self:
                if book.state != 'draft':
                    continue
                book._check_range()
                # Serialize across journals pointing at the same bank account.
                self.env.cr.execute('SELECT id FROM res_partner_bank WHERE id=%s FOR UPDATE', [book.bank_account_id.id])
                start = int(book.first_number)
                keys = [str(number) for number in range(start, start + book.leaf_count)]
                if self.env['account.cheque.leaf'].search_count([('company_id', '=', book.company_id.id), ('bank_account_id', '=', book.bank_account_id.id), ('number_key', 'in', keys)]):
                    raise ValidationError(_('This range overlaps an existing cheque book for the bank account.'))
                self.env['account.cheque.leaf'].with_context(_cheque_capability=TOKEN).create([
                    {'book_id': book.id, 'number': str(number).zfill(len(book.first_number)), 'number_key': str(number)}
                    for number in range(start, start + book.leaf_count)
                ])
                book.with_context(_cheque_capability=TOKEN).state = 'active'
        return True

    def action_suspend(self):
        return self._change_state('suspended', ('active',))

    def action_resume(self):
        return self._change_state('active', ('suspended',))

    def action_close(self):
        return self._change_state('closed', ('active', 'suspended'))

    def _change_state(self, state, sources):
        require_group(self, 'group_cheque_manager')
        with operation(self, 'BOOK_STATE'):
            self._lock()
            if any(book.state not in sources for book in self):
                raise UserError(_('This book transition is not permitted.'))
            self.with_context(_cheque_capability=TOKEN).write({'state': state})
        return True


class ChequeLeaf(models.Model):
    _name = 'account.cheque.leaf'
    _description = 'Physical Cheque Leaf'
    _inherit = ['mail.thread']
    _rec_name = 'number'
    _order = 'book_id, id'
    _check_company_auto = True

    book_id = fields.Many2one('account.cheque.book', required=True, ondelete='restrict', check_company=True, index=True)
    company_id = fields.Many2one(related='book_id.company_id', store=True, index=True)
    journal_id = fields.Many2one(related='book_id.journal_id', store=True)
    bank_account_id = fields.Many2one(related='book_id.bank_account_id', store=True)
    number = fields.Char(required=True, readonly=True)
    number_key = fields.Char(required=True, readonly=True)
    state = fields.Selection([('available', 'Available'), ('reserved', 'Reserved'), ('issued', 'Issued / Uncleared'), ('cleared', 'Cleared'), ('returned', 'Returned'), ('damaged', 'Damaged'), ('cancelled', 'Cancelled'), ('replaced', 'Replaced'), ('review', 'Review Required')], default='available', readonly=True, tracking=True, index=True)
    attempt_ids = fields.One2many('account.cheque.attempt', 'leaf_id', readonly=True)
    current_attempt_id = fields.Many2one('account.cheque.attempt', readonly=True, ondelete='restrict', check_company=True)
    partner_id = fields.Many2one(related='current_attempt_id.partner_id', store=True)
    amount = fields.Monetary(related='current_attempt_id.amount', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id', store=True)
    replacement_for_id = fields.Many2one('account.cheque.leaf', readonly=True, check_company=True, ondelete='restrict')
    event_ids = fields.One2many('account.cheque.event', 'leaf_id', readonly=True)

    _sql_constraints = [('bank_number_unique', 'unique(company_id, bank_account_id, number_key)', 'This cheque number already exists for this bank account, possibly in another book.')]

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_cheque_capability') is not TOKEN:
            raise UserError(_('Leaves are generated when a cheque book is activated.'))
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('_cheque_capability') is not TOKEN:
            raise UserError(_('Use a cheque workflow action to change a leaf.'))
        if {'book_id', 'number', 'number_key', 'company_id', 'bank_account_id', 'journal_id'}.intersection(vals):
            raise UserError(_('A physical cheque identity cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        raise UserError(_('Cheque leaves are permanent audit records.'))

    def _lock(self):
        self.book_id._lock()
        self.check_access('write')
        self.env.cr.execute('SELECT id FROM account_cheque_leaf WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
        self.invalidate_recordset()

    def _set(self, vals, action, note=False):
        self.ensure_one()
        self.with_context(_cheque_capability=TOKEN).write(vals)
        self.env['account.cheque.event'].with_context(_cheque_capability=TOKEN).create({
            'leaf_id': self.id, 'action': action, 'note': note,
        })

    def action_workflow(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Cheque Action'), 'res_model': 'account.cheque.workflow', 'view_mode': 'form', 'target': 'new', 'context': {'default_leaf_id': self.id}}


class ChequeEvent(models.Model):
    _name = 'account.cheque.event'
    _description = 'Cheque Lifecycle Event'
    _order = 'id desc'
    _check_company_auto = True

    leaf_id = fields.Many2one('account.cheque.leaf', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='leaf_id.company_id', store=True)
    action = fields.Char(required=True, readonly=True)
    note = fields.Text(readonly=True)
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_cheque_capability') is not TOKEN:
            raise UserError(_('Events are recorded by the cheque workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Cheque events cannot be edited.'))

    def unlink(self):
        raise UserError(_('Cheque events cannot be deleted.'))
