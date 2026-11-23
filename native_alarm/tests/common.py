from odoo import fields
from odoo.tests.common import TransactionCase, new_test_user


class AlarmCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = new_test_user(cls.env, login='alarm_owner', groups='base.group_user,base.group_partner_manager')
        cls.other = new_test_user(cls.env, login='alarm_other', groups='base.group_user')
        cls.agent = new_test_user(cls.env, login='alarm_agent', groups='native_alarm.group_alarm_companion')
        cls.partner = cls.env['res.partner'].create({'name': 'Alarm target'})
        cls.target = cls.env['native.alarm.target'].create({'model_id': cls.env['ir.model']._get_id('res.partner')})
        cls.device = cls.env['native.alarm.device'].create({
            'name': 'LAN workstation', 'service_user_id': cls.agent.id,
            'allowed_user_ids': [(6, 0, cls.owner.ids)]})

    def alarm(self, **values):
        data = {'name': 'Follow up', 'model_id': self.target.model_id.id,
                'res_id': self.partner.id, 'user_id': self.owner.id,
                'alarm_at': fields.Datetime.now(), 'delivery': 'browser'}
        data.update(values)
        return self.env['native.alarm'].with_user(self.owner).create(data)
