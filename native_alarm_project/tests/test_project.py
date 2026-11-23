from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestProjectAlarm(TransactionCase):
    def test_completed_task_suppresses_alarm(self):
        task = self.env['project.task'].create({'name': 'Alarm task',
            'user_ids': [(4, self.env.ref('base.user_admin').id)]})
        alarm = self.env['native.alarm'].create({
            'name': task.name, 'model_id': self.env['ir.model']._get_id('project.task'),
            'res_id': task.id, 'alarm_at': fields.Datetime.now(),
            'user_id': self.env.ref('base.user_admin').id})
        self.assertTrue(alarm._is_deliverable())
        task.state = '1_done'
        self.assertFalse(alarm._is_deliverable())
        alarm.cancel_on_completion = False
        self.assertTrue(alarm._is_deliverable())
