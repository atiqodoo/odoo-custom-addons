from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .audit import operation, require_group


class ChequeFee(models.Model):
    _name = 'account.cheque.fee'
    _description = 'Actual Outgoing Cheque Bank Fee or Refund'
    _check_company_auto = True

    attempt_id = fields.Many2one('account.cheque.attempt', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='attempt_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    statement_id = fields.Many2one('account.bank.statement.line', required=True, check_company=True, ondelete='restrict')
    kind = fields.Selection([('charge', 'Bank Charge'), ('refund', 'Fee Refund')], required=True, default='charge')
    refund_of_id = fields.Many2one('account.cheque.fee', check_company=True, ondelete='restrict')
    amount = fields.Monetary(compute='_compute_amount')

    _sql_constraints = [('statement_unique', 'unique(statement_id)', 'This bank transaction is already registered as a cheque fee or refund.')]

    @api.depends('statement_id.amount')
    def _compute_amount(self):
        for fee in self:
            fee.amount = abs(fee.statement_id.amount)

    def _validate_evidence(self):
        for fee in self:
            statement = fee.statement_id
            if statement.company_id != fee.company_id or statement.journal_id != fee.attempt_id.payment_id.journal_id or statement.move_id.state != 'posted' or not statement.is_reconciled or statement.move_id.reversal_move_ids.filtered(lambda m: m.state == 'posted'):
                raise ValidationError(_('Select a posted, reconciled bank fee transaction from the cheque bank journal.'))
            if statement.currency_id != fee.currency_id:
                raise ValidationError(_('Cheque fees currently require company currency.'))
            other = statement.move_id.line_ids.filtered(lambda line: line.account_id != statement.journal_id.default_account_id)
            if not other or other.filtered(lambda line: line.account_id.internal_group != 'expense' and not line.tax_repartition_line_id):
                raise ValidationError(_('Fee transactions must contain expenses and their tax lines only, without cheque principal.'))
            if fee.kind == 'charge':
                if statement.amount >= 0 or fee.refund_of_id:
                    raise ValidationError(_('A bank charge must be a negative expense transaction.'))
            else:
                original = fee.refund_of_id
                if statement.amount <= 0 or not original or original.kind != 'charge' or original.attempt_id != fee.attempt_id:
                    raise ValidationError(_('Select the original charge for this attempt and a positive fee refund.'))
                original._validate_evidence()
                refunds = self.search([('refund_of_id', '=', original.id)])
                if fee.currency_id.compare_amounts(sum(refunds.mapped('amount')), original.amount) > 0:
                    raise ValidationError(_('Fee refunds cannot exceed the original charge.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group('account_cheque_book_management.group_cheque_accountant'):
            raise UserError(_('A Cheque Book Accountant must register bank fees.'))
        with operation(self, 'FEE_REGISTER'):
            # Lock attempts before checking cumulative refunds.
            attempts = self.env['account.cheque.attempt'].browse([vals['attempt_id'] for vals in vals_list])
            require_group(attempts, 'group_cheque_accountant')
            attempts.leaf_id._lock()
            fees = super().create(vals_list)
            fees._validate_evidence()
            return fees

    def write(self, vals):
        raise UserError(_('Fee evidence is immutable. Correct bank accounting through its normal workflow.'))

    def unlink(self):
        raise UserError(_('Cheque fee history cannot be deleted.'))
