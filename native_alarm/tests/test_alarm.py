from datetime import timedelta
from unittest.mock import patch
from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, tagged
from .common import AlarmCase
from odoo.addons.base.models.ir_ui_view import get_view_arch_from_file
from odoo.modules.module import get_module_resource


@tagged('post_install', '-at_install')
class TestNativeAlarm(AlarmCase):
    def test_views_reload_from_source_in_xml_development_mode(self):
        # Exercise the actual loader used by --dev=xml, not just database arch_db.
        # It concatenates field_arch.text with the serialized children and therefore
        # requires whitespace text before the first child in each arch field.
        for filename in ('alarm_views.xml', 'settings_views.xml', 'sound_views.xml', 'defaults_views.xml'):
            path = get_module_resource('native_alarm', 'views', filename)
            document = etree.parse(path)
            for view in document.xpath("//record[@model='ir.ui.view']"):
                with self.subTest(view=view.get('id')):
                    arch = get_view_arch_from_file(path, 'native_alarm.' + view.get('id'))
                    self.assertIsNotNone(etree.fromstring(arch.encode('utf-8')))

    def test_record_action_and_enabled_model(self):
        action = self.env['native.alarm'].with_user(self.owner).action_from_record('res.partner', self.partner.ids)
        self.assertEqual(action['context']['default_res_id'], self.partner.id)
        self.assertEqual(self.target.action_id.binding_model_id, self.target.model_id)
        bound_action = self.target.action_id.with_user(self.owner).with_context(
            active_model='res.partner', active_ids=self.partner.ids, active_id=self.partner.id,
        ).run()
        self.assertEqual(bound_action['res_model'], 'native.alarm')
        with self.assertRaises(AccessError):
            self.env['native.alarm'].with_user(self.owner).action_from_record('res.users', self.owner.ids)

    def test_native_form_creation_as_ordinary_user(self):
        model = self.env['native.alarm'].with_user(self.owner)
        action = model.action_from_record('res.partner', self.partner.ids)
        with Form(model.with_context(**action['context'])) as form:
            form.alarm_at = fields.Datetime.now()
        self.assertEqual(form.record.res_id, self.partner.id)
        self.assertEqual(form.record.model_id.id, self.target.model_id.id)
        self.assertEqual(form.record.web_read({'name': {}, 'res_model': {}, 'timezone': {}})[0]['name'], self.partner.name)

    def test_new_alarm_onchange_initializes_link_without_dynamic_many2one(self):
        model = self.env['native.alarm'].with_user(self.owner)
        action = model.action_from_record('res.partner', self.partner.ids)
        model = model.with_context(**action['context'])
        view = model.get_view(view_type='form')
        arch = etree.fromstring(view['arch'])
        self.assertTrue(arch.xpath("//field[@name='model_id'][@invisible='1']"))
        self.assertEqual(arch.xpath("//field[@name='res_id']/@widget"), ['many2one_reference_integer'])
        # Match the web client's initial onchange before the alarm has been saved.
        # The ID widget needs no dynamic relation or display-name fetch.
        result = model.onchange({}, [], {
            'model_id': {'fields': {'display_name': {}}},
            'res_model': {}, 'res_id': {}, 'name': {},
            'user_id': {'fields': {'display_name': {}}},
            'company_id': {'fields': {}}, 'alarm_at': {},
        })
        self.assertEqual(result['value']['res_model'], 'res.partner')
        self.assertEqual(result['value']['res_id'], self.partner.id)

    def test_revoked_recipient_and_disabled_integration_stop_delivery(self):
        alarm = self.alarm(delivery='device', device_id=self.device.id)
        self.device.write({'allowed_user_ids': [(5, 0, 0)]})
        self.assertEqual(self.device.with_user(self.agent).companion_sync()['alarms'], [])
        self.target.unlink()
        self.assertFalse(alarm._is_deliverable())

    def test_source_company_change_suppresses_delivery(self):
        alarm = self.alarm()
        other_company = self.env['res.company'].create({'name': 'Moved record company'})
        self.partner.company_id = other_company
        self.assertFalse(alarm._is_deliverable())

    def test_cannot_reassign_alarm_without_manager_role(self):
        alarm = self.alarm()
        with self.assertRaises(AccessError), self.cr.savepoint():
            alarm.write({'user_id': self.other.id})

    def test_browser_schedule_stop_snooze_repeat_and_stale_revision(self):
        alarm = self.alarm()
        self.assertIn(alarm.id, [a['id'] for a in alarm.browser_schedule()['alarms']])
        revision = alarm.revision
        self.assertTrue(alarm.browser_respond('snooze', revision))
        self.assertGreater(alarm.alarm_at, fields.Datetime.now())
        self.assertFalse(alarm.browser_respond('stop', revision))
        alarm.browser_respond('stop', alarm.revision)
        self.assertEqual(alarm.state, 'acknowledged')
        repeat = self.alarm(repeat_minutes=15)
        repeat.action_stop()
        self.assertEqual(repeat.state, 'scheduled')
        self.assertGreater(repeat.alarm_at, fields.Datetime.now())

    def test_other_user_cannot_read_or_respond(self):
        alarm = self.alarm()
        with self.assertRaises(AccessError):
            alarm.with_user(self.other).read(['name'])
        with self.assertRaises(AccessError):
            alarm.with_user(self.other).browser_respond('stop', alarm.revision)
        with self.assertRaises(AccessError):
            alarm.with_user(self.other).action_cancel()

    def test_device_isolated_and_retry_response_idempotent(self):
        alarm = self.alarm(delivery='device', device_id=self.device.id)
        device = self.device.with_user(self.agent)
        result = device.companion_sync()
        self.assertEqual([a['id'] for a in result['alarms']], alarm.ids)
        response = {'id': alarm.id, 'revision': alarm.revision, 'operation': 'snooze', 'event_id': 'retry'}
        device.companion_sync([response])
        alarm.invalidate_recordset()
        next_time = alarm.alarm_at
        device.companion_sync([response])
        alarm.invalidate_recordset()
        self.assertEqual(alarm.alarm_at, next_time)
        with self.assertRaises(AccessError):
            self.device.with_user(self.owner).companion_sync()

    def test_unauthorised_device_and_negative_intervals(self):
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.alarm(user_id=self.other.id, delivery='device', device_id=self.device.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.alarm(snooze_minutes=0)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.alarm(ring_seconds=-1)

    def test_source_deleted_or_permission_revoked_not_delivered(self):
        alarm = self.alarm()
        self.partner.unlink()
        self.assertNotIn(alarm.id, [a['id'] for a in alarm.browser_schedule()['alarms']])

    def test_company_boundaries(self):
        company = self.env['res.company'].create({'name': 'Alarm other company'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.alarm(company_id=company.id)

    def test_missed_alarm_policy_and_utc_datetime(self):
        now = fields.Datetime.to_datetime('2026-11-18 07:30:00')
        with patch.object(fields.Datetime, 'now', return_value=now):
            due = self.alarm(alarm_at=now)
            old = self.alarm(alarm_at=now - timedelta(minutes=61))
            ids = [a['id'] for a in due.browser_schedule()['alarms']]
            self.assertIn(due.id, ids)
            # Old schedules remain in snapshots so an already ringing player is not
            # interrupted; clients apply missed tolerance before starting a NEW ring.
            self.assertIn(old.id, ids)
            self.assertEqual(due._payload()['alarm_at'], '2026-11-18 07:30:00')

    def test_activity_schedule_native_alarm_and_completion(self):
        wizard = self.env['mail.activity.schedule'].with_user(self.owner).with_context(
            active_model='res.partner', active_ids=self.partner.ids,
        ).create({'res_model': 'res.partner', 'res_ids': str(self.partner.ids),
                  'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                  'activity_user_id': self.owner.id, 'date_deadline': fields.Date.today(),
                  'native_alarm_enabled': True, 'native_alarm_at': fields.Datetime.now()})
        activity = wizard._action_schedule_activities()
        alarm = self.env['native.alarm'].search([('res_model', '=', 'mail.activity'), ('res_id', '=', activity.id)])
        self.assertEqual(len(alarm), 1)
        self.assertTrue(alarm._is_deliverable())
        activity.action_done()
        self.assertFalse(alarm._is_deliverable())

    def test_non_manager_cannot_enable_models(self):
        with self.assertRaises(AccessError):
            self.env['native.alarm.target'].with_user(self.owner).create({
                'model_id': self.env['ir.model']._get_id('res.users')})

    def test_device_response_cannot_stop_another_devices_alarm(self):
        second = self.device.copy({'name': 'Another PC'})
        alarm = self.alarm(delivery='device', device_id=second.id)
        self.device.with_user(self.agent).companion_sync([{
            'id': alarm.id, 'revision': alarm.revision, 'operation': 'stop', 'event_id': 'wrong-device',
        }])
        alarm.invalidate_recordset()
        self.assertEqual(alarm.state, 'scheduled')
        with self.assertRaises(ValidationError):
            self.device.with_user(self.agent).companion_sync([{'id': alarm.id}])

    def test_company_settings_validation(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env.company.alarm_poll_seconds = 0

    def test_backend_asset_compilation(self):
        bundle = self.env['ir.qweb']._get_asset_bundle('web.assets_backend', css=False)
        alarm_asset = next(asset for asset in bundle.javascripts
                           if asset.url.endswith('/native_alarm/static/src/alarm_service.js'))
        self.assertIn('@native_alarm/alarm_service', alarm_asset.minify())
