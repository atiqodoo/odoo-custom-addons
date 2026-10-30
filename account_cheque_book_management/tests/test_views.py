from pathlib import Path

from lxml import etree

from odoo.addons.base.models.ir_ui_view import get_view_arch_from_file
from odoo.modules.module import get_module_path
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestChequeViews(TransactionCase):
    def test_every_view_loads_from_file(self):
        root = Path(get_module_path('account_cheque_book_management'))
        count = 0
        for folder in ('views', 'wizard'):
            for path in (root / folder).glob('*.xml'):
                document = etree.parse(str(path))
                for record in document.xpath("//record[@model='ir.ui.view']"):
                    xmlid = 'account_cheque_book_management.' + record.get('id')
                    with self.subTest(xmlid=xmlid):
                        arch = get_view_arch_from_file(str(path), xmlid)
                        self.assertTrue(arch)
                        etree.fromstring(arch.encode())
                    count += 1
        self.assertGreater(count, 0)

    def test_forms_compile_in_file_mode(self):
        for model, xmlid in (
            ('account.journal', 'account.view_account_journal_form'),
            ('account.payment', 'account.view_account_payment_form'),
            ('account.payment.register', 'account.view_account_payment_register_form'),
            ('account.cheque.book', 'account_cheque_book_management.book_form'),
            ('account.cheque.leaf', 'account_cheque_book_management.leaf_form'),
            ('account.cheque.attempt', 'account_cheque_book_management.attempt_form'),
            ('account.cheque.fee', 'account_cheque_book_management.fee_form'),
            ('account.cheque.workflow', 'account_cheque_book_management.workflow_form'),
        ):
            with self.subTest(model=model):
                result = self.env[model].with_context(read_arch_from_file=True).get_views(
                    [(self.env.ref(xmlid).id, 'form')], options={'toolbar': False},
                )
                self.assertEqual(etree.fromstring(result['views']['form']['arch'].encode()).tag, 'form')
