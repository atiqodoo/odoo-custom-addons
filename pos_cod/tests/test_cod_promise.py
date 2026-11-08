from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestCodCollectionPromise(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        receivable = cls.env['account.account'].create({
            'name': 'COD promise test receivable', 'code': 'CODPROMAR',
            'account_type': 'asset_receivable', 'reconcile': True,
            'company_ids': [Command.set(cls.company.ids)],
        })
        income = cls.env['account.account'].create({
            'name': 'COD promise test income', 'code': 'CODPROMINC',
            'account_type': 'income', 'company_ids': [Command.set(cls.company.ids)],
        })
        sale = cls.env['account.journal'].create({
            'name': 'COD promise sales', 'code': 'CPROM', 'type': 'sale',
            'company_id': cls.company.id, 'default_account_id': income.id,
        })
        cls.company_data = {'default_journal_sale': sale, 'default_account_receivable': receivable}
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'COD promise test POS', 'company_id': cls.company.id,
            'journal_id': sale.id, 'invoice_journal_id': sale.id,
            'payment_method_ids': [Command.clear()],
            'cod_enabled': True,
            'cod_ar_account_id': receivable.id,
            'cod_collection_promises_enabled': True,
            'cod_collection_timezone': 'Africa/Nairobi',
            'cod_collection_hour': 18,
        })
        cls.partner1 = cls.env['res.partner'].create({
            'name': 'COD promise test customer', 'property_account_receivable_id': receivable.id,
        })
        cls.product3 = cls.env['product.product'].create({
            'name': 'COD promise test service', 'type': 'service', 'available_in_pos': True,
            'property_account_income_id': income.id, 'list_price': 450, 'taxes_id': [Command.clear()],
        })
        other_company = cls.env['res.company'].create({'name': 'COD promise other company'})
        other_sale = cls.env['account.journal'].create({
            'name': 'Other COD sales', 'code': 'CPR2', 'type': 'sale', 'company_id': other_company.id,
        })
        cls.company_data_2 = {'company': other_company, 'default_journal_sale': other_sale}
        cls.session = cls.env['pos.session'].create({'config_id': cls.pos_config.id})
        cls.session.write({'state': 'opened'})
        cls.cashier = new_test_user(cls.env, login='cod_promise_cashier',
            groups='base.group_user,point_of_sale.group_pos_user', company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)])
        cls.marker = cls.env['account.move'].create({
            'journal_id': cls.company_data['default_journal_sale'].id,
        })

    def make_order(self, **values):
        return self.env['pos.order'].create({
            'session_id': self.session.id, 'partner_id': self.partner1.id,
            'amount_total': 100, 'amount_tax': 0, 'amount_paid': 0,
            'amount_return': 0, 'is_cod': True, 'cod_state': 'pending',
            'state': 'paid', 'cod_ar_move_id': self.marker.id,
            'cod_promised_payment_at': fields.Datetime.now() - timedelta(hours=1),
            **values,
        })

    def reminders(self, **kwargs):
        return self.env['pos.order'].cod_overdue_reminders(self.pos_config.id, **kwargs)

    def test_defaults_use_local_calendar_not_session_date(self):
        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 11, 6, 22, 30)):
            for days in (0, 1, 2, 7):
                self.pos_config.cod_collection_delay_days = days
                defaults = self.pos_config.cod_promise_defaults()
                self.assertEqual(defaults['date'], (datetime(2026, 11, 7) + timedelta(days=days)).date().isoformat())
                self.assertEqual((defaults['hour'], defaults['minute']), (18, 0))

    def test_invalid_settings(self):
        for vals in ({'cod_collection_delay_days': -1}, {'cod_collection_hour': 24},
                     {'cod_collection_hour': -1}, {'cod_reminder_interval_minutes': 0},
                     {'cod_reminder_refresh_seconds': 0}):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.pos_config.write(vals)

    def test_cashier_cannot_change_settings(self):
        with self.assertRaises(AccessError):
            self.pos_config.with_user(self.cashier).write({'cod_collection_delay_days': 2})
        self.assertTrue(self.pos_config.with_user(self.cashier).cod_promise_defaults()['enabled'])
        with self.assertRaises(AccessError):
            self.pos_config.with_user(self.env.ref('base.public_user')).cod_promise_defaults()

    def test_missing_past_and_invalid_promises_rejected_before_dispatch(self):
        for due in (False, 'invalid', fields.Datetime.to_string(fields.Datetime.now() - timedelta(seconds=1))):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.env['pos.order'].sync_from_ui([{
                    'is_cod': True, 'session_id': self.session.id,
                    'uuid': str(uuid4()), 'cod_promised_payment_at': due,
                }])

    def test_overdue_balances_and_exclusions(self):
        overdue = self.make_order()
        partial = self.make_order(cod_state='partial')
        self.env['pos.cod.collection'].create({
            'order_id': partial.id, 'session_id': self.session.id, 'kind': 'payment', 'amount': 40,
        })
        for kind in ('payment', 'return', 'discount'):
            settled = self.make_order()
            self.env['pos.cod.collection'].create({
                'order_id': settled.id, 'session_id': self.session.id, 'kind': kind, 'amount': 100,
            })
            self.assertEqual(settled._cod_open_amount(), 0, 'Settled balance for %s' % kind)
        for values in ({'cod_promised_payment_at': False}, {'cod_state': 'paid'},
                       {'cod_state': 'returned'}, {'state': 'cancel'}, {'state': 'draft'},
                       {'is_cod': False}, {'cod_ar_move_id': False}):
            excluded = self.make_order(**values)
            self.assertNotIn(excluded.id, [row['id'] for row in self.reminders()['rows']], repr(values))
        future = self.make_order(cod_promised_payment_at=fields.Datetime.now() + timedelta(hours=2))
        result = self.reminders()
        rows = {row['id']: row for row in result['rows']}
        self.assertIn(overdue.id, rows)
        self.assertEqual(rows[partial.id]['open_amount'], 60)
        self.assertNotIn(future.id, rows)
        self.assertEqual(result['count'], 2)
        self.assertGreater(result['next_due_in_seconds'], 0)
        self.assertEqual(self.reminders(offset=1, limit=1)['rows'][0]['id'], result['rows'][1]['id'])

    def test_company_isolation_and_disabled_feature(self):
        order = self.make_order()
        other = self.env['pos.config'].with_company(self.company_data_2['company']).create({
            'name': 'Other company COD',
            'journal_id': self.company_data_2['default_journal_sale'].id,
            'invoice_journal_id': self.company_data_2['default_journal_sale'].id,
            'payment_method_ids': [Command.clear()],
        })
        with self.assertRaises(AccessError):
            self.env['pos.order'].with_user(self.cashier).cod_overdue_reminders(other.id)
        self.assertIn(order.id, [row['id'] for row in self.reminders()['rows']])
        self.pos_config.cod_collection_promises_enabled = False
        self.assertEqual(self.reminders()['count'], 0)

    def test_cashier_reminders_survive_session_and_settings_changes(self):
        order = self.make_order()
        original_due = order.cod_promised_payment_at
        self.session.state = 'closed'
        self.pos_config.cod_collection_delay_days = 2
        result = self.env['pos.order'].with_user(self.cashier).cod_overdue_reminders(self.pos_config.id)
        self.assertIn(order.id, [row['id'] for row in result['rows']])
        self.assertEqual(order.cod_promised_payment_at, original_due)

    def test_new_dispatch_and_duplicate_preserve_promise(self):
        due = fields.Datetime.to_string(fields.Datetime.now() + timedelta(days=1))
        payload = {
            'name': 'COD promise test', 'uuid': str(uuid4()), 'session_id': self.session.id,
            'partner_id': self.partner1.id, 'is_cod': True, 'cod_state': 'pending',
            'cod_promised_payment_at': due, 'amount_total': 450, 'amount_tax': 0,
            'amount_paid': 0, 'amount_return': -450, 'payment_ids': [],
            'lines': [[0, 0, {'product_id': self.product3.id, 'qty': 1,
                'price_unit': 450, 'price_subtotal': 450, 'price_subtotal_incl': 450,
                'tax_ids': [], 'uuid': str(uuid4())}]],
        }
        self.env['pos.order'].sync_from_ui([dict(payload)])
        order = self.env['pos.order'].search([('uuid', '=', payload['uuid'])])
        self.assertEqual(len(order), 1)
        self.assertEqual(order.cod_promised_payment_at, fields.Datetime.to_datetime(due))
        retry = dict(payload, cod_promised_payment_at=False)
        self.env['pos.order'].sync_from_ui([retry])
        self.assertEqual(order.cod_promised_payment_at, fields.Datetime.to_datetime(due))
        self.assertEqual(self.env['pos.order'].search_count([('uuid', '=', payload['uuid'])]), 1)
