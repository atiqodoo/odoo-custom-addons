from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestPurchaseArrivalAlarm(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Arrival vendor'})
        cls.product = cls.env['product.product'].create({'name': 'Arrival product', 'type': 'consu'})
        cls.order = cls.env['purchase.order'].create({
            'partner_id': cls.vendor.id,
            'order_line': [(0, 0, {'name': 'Arrival product', 'product_id': cls.product.id,
                                    'product_qty': 2, 'product_uom': cls.product.uom_po_id.id,
                                    'price_unit': 10, 'date_planned': fields.Datetime.now() + timedelta(days=2)})],
        })
        cls.order.button_confirm()

    def _alarm(self, order=None):
        order = (order or self.order).with_user(self.env.ref('base.user_admin'))
        action = order.action_set_arrival_alarm()
        return self.env['native.alarm'].with_user(order.env.user).with_context(**action['context']).create({})

    def test_schedule_reschedule_snooze_and_stop(self):
        alarm = self._alarm()
        original = self.order.date_planned
        self.assertEqual(alarm.alarm_at, original)
        self.assertIn(self.order.name, alarm.name)
        alarm.action_snooze()
        snoozed = alarm.alarm_at
        alarm.browser_schedule()
        self.assertEqual(alarm.alarm_at, snoozed)
        revised = original + timedelta(days=3)
        self.order.order_line.date_planned = revised
        alarm.browser_schedule()
        self.assertEqual(alarm.alarm_at, revised)
        self.assertEqual(alarm.purchase_arrival_date, revised)
        alarm.action_stop()
        self.order.order_line.date_planned = revised + timedelta(days=1)
        alarm.browser_schedule()
        self.assertEqual(alarm.state, 'acknowledged')
        self.assertEqual(alarm.alarm_at, revised)

    def test_user_override_tracks_offset_and_snooze(self):
        order = self.order.with_user(self.env.ref('base.user_admin'))
        original = order.date_planned
        action = order.action_set_arrival_alarm()
        model = self.env['native.alarm'].with_user(order.env.user).with_context(**action['context'])
        with Form(model) as form:
            self.assertEqual(form.alarm_at, original)
            self.assertEqual(form.purchase_arrival_date, original)
            form.alarm_at = original - timedelta(hours=2)
        alarm = form.record
        self.assertEqual(order.date_planned, original)
        self.assertEqual(alarm.alarm_at, original - timedelta(hours=2))
        self.assertEqual(alarm.purchase_arrival_offset, -7200)
        alarm.action_snooze()
        self.assertEqual(alarm.purchase_arrival_offset, -7200)
        revised = original + timedelta(days=1)
        order.order_line.date_planned = revised
        alarm.browser_schedule()
        self.assertEqual(alarm.alarm_at, revised - timedelta(hours=2))
        alarm.write({'alarm_at': revised + timedelta(hours=1)})
        self.assertEqual(alarm.purchase_arrival_offset, 3600)
        order.order_line.date_planned = revised + timedelta(days=1)
        alarm.browser_schedule()
        self.assertEqual(alarm.alarm_at, revised + timedelta(days=1, hours=1))

    def test_cancel_and_receipt_completion_suppress(self):
        alarm = self._alarm()
        self.assertTrue(alarm._is_deliverable())
        self.order.write({'state': 'cancel'})
        self.assertFalse(alarm._is_deliverable())

    def test_fully_received_suppresses(self):
        alarm = self._alarm()
        picking = self.order.picking_ids
        self.assertTrue(picking)
        picking.move_ids.write({'quantity': 2, 'picked': True})
        picking.button_validate()
        self.assertEqual(self.order.receipt_status, 'full')
        self.assertFalse(alarm._is_deliverable())

    def test_partial_receipt_remains_deliverable(self):
        alarm = self._alarm()
        picking = self.order.picking_ids
        picking.move_ids.write({'quantity': 1, 'picked': True})
        action = picking.button_validate()
        if isinstance(action, dict) and action.get('res_model') == 'stock.backorder.confirmation':
            wizard = self.env['stock.backorder.confirmation'].with_context(**action['context']).create({})
            wizard.process()
        self.assertEqual(self.order.receipt_status, 'partial')
        self.assertTrue(alarm._is_deliverable())

    def test_registered_pc_follows_revised_date(self):
        owner = self.env.ref('base.user_admin')
        agent = new_test_user(self.env, login='arrival_agent', groups='native_alarm.group_alarm_companion')
        device = self.env['native.alarm.device'].create({'name': 'Arrival PC', 'service_user_id': agent.id,
                                                        'allowed_user_ids': [(6, 0, owner.ids)]})
        alarm = self._alarm()
        alarm.write({'delivery': 'device', 'device_id': device.id})
        revised = self.order.date_planned + timedelta(days=1)
        self.order.order_line.date_planned = revised
        device.with_user(agent).companion_sync()
        alarm.invalidate_recordset()
        self.assertEqual(alarm.alarm_at, revised)
        self.assertIn(self.order.name, alarm._payload()['name'])

    def test_draft_and_tampering_rejected(self):
        draft = self.order.copy()
        with self.assertRaises(UserError):
            draft.action_set_arrival_alarm()
        alarm = self._alarm()
        with self.assertRaises(AccessError), self.cr.savepoint():
            alarm.write({'purchase_arrival_date': fields.Datetime.now()})
        with self.assertRaises(AccessError), self.cr.savepoint():
            alarm.write({'res_id': draft.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['native.alarm'].create({'name': 'Invalid', 'model_id': self.env['ir.model']._get_id('purchase.order'),
                'res_id': draft.id, 'alarm_at': fields.Datetime.now(), 'purchase_arrival_tracking': True})

    def test_user_and_company_access(self):
        other = new_test_user(self.env, login='arrival_other', groups='base.group_user,purchase.group_purchase_user')
        alarm = self._alarm()
        with self.assertRaises(AccessError):
            alarm.with_user(other).read(['name'])
        company = self.env['res.company'].create({'name': 'Another company'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['native.alarm'].with_context(default_purchase_arrival_tracking=True).create({
                'name': 'Wrong company', 'model_id': self.env['ir.model']._get_id('purchase.order'),
                'res_id': self.order.id, 'company_id': company.id, 'alarm_at': self.order.date_planned})
