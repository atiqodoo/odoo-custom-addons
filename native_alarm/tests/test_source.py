from urllib.parse import parse_qs, urlsplit

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, new_test_user, tagged
from .common import AlarmCase


@tagged('post_install', '-at_install')
class TestAlarmSource(AlarmCase):
    def test_direct_record_opens_without_acknowledging(self):
        alarm = self.alarm()
        action = alarm.action_open_record()
        self.assertEqual((action['res_model'], action['res_id']), ('res.partner', self.partner.id))
        self.assertEqual(alarm.state, 'scheduled')

    def test_activity_opens_its_business_source(self):
        activity = self.env['mail.activity'].with_user(self.owner).create({
            'res_model_id': self.env['ir.model']._get_id('res.partner'), 'res_id': self.partner.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'user_id': self.owner.id,
        })
        alarm = self.alarm(model_id=self.env['ir.model']._get_id('mail.activity'), res_id=activity.id)
        action = alarm.action_open_record()
        self.assertEqual((action['res_model'], action['res_id']), ('res.partner', self.partner.id))

    def test_other_users_cannot_open_an_alarm_source(self):
        alarm = self.alarm()
        with self.assertRaises(AccessError):
            alarm.with_user(self.other).action_open_record()

    def test_deleted_source_has_clear_error(self):
        alarm = self.alarm()
        self.partner.unlink()
        with self.assertRaises(UserError):
            alarm.action_open_record()

    def test_company_boundary_is_checked_at_open_time(self):
        alarm = self.alarm()
        self.partner.company_id = self.env['res.company'].create({'name': 'Moved source'})
        with self.assertRaises(AccessError):
            alarm.action_open_record()


@tagged('post_install', '-at_install')
class TestAlarmSourceHttp(HttpCase):
    def test_authenticated_source_route_and_denied_access(self):
        owner = new_test_user(self.env, login='source_route_owner', password='route-test-password',
                              groups='base.group_user')
        other = new_test_user(self.env, login='source_route_other', password='route-test-password',
                              groups='base.group_user')
        partner = self.env['res.partner'].create({'name': 'Source route target'})
        self.env['native.alarm.target'].create({'model_id': self.env['ir.model']._get_id('res.partner')})
        alarm = self.env['native.alarm'].create({
            'name': 'Source route alarm', 'user_id': owner.id,
            'model_id': self.env['ir.model']._get_id('res.partner'), 'res_id': partner.id,
            'alarm_at': fields.Datetime.now(),
        })
        self.authenticate(owner.login, 'route-test-password')
        response = self.url_open(f'/native_alarm/{alarm.id}/source', allow_redirects=False)
        self.assertEqual(response.status_code, 303)
        destination = parse_qs(urlsplit(response.headers['Location']).fragment)
        self.assertEqual(destination['model'], ['res.partner'])
        self.assertEqual(destination['id'], [str(partner.id)])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.authenticate(other.login, 'route-test-password')
        self.assertEqual(self.url_open(f'/native_alarm/{alarm.id}/source').status_code, 404)
        self.assertEqual(self.url_open('/native_alarm/0/source').status_code, 404)
