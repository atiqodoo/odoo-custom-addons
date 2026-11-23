from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestSaleAlarm(TransactionCase):
    def test_quotation_cancellation_suppresses_alarm(self):
        partner = self.env['res.partner'].create({'name': 'Alarm customer'})
        order = self.env['sale.order'].create({'partner_id': partner.id})
        action = self.env['native.alarm'].action_from_record('sale.order', order.ids)
        self.assertEqual(action['context']['default_res_id'], order.id)
        alarm = self.env['native.alarm'].create({
            'name': order.name, 'model_id': self.env['ir.model']._get_id('sale.order'),
            'res_id': order.id, 'alarm_at': fields.Datetime.now(),
            'user_id': self.env.ref('base.user_admin').id})
        self.assertTrue(alarm._is_deliverable())
        order.action_cancel()
        self.assertFalse(alarm._is_deliverable())
