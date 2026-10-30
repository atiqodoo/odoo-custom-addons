from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ChequePaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    cheque_managed = fields.Boolean(compute='_compute_cheque_managed')
    cheque_book_id = fields.Many2one('account.cheque.book', check_company=True)
    cheque_leaf_id = fields.Many2one('account.cheque.leaf', check_company=True)
    cheque_date = fields.Date(default=fields.Date.context_today)
    cheque_copy = fields.Binary(string='Completed Cheque Copy', attachment=False)
    cheque_copy_filename = fields.Char()

    @api.depends('journal_id.cheque_book_enabled', 'payment_method_code', 'payment_type', 'partner_type')
    def _compute_cheque_managed(self):
        for wizard in self:
            wizard.cheque_managed = bool(wizard.journal_id.cheque_book_enabled and wizard.payment_method_code == 'check_printing' and wizard.payment_type == 'outbound' and wizard.partner_type == 'supplier')

    @api.onchange('journal_id', 'payment_method_line_id')
    def _onchange_cheque_journal(self):
        if not self.cheque_managed or self.cheque_book_id.journal_id != self.journal_id:
            self.cheque_book_id = False
            self.cheque_leaf_id = False

    @api.onchange('cheque_book_id')
    def _onchange_cheque_book(self):
        if self.cheque_leaf_id.book_id != self.cheque_book_id:
            self.cheque_leaf_id = False

    def _init_payments(self, to_process, edit_mode=False):
        self.ensure_one()
        if self.cheque_managed:
            if len(to_process) != 1:
                raise UserError(_('One selected leaf can fund only one payment. Group eligible bills for the same vendor, or pay each vendor/payment separately.'))
            if not self.cheque_book_id or not self.cheque_leaf_id or not self.cheque_date:
                raise UserError(_('Select a cheque book, available leaf and cheque date.'))
            if not self.cheque_copy:
                raise UserError(_('Attach a copy of the completed cheque before creating its payment.'))
            to_process[0]['create_vals'].update({
                'cheque_book_id': self.cheque_book_id.id,
                'cheque_leaf_id': self.cheque_leaf_id.id,
                'cheque_date': self.cheque_date,
                'cheque_copy': self.with_context(bin_size=False).cheque_copy,
                'cheque_copy_filename': self.cheque_copy_filename,
            })
            if self.journal_id.cheque_separate_approval:
                debts = to_process[0]['to_reconcile']
                self.cheque_leaf_id._lock()
                # Serialise draft commitments for the same payable lines.
                self.env.cr.execute('SELECT id FROM account_move_line WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(debts.ids)])
                if self.env['account.cheque.attempt'].search_count([('state', '=', 'reserved'), ('planned_debt_ids', 'in', debts.ids), ('leaf_id.state', '=', 'reserved')]):
                    raise UserError(_('These bills already have a cheque awaiting approval. Resolve that request before preparing another cheque.'))
        payments = super()._init_payments(to_process, edit_mode=edit_mode)
        for values in to_process:
            payment = values['payment']
            if payment.cheque_managed and payment.journal_id.cheque_separate_approval:
                payment.cheque_leaf_id.current_attempt_id._update({'planned_debt_ids': [(6, 0, values['to_reconcile'].ids)]})
        return payments

    def _post_payments(self, to_process, edit_mode=False):
        ready = [values for values in to_process if not (values['payment'].cheque_managed and values['payment'].journal_id.cheque_separate_approval)]
        return super()._post_payments(ready, edit_mode=edit_mode)

    def _reconcile_payments(self, to_process, edit_mode=False):
        ready = [values for values in to_process if values['payment'].move_id.state == 'posted']
        return super()._reconcile_payments(ready, edit_mode=edit_mode)
