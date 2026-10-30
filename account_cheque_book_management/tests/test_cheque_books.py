import base64

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged, new_test_user, Form
from unittest.mock import patch
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestChequeBooks(AccountTestInvoicingCommon):
    CHEQUE_COPY = base64.b64encode(b'%PDF-1.4\nTest completed cheque copy\n%%EOF')
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.write({'groups_id': [Command.link(cls.env.ref('account_cheque_book_management.group_cheque_manager').id)]})
        cls.bank = cls.company_data['default_journal_bank']
        cls.bank.bank_account_id = cls.env['res.partner.bank'].create({'acc_number': 'CHEQUE-TEST-ACCOUNT', 'partner_id': cls.env.company.partner_id.id, 'company_id': cls.env.company.id})
        cls.bank.cheque_book_enabled = True
        cls.method = cls.bank.outbound_payment_method_line_ids.filtered(lambda m: m.code == 'check_printing')
        if not cls.method:
            cls.method = cls.env['account.payment.method.line'].create({'journal_id': cls.bank.id, 'payment_method_id': cls.env.ref('account_check_printing.account_payment_method_check').id})
        cls.outstanding = cls.env['account.account'].create({'name': 'Outstanding test cheques', 'code': 'CHQOUT', 'account_type': 'liability_current', 'reconcile': True})
        cls.method.payment_account_id = cls.outstanding
        cls.vendor = cls.env['res.partner'].create({'name': 'Cheque test vendor'})
        cls.reason = cls.env['account.cheque.reason'].create({'name': 'Technical return', 'allow_represent': True})

    def _book(self, first='004501', count=5, activate=True):
        book = self.env['account.cheque.book'].create({'name': 'Test book', 'journal_id': self.bank.id, 'first_number': first, 'leaf_count': count})
        if activate:
            book.action_activate()
        return book

    def _payment(self, leaf, amount=100):
        return self.env['account.payment'].create({'partner_id': self.vendor.id, 'payment_type': 'outbound', 'partner_type': 'supplier', 'journal_id': self.bank.id, 'payment_method_line_id': self.method.id, 'amount': amount, 'cheque_book_id': leaf.book_id.id, 'cheque_leaf_id': leaf.id, 'cheque_date': fields.Date.today(), 'cheque_copy': self.CHEQUE_COPY, 'cheque_copy_filename': 'completed-cheque.pdf'})

    def _action(self, leaf, action, **values):
        if action in ('represent', 'replace'):
            values.setdefault('cheque_copy', self.CHEQUE_COPY)
            values.setdefault('cheque_copy_filename', 'completed-cheque.pdf')
        return self.env['account.cheque.workflow'].create({'leaf_id': leaf.id, 'action': action, 'note': 'Test audit evidence', **values}).action_apply()

    def _bill(self, amount=100):
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'partner_id': self.vendor.id, 'invoice_date': fields.Date.today(), 'invoice_line_ids': [Command.create({'name': 'Goods', 'quantity': 1, 'price_unit': amount, 'account_id': self.company_data['default_account_expense'].id, 'tax_ids': [Command.clear()]})]})
        bill.action_post()
        return bill

    def _statement(self, amount, account=None):
        return self.env['account.bank.statement.line'].create({'journal_id': self.bank.id, 'amount': amount, 'payment_ref': 'Cheque test evidence', 'partner_id': self.vendor.id, 'counterpart_account_id': (account or self.outstanding).id})

    def _pay_bill(self, bill, leaf):
        register = self.env['account.payment.register'].with_context(active_model='account.move', active_ids=bill.ids).create({'journal_id': self.bank.id, 'payment_method_line_id': self.method.id, 'cheque_book_id': leaf.book_id.id, 'cheque_leaf_id': leaf.id, 'cheque_date': fields.Date.today(), 'cheque_copy': self.CHEQUE_COPY, 'cheque_copy_filename': 'completed-cheque.pdf', 'group_payment': True})
        return register._create_payments()

    def test_book_generation_and_identity(self):
        book = self._book()
        self.assertEqual(book.leaf_ids.mapped('number'), ['004501', '004502', '004503', '004504', '004505'])
        self.assertEqual(book.available_count, 5)
        book.action_activate()
        self.assertEqual(len(book.leaf_ids), 5)
        with self.assertRaises(UserError):
            book.first_number = '999'
        with self.assertRaises(UserError):
            book.leaf_ids[0].state = 'cleared'
        with self.assertRaises(UserError):
            book.unlink()

    def test_overlapping_range_and_invalid_size(self):
        self._book()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._book('4502')
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._book(count=0)

    def test_activated_book_allows_unchanged_journal_identity(self):
        book = self._book()
        self.bank.write({
            'bank_account_id': self.bank.bank_account_id.id,
            'company_id': self.bank.company_id.id,
            'cheque_book_enabled': True,
            'type': 'bank',
            'cheque_validity_days': 30,
        })
        self.assertEqual(self.bank.cheque_validity_days, 30)
        self.assertEqual(book.state, 'active')
        self.assertEqual(len(book.leaf_ids), 5)

    def test_activated_book_still_blocks_actual_identity_changes(self):
        self._book()
        for values in (
            {'bank_account_id': False},
            {'cheque_book_enabled': False},
            {'type': 'cash'},
        ):
            with self.subTest(values=values), self.assertRaises(UserError):
                self.bank.write(values)

    def test_batch_journal_save_checks_only_changed_records(self):
        self._book()
        account = self.env['res.partner.bank'].create({
            'acc_number': 'OTHER-CHEQUE-TEST-ACCOUNT',
            'partner_id': self.env.company.partner_id.id,
        })
        other = self.env['account.journal'].create({
            'name': 'Other cheque bank', 'code': 'CHQ2', 'type': 'bank',
            'bank_account_id': account.id,
        })
        (self.bank | other).write({'cheque_book_enabled': True})
        self.assertTrue(other.cheque_book_enabled)

    def test_leaf_reservation_and_number(self):
        book = self._book()
        payment = self._payment(book.leaf_ids[0])
        self.assertEqual(payment.check_number, '004501')
        self.assertEqual(book.leaf_ids[0].state, 'reserved')
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._payment(book.leaf_ids[0])
        payment.action_post()
        self.assertEqual(book.leaf_ids[0].state, 'issued')
        self.assertEqual(payment.check_number, '004501')
        with self.assertRaises(UserError):
            payment.amount = 200
        with self.assertRaises(UserError):
            payment.action_draft()

    def test_grouped_bills_one_leaf(self):
        book = self._book()
        bills = self._bill(60) | self._bill(40)
        payment = self._pay_bill(bills, book.leaf_ids[0])
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.amount, 100)
        self.assertEqual(bills.mapped('amount_residual'), [0, 0])

    def test_return_reopens_only_failed_payment_and_retry(self):
        leaf = self._book().leaf_ids[0]
        bill = self._bill()
        payment = self._pay_bill(bill, leaf)
        self._action(leaf, 'report', reason_id=self.reason.id)
        self._action(leaf, 'correct')
        self.assertEqual(bill.amount_residual, 100)
        reversal = leaf.current_attempt_id.reversal_move_id
        self._action(leaf, 'correct')
        self.assertEqual(leaf.current_attempt_id.reversal_move_id, reversal)
        self._action(leaf, 'represent')
        self.assertEqual(len(leaf.attempt_ids), 2)
        self.assertEqual(bill.amount_residual, 0)
        self.assertNotEqual(leaf.current_attempt_id.payment_id, payment)

    def test_replacement_and_physical_safeguard(self):
        book = self._book()
        old, new = book.leaf_ids[:2]
        bill = self._bill()
        self._pay_bill(bill, old)
        self._action(old, 'report', reason_id=self.reason.id)
        self._action(old, 'correct')
        with self.assertRaises(UserError):
            self._action(old, 'replace', replacement_leaf_id=new.id, replacement_amount=100)
        self._action(old, 'replace', replacement_leaf_id=new.id, replacement_amount=100, instrument_recovered=True)
        self.assertEqual(old.state, 'replaced')
        self.assertEqual(new.replacement_for_id, old)
        self.assertEqual(bill.amount_residual, 0)

    def test_damage_and_unverified_clearance(self):
        book = self._book()
        self._action(book.leaf_ids[0], 'damage')
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._payment(book.leaf_ids[0])
        payment = self._payment(book.leaf_ids[1])
        payment.action_post()
        with self.assertRaises(UserError):
            self._action(book.leaf_ids[1], 'clear')

    def test_operator_cannot_post_or_correct(self):
        operator = new_test_user(self.env, login='cheque_operator_test', groups='account_cheque_book_management.group_cheque_user', company_id=self.env.company.id)
        leaf = self._book().leaf_ids[0]
        payment = self._payment(leaf)
        with self.assertRaises(AccessError):
            payment.with_user(operator).action_post()

    def test_company_and_journal_mismatch(self):
        leaf = self._book().leaf_ids[0]
        other_company = self.env['res.company'].create({'name': 'Isolated cheque company'})
        outsider = new_test_user(self.env, login='cheque_other_company_test', groups='account_cheque_book_management.group_cheque_manager', company_id=other_company.id, company_ids=[Command.set(other_company.ids)])
        with self.assertRaises(AccessError):
            leaf.with_user(outsider).with_context(allowed_company_ids=other_company.ids).read(['number'])
        payment = self._payment(leaf)
        with self.assertRaises(UserError):
            payment.write({'journal_id': self.company_data['default_journal_cash'].id})

    def test_views_compile(self):
        for model in ('account.cheque.book', 'account.cheque.leaf', 'account.cheque.attempt', 'account.cheque.workflow', 'account.cheque.fee', 'account.payment', 'account.payment.register', 'account.journal'):
            self.env[model].get_views([(False, 'form')], {})

    def test_bank_clearance_return_and_evidence_change(self):
        leaf = self._book().leaf_ids[0]
        bill = self._bill()
        payment = self._pay_bill(bill, leaf)
        debit = self._statement(-100)
        liquidity = payment.move_id.line_ids.filtered(lambda line: line.account_id == self.outstanding)
        evidence = debit.move_id.line_ids.filtered(lambda line: line.account_id == self.outstanding)
        (liquidity | evidence).reconcile()
        self._action(leaf, 'clear', statement_id=debit.id)
        self.assertEqual(leaf.state, 'cleared')
        # Evidence rechecks must not produce additional postings.
        count = self.env['account.move'].search_count([])
        liquidity.remove_move_reconcile()
        self.env['account.cheque.attempt']._cron_review_evidence()
        self.assertEqual(leaf.state, 'review')
        self.assertEqual(self.env['account.move'].search_count([]), count)
        (liquidity | evidence).reconcile()
        self._action(leaf, 'clear', statement_id=debit.id)
        self._action(leaf, 'report', reason_id=self.reason.id)
        with self.assertRaises(UserError):
            self._action(leaf, 'correct')
        self.assertEqual(bill.amount_residual, 0)
        refund = self._statement(100)
        self._action(leaf, 'correct', statement_id=refund.id)
        self.assertEqual(bill.amount_residual, 100)
        self.assertTrue(leaf.current_attempt_id.reversal_move_id)

    def test_fees_and_refunds_cannot_clear_principal(self):
        leaf = self._book().leaf_ids[0]
        payment = self._payment(leaf)
        payment.action_post()
        attempt = leaf.current_attempt_id
        charge = self._statement(-10, self.company_data['default_account_expense'])
        fee = self.env['account.cheque.fee'].create({'attempt_id': attempt.id, 'statement_id': charge.id})
        refund = self._statement(6, self.company_data['default_account_expense'])
        self.env['account.cheque.fee'].create({'attempt_id': attempt.id, 'statement_id': refund.id, 'kind': 'refund', 'refund_of_id': fee.id})
        excess = self._statement(5, self.company_data['default_account_expense'])
        with self.assertRaises(ValidationError):
            self.env['account.cheque.fee'].create({'attempt_id': attempt.id, 'statement_id': excess.id, 'kind': 'refund', 'refund_of_id': fee.id})
        with self.assertRaises(UserError):
            self._action(leaf, 'clear', statement_id=refund.id)
        self.assertEqual(leaf.state, 'issued')

    def test_failure_rolls_back_reconciliation(self):
        leaf = self._book().leaf_ids[0]
        bill = self._bill()
        self._pay_bill(bill, leaf)
        self._action(leaf, 'report', reason_id=self.reason.id)
        with patch.object(type(self.env['account.move']), '_reverse_moves', side_effect=UserError('Test posting failure')):
            with self.assertRaises(UserError):
                self._action(leaf, 'correct')
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(leaf.current_attempt_id.state, 'reported')
        self.assertFalse(leaf.current_attempt_id.reversal_move_id)

    def test_sign_handover_stop_and_void(self):
        leaf = self._book().leaf_ids[0]
        payment = self._payment(leaf)
        payment.action_post()
        with self.assertRaises(UserError):
            self._action(leaf, 'deliver', reference='Vendor acknowledgement')
        self._action(leaf, 'sign')
        self._action(leaf, 'deliver', reference='Vendor acknowledgement')
        self._action(leaf, 'stop_request')
        self._action(leaf, 'stop_confirm', reference='Bank confirmation')
        self._action(leaf, 'void')
        self.assertEqual(leaf.state, 'cancelled')
        self.assertTrue(leaf.current_attempt_id.reversal_move_id)

    def test_unrelated_partial_payment_survives_return(self):
        leaf = self._book().leaf_ids[0]
        bill = self._bill(150)
        payment = self._payment(leaf, 100)
        payment.action_post()
        payable = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        source = payment.move_id.line_ids.filtered(lambda line: line.account_id == payable.account_id)
        (payable | source).reconcile()
        other = self.env['account.payment'].create({'partner_id': self.vendor.id, 'payment_type': 'outbound', 'partner_type': 'supplier', 'journal_id': self.bank.id, 'payment_method_line_id': self.bank.outbound_payment_method_line_ids.filtered(lambda method: method.code == 'manual')[:1].id, 'amount': 50, 'outstanding_account_id': self.outstanding.id})
        other.action_post()
        other_payable = other.move_id.line_ids.filtered(lambda line: line.account_id == payable.account_id)
        (payable | other_payable).reconcile()
        self._action(leaf, 'report', reason_id=self.reason.id)
        self._action(leaf, 'correct')
        self.assertEqual(bill.amount_residual, 100)
        self.assertTrue(other_payable.reconciled)

    def test_multiple_payments_cannot_share_leaf(self):
        leaf = self._book().leaf_ids[0]
        bills = self._bill(60) | self._bill(40)
        register = self.env['account.payment.register'].with_context(active_model='account.move', active_ids=bills.ids).create({'journal_id': self.bank.id, 'payment_method_line_id': self.method.id, 'cheque_book_id': leaf.book_id.id, 'cheque_leaf_id': leaf.id, 'cheque_date': fields.Date.today(), 'cheque_copy': self.CHEQUE_COPY, 'cheque_copy_filename': 'completed-cheque.pdf', 'group_payment': False})
        with self.assertRaises(UserError):
            register._create_payments()
        self.assertEqual(leaf.state, 'available')

    def test_payment_form_selects_physical_leaf(self):
        leaf = self._book().leaf_ids[0]
        with Form(self.env['account.payment'].with_context(default_payment_type='outbound', default_partner_type='supplier')) as form:
            form.partner_id = self.vendor
            form.journal_id = self.bank
            form.payment_method_line_id = self.method
            form.amount = 100
            form.cheque_book_id = leaf.book_id
            form.cheque_leaf_id = leaf
            form.cheque_date = fields.Date.today()
            form.cheque_copy = self.CHEQUE_COPY
        self.assertEqual(form.record.cheque_leaf_id, leaf)
        self.assertEqual(form.record.check_number, leaf.number)

    def test_cheque_copy_required_before_confirmation(self):
        payment = self._payment(self._book().leaf_ids[0])
        payment.write({'cheque_copy': False})
        with self.assertRaisesRegex(UserError, 'Attach a copy'):
            payment.action_post()
        self.assertEqual(payment.state, 'draft')
        self.assertFalse(payment.move_id)
        self.assertEqual(payment.cheque_leaf_id.state, 'reserved')
        payment.write({'cheque_copy': self.CHEQUE_COPY, 'cheque_copy_filename': 'completed.pdf'})
        payment.action_post()
        self.assertEqual(payment.move_id.state, 'posted')

    def test_bill_wizard_missing_copy_does_not_reserve_leaf(self):
        leaf = self._book().leaf_ids[0]
        bill = self._bill()
        wizard = self.env['account.payment.register'].with_context(active_model='account.move', active_ids=bill.ids).create({
            'journal_id': self.bank.id, 'payment_method_line_id': self.method.id,
            'cheque_book_id': leaf.book_id.id, 'cheque_leaf_id': leaf.id,
            'cheque_date': fields.Date.today(), 'group_payment': True,
        })
        with self.assertRaisesRegex(UserError, 'Attach a copy'):
            wizard._create_payments()
        self.assertEqual(leaf.state, 'available')
        self.assertEqual(bill.amount_residual, 100)

    def test_bill_wizard_transfers_copy_to_payment(self):
        payment = self._pay_bill(self._bill(), self._book().leaf_ids[0])
        self.assertEqual(payment.with_context(bin_size=False).cheque_copy, self.CHEQUE_COPY)
        self.assertEqual(payment.cheque_copy_filename, 'completed-cheque.pdf')

    def _copy_attachment(self, payment):
        return self.env['ir.attachment'].search([
            ('res_model', '=', 'account.payment'), ('res_id', '=', payment.id),
            ('res_field', '=', 'cheque_copy'),
        ])

    def test_confirmed_copy_cannot_be_changed_deleted_or_rebound(self):
        payment = self._payment(self._book().leaf_ids[0])
        payment.action_post()
        attachment = self._copy_attachment(payment)
        self.assertEqual(len(attachment), 1)
        self.assertFalse(attachment.public)
        with self.assertRaises(UserError):
            payment.write({'cheque_copy': False})
        with self.assertRaises(UserError):
            payment.write({'cheque_copy_filename': 'changed.pdf'})
        with self.assertRaises(UserError):
            attachment.unlink()
        with self.assertRaises(UserError):
            attachment.write({'res_field': False})
        with self.assertRaises(UserError):
            attachment.write({'datas': base64.b64encode(b'changed')})
        unrelated = self.env['ir.attachment'].create({'name': 'Other document', 'datas': self.CHEQUE_COPY})
        with self.assertRaises(UserError):
            unrelated.write({'res_model': 'account.payment', 'res_id': payment.id, 'res_field': 'cheque_copy'})
        with self.assertRaises(UserError):
            self.env['ir.attachment'].create({'name': 'Extra copy', 'datas': self.CHEQUE_COPY,
                'res_model': 'account.payment', 'res_id': payment.id, 'res_field': 'cheque_copy'})

    def test_draft_copy_is_private_and_can_be_replaced(self):
        payment = self._payment(self._book().leaf_ids[0])
        attachment = self._copy_attachment(payment)
        with self.assertRaises(UserError):
            attachment.write({'public': True})
        with self.assertRaises(UserError):
            attachment.write({'access_token': 'test-share-token'})
        attachment.unlink()
        payment.invalidate_recordset(['cheque_copy'])
        with self.assertRaises(UserError):
            payment.action_post()
        payment.cheque_copy = self.CHEQUE_COPY
        payment.action_post()

    def test_replacement_requires_its_own_uploaded_copy(self):
        book = self._book()
        old, new = book.leaf_ids[:2]
        payment = self._payment(old)
        payment.action_post()
        self._action(old, 'report', reason_id=self.reason.id)
        self._action(old, 'correct')
        with self.assertRaisesRegex(UserError, 'Attach a copy'):
            self._action(old, 'replace', replacement_leaf_id=new.id, replacement_amount=100,
                instrument_recovered=True, cheque_copy=False)
        self.assertEqual(new.state, 'available')
        self.assertEqual(old.state, 'returned')

    def test_bank_code_preserves_zeros_and_confirmation_history(self):
        book = self._book()
        book.bank_code = '01-286'
        self.assertEqual(book.bank_code, '01-286')
        payment = self._payment(book.leaf_ids[0])
        payment.action_post()
        self.assertEqual(payment.cheque_leaf_id.current_attempt_id.bank_code, '01-286')
        book.bank_code = '01-287'
        self.assertEqual(payment.cheque_leaf_id.current_attempt_id.bank_code, '01-286')
        operator = new_test_user(self.env, login='bank_code_operator_test', groups='account_cheque_book_management.group_cheque_user', company_id=self.env.company.id)
        with self.assertRaises(AccessError):
            book.with_user(operator).write({'bank_code': 'other'})

    def test_other_company_cannot_read_cheque_copy(self):
        payment = self._payment(self._book().leaf_ids[0])
        other_company = self.env['res.company'].create({'name': 'Copy isolation company'})
        outsider = new_test_user(self.env, login='cheque_copy_other_company', groups='account_cheque_book_management.group_cheque_accountant', company_id=other_company.id, company_ids=[Command.set(other_company.ids)])
        with self.assertRaises(AccessError):
            payment.with_user(outsider).with_context(allowed_company_ids=other_company.ids).read(['cheque_copy'])

    def test_separate_approval_keeps_bills_open_until_confirmation(self):
        self.bank.cheque_separate_approval = True
        leaf = self._book().leaf_ids[0]
        bill = self._bill()
        payment = self._pay_bill(bill, leaf)
        self.assertEqual(payment.state, 'draft')
        self.assertEqual(bill.amount_residual, 100)
        with self.assertRaises(UserError):
            self._pay_bill(bill, leaf.book_id.leaf_ids[1])
        with self.assertRaises(UserError):
            payment.action_post()
        accountant = new_test_user(self.env, login='cheque_approver_test', groups='account_cheque_book_management.group_cheque_accountant', company_id=self.env.company.id)
        payment.with_user(accountant).action_post()
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(leaf.current_attempt_id.approved_by_id, accountant)

    def test_direct_state_change_cannot_bypass_accountant(self):
        leaf = self._book().leaf_ids[0]
        payment = self._payment(leaf)
        with self.assertRaises(UserError):
            payment.write({'state': 'paid'})
        with self.assertRaises(UserError):
            payment.with_context(_cheque_capability=True).write({'state': 'in_process'})

    def test_draft_refreshes_account_configured_after_creation(self):
        self.method.payment_account_id = False
        payment = self._payment(self._book().leaf_ids[0])
        # Community may supply a fallback; Accounting leaves this empty. Both
        # must refresh to the subsequently configured Checks account.
        self.assertNotEqual(payment.outstanding_account_id, self.outstanding)
        self.assertFalse(payment.move_id)
        self.method.payment_account_id = self.outstanding
        payment.action_post()
        self.assertEqual(payment.outstanding_account_id, self.outstanding)
        self.assertEqual(payment.move_id.state, 'posted')

    def test_refresh_does_not_change_posted_accounting(self):
        payment = self._payment(self._book().leaf_ids[0])
        payment.action_post()
        original = payment.outstanding_account_id
        self.method.payment_account_id = False
        payment._refresh_draft_cheque_outstanding_account()
        self.assertEqual(payment.outstanding_account_id, original)

    def test_locked_correction_does_not_change_invoice(self):
        leaf = self._book().leaf_ids[0]
        bill = self._bill()
        self._pay_bill(bill, leaf)
        self._action(leaf, 'report', reason_id=self.reason.id)
        with patch.object(type(self.env.company), '_get_user_fiscal_lock_date', return_value=fields.Date.today()):
            with self.assertRaises(UserError):
                self._action(leaf, 'correct')
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(leaf.current_attempt_id.state, 'reported')

    def test_represent_preserves_cheque_date_and_validity(self):
        from datetime import timedelta
        leaf = self._book().leaf_ids[0]
        payment = self._payment(leaf)
        payment.action_post()
        self._action(leaf, 'report', reason_id=self.reason.id)
        self._action(leaf, 'correct')
        self.bank.cheque_validity_days = 1
        with self.assertRaises(UserError):
            self._action(leaf, 'represent', date=fields.Date.today() + timedelta(days=2))
        self._action(leaf, 'represent', date=fields.Date.today() + timedelta(days=1))
        self.assertEqual(leaf.current_attempt_id.payment_id.cheque_date, payment.cheque_date)

    def test_replacement_rechecks_other_payments(self):
        book = self._book()
        old, new = book.leaf_ids[:2]
        bill = self._bill()
        self._pay_bill(bill, old)
        self._action(old, 'report', reason_id=self.reason.id)
        self._action(old, 'correct')
        other = self._payment(book.leaf_ids[2], 20)
        other.action_post()
        payable = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        other_payable = other.move_id.line_ids.filtered(lambda line: line.account_id == payable.account_id)
        (payable | other_payable).reconcile()
        with self.assertRaises(UserError):
            self._action(old, 'replace', replacement_leaf_id=new.id, replacement_amount=100, instrument_recovered=True)
        self._action(old, 'replace', replacement_leaf_id=new.id, replacement_amount=80, instrument_recovered=True)
        self.assertEqual(bill.amount_residual, 0)

    def test_printing_uses_leaf_with_automatic_journal_sequence(self):
        self.bank.check_manual_sequencing = True
        leaf = self._book().leaf_ids[0]
        payment = self._payment(leaf)
        next_number = self.bank.check_sequence_id.number_next_actual
        payment.action_post()
        self.assertEqual(self.bank.check_sequence_id.number_next_actual, next_number)
        self.assertEqual(payment.check_number, leaf.number)
        with self.assertRaises(ValidationError):
            payment.check_number = '999999'
        self._action(leaf, 'void', instrument_recovered=True)
        with self.assertRaises(UserError):
            payment.do_print_checks()
