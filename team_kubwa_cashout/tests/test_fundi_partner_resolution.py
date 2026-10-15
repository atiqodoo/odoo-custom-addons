# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase
from odoo import fields
from odoo.addons.team_kubwa_cashout.services.eligibility_engine import TeamKubwaEligibilityEngine


class TestTeamKubwaFundiPartnerResolution(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cashout_model = cls.env['team.kubwa.cashout']
        cls.partner_model = cls.env['res.partner']
        cls.pos_session = cls.env['pos.session'].search(
            [('config_id.company_id', '=', cls.env.company.id)],
            limit=1,
        )

    def _create_cod_order(self, partner, amount=500.0, state='pending'):
        self.assertTrue(self.pos_session, 'A POS session is required for the COD cash-out block tests.')
        return self.env['pos.order'].create({
            'name': 'TK COD Block Test',
            'session_id': self.pos_session.id,
            'company_id': self.env.company.id,
            'partner_id': partner.id,
            'is_cod': True,
            'cod_state': state,
            'amount_tax': 0.0,
            'amount_total': amount,
            'amount_paid': 0.0,
            'amount_return': 0.0,
        })

    def _create_customer_invoice(self, partner, amount=500.0, post=True, paid=False):
        journal = self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        self.assertTrue(journal, 'A sales journal is required for invoice block tests.')
        state = 'posted' if post else 'draft'
        residual = 0.0 if paid else amount
        columns = [
            'move_type', 'state', 'partner_id', 'partner_shipping_id', 'commercial_partner_id',
            'journal_id', 'company_id', 'currency_id', 'date', 'invoice_date', 'amount_total',
            'amount_residual', 'auto_post', 'extract_state', 'invoice_currency_rate',
            'is_cod_entry', 'create_uid', 'write_uid', 'create_date', 'write_date',
        ]
        values = [
            'out_invoice', state, partner.id, partner.id, partner.commercial_partner_id.id,
            journal.id, self.env.company.id, self.env.company.currency_id.id, fields.Date.today(),
            fields.Date.today(), amount, residual, 'no', 'no_extract_requested', 1.0,
            False, self.env.uid, self.env.uid, fields.Datetime.now(), fields.Datetime.now(),
        ]
        # Minimal guard fixture: this dev DB has optional account.move columns before their modules load in tests.
        self.env.cr.execute("""
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = 'account_move'
               AND column_name = 'promotion_release_state'
        """)
        if self.env.cr.fetchone():
            columns.append('promotion_release_state')
            values.append('not_required')
        placeholders = ', '.join(['%s'] * len(values))
        query = 'INSERT INTO account_move (%s) VALUES (%s) RETURNING id' % (
            ', '.join(columns),
            placeholders,
        )
        self.env.cr.execute(query, values)
        return self.env['account.move'].browse(self.env.cr.fetchone()[0])

    def test_find_fundi_partner_by_phone_variant(self):
        partner = self.partner_model.create({
            'name': 'Patrick Fundi',
            'mobile': '254712345678',
            'company_id': self.env.company.id,
        })

        resolved = self.cashout_model._find_fundi_partner(phone='0712 345 678')

        self.assertEqual(resolved, partner)

    def test_find_fundi_partner_by_unique_name(self):
        partner = self.partner_model.create({
            'name': 'TK Unique Patricia 9001',
            'company_id': self.env.company.id,
        })

        resolved = self.cashout_model._find_fundi_partner(name='Unique Patricia 9001')

        self.assertEqual(resolved, partner)

    def test_find_fundi_partner_rejects_registered_name_with_unregistered_phone(self):
        self.partner_model.create({
            'name': 'TK Registered Name Fake Phone 9001',
            'phone': '0712 345 690',
            'company_id': self.env.company.id,
        })

        with self.assertRaises(UserError):
            self.cashout_model._find_fundi_partner(
                phone='0712 345 691',
                name='TK Registered Name Fake Phone 9001',
            )

    def test_find_fundi_partner_rejects_phone_registered_to_different_name(self):
        self.partner_model.create({
            'name': 'TK Correct Phone Owner 9001',
            'phone': '0712 345 692',
            'company_id': self.env.company.id,
        })

        with self.assertRaises(UserError):
            self.cashout_model._find_fundi_partner(
                phone='0712 345 692',
                name='TK Wrong Phone Owner 9001',
            )

    def test_find_fundi_partner_by_ambiguous_name_requires_more_detail(self):
        self.partner_model.create({'name': 'TK Ambiguous Fundi 9001 A', 'company_id': self.env.company.id})
        self.partner_model.create({'name': 'TK Ambiguous Fundi 9001 B', 'company_id': self.env.company.id})

        with self.assertRaises(UserError):
            self.cashout_model._find_fundi_partner(name='Ambiguous Fundi 9001')

    def test_eligibility_requires_manual_customer_creation_when_not_found(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK First-Time Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 1000.0,
            'purchase_ratio': 10.0,
        })
        self.env['ir.config_parameter'].sudo().set_param('team_kubwa_cashout.default_policy_id', str(policy.id))
        domain = [('name', '=', 'TK Brand New Fundi 9001'), ('phone', '=', '0712 345 681')]

        result = self.cashout_model.pos_check_eligibility({
            'fundi_name': 'TK Brand New Fundi 9001',
            'phone': '0712 345 681',
            'requested_amount': 200.0,
        })

        self.assertFalse(result['allowed'])
        self.assertTrue(result['requires_customer_creation'])
        self.assertFalse(result['partner_id'])
        self.assertFalse(self.partner_model.search(domain))

    def test_eligibility_requires_both_name_and_phone_when_name_not_identified(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Missing Phone Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 1000.0,
            'purchase_ratio': 10.0,
        })
        self.env['ir.config_parameter'].sudo().set_param('team_kubwa_cashout.default_policy_id', str(policy.id))

        result = self.cashout_model.pos_check_eligibility({
            'fundi_name': 'TK Unknown Name Only 9001',
            'requested_amount': 200.0,
        })

        self.assertEqual(result['reason'], 'customer_not_found')
        self.assertFalse(result['requires_customer_creation'])
        self.assertFalse(result['partner_id'])

    def test_eligibility_requires_both_name_and_phone_when_phone_not_identified(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Missing Name Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 1000.0,
            'purchase_ratio': 10.0,
        })
        self.env['ir.config_parameter'].sudo().set_param('team_kubwa_cashout.default_policy_id', str(policy.id))

        result = self.cashout_model.pos_check_eligibility({
            'phone': '0712 345 688',
            'requested_amount': 200.0,
        })

        self.assertEqual(result['reason'], 'customer_not_found')
        self.assertFalse(result['requires_customer_creation'])
        self.assertFalse(result['partner_id'])

    def test_fully_unpaid_cod_order_blocks_cashout(self):
        partner = self.partner_model.create({
            'name': 'TK COD Blocked Fundi 9001',
            'phone': '0712 345 683',
            'company_id': self.env.company.id,
        })
        self._create_cod_order(partner, amount=750.0)

        with self.assertRaises(UserError):
            self.cashout_model._validate_no_fully_unpaid_cod_orders(partner, company=self.env.company)

    def test_cod_order_with_payment_does_not_block_cashout(self):
        partner = self.partner_model.create({
            'name': 'TK COD Paid Fundi 9001',
            'phone': '0712 345 684',
            'company_id': self.env.company.id,
        })
        order = self._create_cod_order(partner, amount=750.0)
        self.env['pos.cod.collection'].create({
            'order_id': order.id,
            'session_id': self.pos_session.id,
            'kind': 'payment',
            'amount': 750.0,
        })

        self.cashout_model._validate_no_fully_unpaid_cod_orders(partner, company=self.env.company)

    def test_open_unpaid_invoice_blocks_cashout(self):
        partner = self.partner_model.create({
            'name': 'TK Invoice Blocked Fundi 9001',
            'phone': '0712 345 685',
            'company_id': self.env.company.id,
        })
        self._create_customer_invoice(partner, amount=850.0)

        with self.assertRaises(UserError):
            self.cashout_model._validate_no_open_unpaid_invoices(partner, company=self.env.company)

    def test_draft_invoice_does_not_block_cashout(self):
        partner = self.partner_model.create({
            'name': 'TK Draft Invoice Fundi 9001',
            'phone': '0712 345 686',
            'company_id': self.env.company.id,
        })
        self._create_customer_invoice(partner, amount=850.0, post=False)

        self.cashout_model._validate_no_open_unpaid_invoices(partner, company=self.env.company)

    def test_paid_invoice_does_not_block_cashout(self):
        partner = self.partner_model.create({
            'name': 'TK Paid Invoice Fundi 9001',
            'phone': '0712 345 687',
            'company_id': self.env.company.id,
        })
        self._create_customer_invoice(partner, amount=850.0, paid=True)

        self.cashout_model._validate_no_open_unpaid_invoices(partner, company=self.env.company)

    def test_eligibility_engine_handles_phone_without_existing_partner(self):
        result = TeamKubwaEligibilityEngine(self.env)._last_paid_cashout(
            '07541287945',
            self.env['res.partner'],
            self.env.company,
        )

        self.assertFalse(result)

    def test_first_time_goodwill_override_obeys_first_time_limit(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK First-Time Limit Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 200.0,
            'purchase_ratio': 10.0,
        })
        eligibility = {'reason': 'first_time_limit_exceeded'}

        with self.assertRaises(UserError):
            self.cashout_model._validate_manager_override(policy, eligibility, 'first_time_goodwill')

    def test_owner_approved_override_can_handle_first_time_limit_failure(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Owner Override Limit Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 200.0,
            'purchase_ratio': 10.0,
        })

        self.cashout_model._validate_manager_override(
            policy,
            {'reason': 'first_time_limit_exceeded', 'is_first_time': True},
            'owner_approved',
        )

    def test_first_time_goodwill_cannot_be_reused_after_paid_cashout(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Reused Goodwill Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 200.0,
            'purchase_ratio': 10.0,
        })

        with self.assertRaises(UserError):
            self.cashout_model._validate_manager_override(
                policy,
                {'reason': 'insufficient_purchase', 'is_first_time': False, 'last_cashout_id': 99},
                'first_time_goodwill',
            )

    def test_first_time_amount_cannot_exceed_configured_limit(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Absolute First-Time Limit Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 200.0,
            'purchase_ratio': 10.0,
        })

        with self.assertRaises(UserError):
            self.cashout_model._validate_first_time_limit(
                policy,
                {'is_first_time': True, 'reason': 'first_time_limit_exceeded'},
                201.0,
            )

    def test_owner_approved_first_time_amount_can_exceed_configured_limit(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Owner Approved First-Time Limit Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 200.0,
            'purchase_ratio': 10.0,
        })

        self.cashout_model._validate_first_time_limit(
            policy,
            {'is_first_time': True, 'reason': 'first_time_limit_exceeded'},
            201.0,
            override_reason='owner_approved',
        )

    def test_first_time_goodwill_amount_cannot_exceed_configured_limit(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Goodwill First-Time Limit Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 200.0,
            'purchase_ratio': 10.0,
        })

        with self.assertRaises(UserError):
            self.cashout_model._validate_first_time_limit(
                policy,
                {'is_first_time': True, 'reason': 'first_time_limit_exceeded'},
                201.0,
                override_reason='first_time_goodwill',
            )

    def test_purchase_eligible_first_cashout_can_exceed_first_time_limit(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Purchase Eligible First Cashout Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 200.0,
            'purchase_ratio': 10.0,
        })

        self.cashout_model._validate_first_time_limit(
            policy,
            {'is_first_time': True, 'reason': 'eligible_by_purchase'},
            300.0,
        )

    def test_first_time_amount_at_configured_limit_is_allowed(self):
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Exact First-Time Limit Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 200.0,
            'purchase_ratio': 10.0,
        })

        self.cashout_model._validate_first_time_limit(
            policy,
            {'is_first_time': True, 'reason': 'first_time_allowed'},
            200.0,
        )

    def test_approved_amount_cannot_exceed_eligibility_checked_amount(self):
        with self.assertRaises(UserError):
            self.cashout_model._validate_cashout_amounts_against_eligibility(
                requested_amount=200.0,
                approved_amount=2100.0,
                paid_amount=2100.0,
            )

    def test_paid_amount_cannot_exceed_approved_amount(self):
        with self.assertRaises(UserError):
            self.cashout_model._validate_cashout_amounts_against_eligibility(
                requested_amount=200.0,
                approved_amount=200.0,
                paid_amount=2100.0,
            )

    def test_amount_guard_accepts_paid_amount_within_checked_amount(self):
        self.cashout_model._validate_cashout_amounts_against_eligibility(
            requested_amount=200.0,
            approved_amount=200.0,
            paid_amount=200.0,
        )

    def test_otp_reference_is_required_for_pos_payout(self):
        with self.assertRaises(UserError):
            self.cashout_model._validate_otp_confirmation({
                'otp_reference': '   ',
                'crown_member_name': 'TK Member',
                'crown_points_redeemed': 3000,
                'otp_received': True,
            })

    def test_crown_member_name_is_required_for_pos_payout(self):
        with self.assertRaises(UserError):
            self.cashout_model._validate_otp_confirmation({
                'otp_reference': 'OTP123',
                'crown_member_name': '   ',
                'crown_points_redeemed': 3000,
                'otp_received': True,
            })

    def test_crown_points_redeemed_is_required_for_pos_payout(self):
        with self.assertRaises(UserError):
            self.cashout_model._validate_otp_confirmation({
                'otp_reference': 'OTP123',
                'crown_member_name': 'TK Member',
                'crown_points_redeemed': 0,
                'otp_received': True,
            })

    def test_otp_must_be_marked_received_for_pos_payout(self):
        with self.assertRaises(UserError):
            self.cashout_model._validate_otp_confirmation({
                'otp_reference': 'OTP123',
                'crown_member_name': 'TK Member',
                'crown_points_redeemed': 3000,
                'otp_received': False,
            })

    def test_otp_confirmation_accepts_reference_and_received_flag(self):
        self.cashout_model._validate_otp_confirmation({
            'otp_reference': 'OTP123',
            'crown_member_name': 'TK Member',
            'crown_points_redeemed': 3000,
            'otp_received': True,
        })

    def test_second_cashout_for_same_fundi_is_not_first_time(self):
        partner = self.partner_model.create({
            'name': 'TK Repeat Fundi 9001',
            'phone': '0712 345 682',
            'company_id': self.env.company.id,
        })
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Repeat Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 500.0,
            'purchase_ratio': 10.0,
        })
        self.cashout_model.create({
            'fundi_name': partner.name,
            'fundi_phone': partner.phone,
            'fundi_partner_id': partner.id,
            'requested_amount': 100.0,
            'approved_amount': 100.0,
            'paid_amount': 100.0,
            'eligibility_policy_id': policy.id,
            'state': 'paid',
            'paid_datetime': fields.Datetime.now(),
            'company_id': self.env.company.id,
        })

        result = TeamKubwaEligibilityEngine(self.env).evaluate(policy, partner.phone, 100.0, partner=partner)

        self.assertFalse(result['is_first_time'])

    def test_all_time_prior_cashout_consumes_required_purchase_value(self):
        partner = self.partner_model.create({
            'name': 'TK Consumed Fundi 9001',
            'phone': '0712 345 693',
            'company_id': self.env.company.id,
        })
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Consumption Policy',
            'company_id': self.env.company.id,
            'first_time_allowed': True,
            'first_time_limit_amount': 500.0,
            'purchase_ratio': 10.0,
            'purchase_period_mode': 'all_time',
        })
        self.cashout_model.create({
            'fundi_name': partner.name,
            'fundi_phone': partner.phone,
            'fundi_partner_id': partner.id,
            'requested_amount': 1000.0,
            'approved_amount': 1000.0,
            'paid_amount': 1000.0,
            'eligibility_policy_id': policy.id,
            'eligibility_required_purchase': 10000.0,
            'state': 'paid',
            'paid_datetime': fields.Datetime.now(),
            'company_id': self.env.company.id,
        })

        result = TeamKubwaEligibilityEngine(self.env).evaluate(policy, partner.phone, 700.0, partner=partner)

        self.assertEqual(result['consumed_purchase'], 10000.0)
        self.assertEqual(result['available_purchase'], -10000.0)
        self.assertEqual(result['required_purchase'], 7000.0)
        self.assertEqual(result['gap'], 17000.0)

    def test_purchase_ledger_records_cashout_consumption_deficit(self):
        partner = self.partner_model.create({
            'name': 'TK Ledger Deficit Fundi 9001',
            'phone': '0712 345 694',
            'company_id': self.env.company.id,
        })
        policy = self.env['team.kubwa.eligibility.policy'].create({
            'name': 'TK Ledger Deficit Policy',
            'company_id': self.env.company.id,
            'purchase_ratio': 10.0,
            'purchase_period_mode': 'all_time',
        })
        cashout = self.cashout_model.create({
            'fundi_name': partner.name,
            'fundi_phone': partner.phone,
            'fundi_partner_id': partner.id,
            'requested_amount': 700.0,
            'approved_amount': 700.0,
            'paid_amount': 700.0,
            'eligibility_policy_id': policy.id,
            'eligibility_required_purchase': 7000.0,
            'eligibility_gross_purchase': 4000.0,
            'eligibility_consumed_purchase': 10000.0,
            'eligibility_actual_purchase': -6000.0,
            'eligibility_available_purchase': -6000.0,
            'eligibility_available_after_cashout': -13000.0,
            'eligibility_gap': 13000.0,
            'eligibility_purchase_period_mode': 'all_time',
            'manager_override': True,
            'override_reason': 'owner_approved',
            'state': 'paid',
            'paid_datetime': fields.Datetime.now(),
            'company_id': self.env.company.id,
        })

        cashout._create_purchase_ledger_entry('cashout_consumption', 'Test consumption')
        ledger = cashout.ledger_ids[:1]

        self.assertEqual(ledger.consumed_purchase, 7000.0)
        self.assertEqual(ledger.running_available_purchase, -13000.0)
        self.assertTrue(ledger.manager_override)

    def test_pos_save_draft_creates_audited_open_cashout(self):
        partner = self.partner_model.create({
            'name': 'TK Draft Fundi 9001',
            'phone': '0712 345 689',
            'company_id': self.env.company.id,
        })

        draft = self.cashout_model.pos_save_draft_cashout({
            'fundi_name': partner.name,
            'phone': partner.phone,
            'partner_id': partner.id,
            'requested_amount': 455.0,
            'step': 'fundi',
        })
        cashout = self.cashout_model.browse(draft['id'])

        self.assertEqual(cashout.state, 'draft')
        self.assertEqual(cashout.fundi_partner_id, partner)
        self.assertEqual(cashout.requested_amount, 455.0)
        self.assertIn('draft_saved', cashout.log_ids.mapped('event_type'))

    def test_pos_save_draft_updates_existing_open_cashout(self):
        partner = self.partner_model.create({
            'name': 'TK Draft Update Fundi 9001',
            'phone': '0712 345 690',
            'company_id': self.env.company.id,
        })
        first = self.cashout_model.pos_save_draft_cashout({
            'fundi_name': partner.name,
            'phone': partner.phone,
            'partner_id': partner.id,
            'requested_amount': 455.0,
            'step': 'fundi',
        })

        second = self.cashout_model.pos_save_draft_cashout({
            'draft_id': first['id'],
            'fundi_name': partner.name,
            'phone': partner.phone,
            'partner_id': partner.id,
            'requested_amount': 700.0,
            'step': 'otp',
        })
        cashout = self.cashout_model.browse(second['id'])

        self.assertEqual(first['id'], second['id'])
        self.assertEqual(cashout.state, 'waiting_otp')
        self.assertEqual(cashout.requested_amount, 700.0)
        self.assertIn('draft_updated', cashout.log_ids.mapped('event_type'))

    def test_pos_save_draft_requires_identified_customer(self):
        with self.assertRaises(UserError):
            self.cashout_model.pos_save_draft_cashout({
                'fundi_name': 'TK Missing Draft Fundi 9001',
                'phone': '0712 345 691',
                'requested_amount': 455.0,
                'step': 'fundi',
            })

    def test_transaction_ref_required_only_for_bank_journal_when_enabled(self):
        settings = {'require_transaction_ref': True}
        bank_journal = self.env['account.journal'].new({'type': 'bank'})
        cash_journal = self.env['account.journal'].new({'type': 'cash'})

        with self.assertRaises(UserError):
            self.cashout_model._validate_transaction_ref_for_journal(settings, bank_journal, {})

        self.assertFalse(
            self.cashout_model._validate_transaction_ref_for_journal(settings, cash_journal, {})
        )
        self.assertEqual(
            self.cashout_model._validate_transaction_ref_for_journal(settings, bank_journal, {'transaction_ref': ' MPESA123 '}),
            'MPESA123',
        )

    def test_transaction_ref_is_unique_despite_caps_per_company(self):
        self.cashout_model.create({
            'fundi_name': 'TK Ref Fundi 9001',
            'requested_amount': 100.0,
            'transaction_ref': 'ABC123',
            'company_id': self.env.company.id,
        })

        with self.assertRaises(ValidationError):
            self.cashout_model.create({
                'fundi_name': 'TK Ref Fundi 9002',
                'requested_amount': 100.0,
                'transaction_ref': ' abc123 ',
                'company_id': self.env.company.id,
            })

    def test_log_payload_serializes_datetime_values(self):
        now = fields.Datetime.now()

        result = self.cashout_model._json_safe_payload({'last_cashout_date': now})

        self.assertEqual(result['last_cashout_date'], now.isoformat())

    def test_team_kubwa_authorization_allows_unrestricted_cashier(self):
        cashier = self.env['hr.employee'].create({
            'name': 'TK Unrestricted Cashier',
            'sbl_require_auth_team_kubwa_pay_post': False,
        })

        auth_log = self.cashout_model._validate_team_kubwa_pos_authorization(
            {'cashier_id': cashier.id},
            'team_kubwa_pay_post',
        )

        self.assertFalse(auth_log)

    def test_team_kubwa_authorization_blocks_restricted_cashier_without_log(self):
        cashier = self.env['hr.employee'].create({
            'name': 'TK Restricted Cashier',
            'sbl_require_auth_team_kubwa_pay_post': True,
        })

        with self.assertRaises(UserError):
            self.cashout_model._validate_team_kubwa_pos_authorization(
                {'cashier_id': cashier.id},
                'team_kubwa_pay_post',
            )

    def test_team_kubwa_authorization_accepts_fresh_approved_log(self):
        cashier = self.env['hr.employee'].create({
            'name': 'TK Authorized Cashier',
            'sbl_require_auth_team_kubwa_pay_post': True,
        })
        supervisor = self.env['hr.employee'].create({'name': 'TK Supervisor'})
        auth_log = self.env['sbl.pos.authorization.log'].sbl_log_authorization({
            'action_key': 'team_kubwa_pay_post',
            'status': 'approved',
            'cashier_id': cashier.id,
            'supervisor_id': supervisor.id,
            'message': 'Test authorization',
        })

        result = self.cashout_model._validate_team_kubwa_pos_authorization(
            {
                'cashier_id': cashier.id,
                'authorizations': {
                    'team_kubwa_pay_post': {
                        'authorization_log_id': auth_log.id,
                        'supervisor_id': supervisor.id,
                    },
                },
            },
            'team_kubwa_pay_post',
        )

        self.assertEqual(result, auth_log)
