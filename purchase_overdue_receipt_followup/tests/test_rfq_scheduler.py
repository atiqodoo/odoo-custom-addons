from unittest.mock import patch

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestRfqHomeScheduler(TransactionCase):
    def setUp(self):
        super().setUp()
        self.orders = self.env['purchase.order']
        self.jobs = self.orders._rfq_scheduler_jobs()

    def test_home_button_queues_existing_jobs_without_selection(self):
        next_calls = {job.id: job.nextcall for job in self.jobs}
        purchase_count = self.orders.search_count([])
        self.env['ir.cron.trigger'].search([('cron_id', 'in', self.jobs.ids)]).unlink()
        action = self.orders.action_run_scheduler_from_rfq()
        triggers = self.env['ir.cron.trigger'].search([('cron_id', 'in', self.jobs.ids)])
        self.assertEqual(triggers.cron_id, self.jobs)
        self.assertEqual(len(triggers), 2)
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(self.orders.search_count([]), purchase_count)
        self.assertEqual({job.id: job.nextcall for job in self.jobs}, next_calls)
        self.orders.action_run_scheduler_from_rfq()
        self.assertEqual(self.env['ir.cron.trigger'].search_count([('cron_id', 'in', self.jobs.ids)]), 2)

    def test_purchase_manager_cannot_invoke_database_wide_scheduler(self):
        buyer = new_test_user(self.env, login='rfq_scheduler_manager', groups='purchase.group_purchase_manager')
        with self.assertRaises(AccessError):
            self.orders.with_user(buyer).action_run_scheduler_from_rfq()

    def test_disabled_job_rejected_without_changing_configuration(self):
        job = self.jobs[:1]
        job.active = False
        with self.assertRaises(UserError):
            self.orders.action_run_scheduler_from_rfq()
        self.assertFalse(job.active)

    def test_failed_queue_propagates_error(self):
        self.env['ir.cron.trigger'].search([('cron_id', 'in', self.jobs.ids)]).unlink()
        with patch.object(type(self.jobs), '_trigger', side_effect=UserError('Cron service unavailable')):
            with self.assertRaises(UserError):
                self.orders.action_run_scheduler_from_rfq()

    def test_button_visible_without_selection_and_hidden_from_buyers(self):
        view_id = self.env.ref('purchase.purchase_order_kpis_tree').id
        admin_view = self.orders.get_view(view_id=view_id, view_type='list')
        root = etree.fromstring(admin_view['arch'])
        buttons = root.xpath("./header/button[@name='action_run_scheduler_from_rfq']")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get('display'), 'always')
        buyer = new_test_user(self.env, login='rfq_scheduler_buyer', groups='purchase.group_purchase_user')
        buyer_view = self.orders.with_user(buyer).get_view(view_id=view_id, view_type='list')
        buyer_root = etree.fromstring(buyer_view['arch'])
        self.assertFalse(buyer_root.xpath("./header/button[@name='action_run_scheduler_from_rfq']"))

    def test_button_does_not_override_sunday_warning_policy(self):
        company = self.env.company
        company.write({'receipt_followup_enabled': True,
            'receipt_followup_calendar_id': self.env.ref('purchase_overdue_receipt_followup.receiving_calendar').id})
        self.orders.action_run_scheduler_from_rfq()
        with patch.object(fields.Datetime, 'now', return_value=fields.Datetime.to_datetime('2026-11-01 07:00:00')):
            self.assertFalse(self.env['purchase.receipt.followup'].get_popup_warning())
