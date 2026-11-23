from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, tagged
from .common import AlarmCase


@tagged('post_install', '-at_install')
class TestAlarmDefaults(AlarmCase):
    def configure(self, **overrides):
        values = dict(alarm_delivery='both', alarm_device_id=self.device.id,
                      alarm_snooze_minutes=7, alarm_ring_seconds=0, alarm_repeat_minutes=12,
                      alarm_cancel_on_completion=False)
        values.update(overrides)
        self.env.company.write(values)

    def wizard(self, **overrides):
        values = dict(res_model='res.partner', res_ids=str(self.partner.ids),
            activity_type_id=self.env.ref('mail.mail_activity_data_todo').id,
            activity_user_id=self.owner.id, date_deadline=fields.Date.today(),
            native_alarm_enabled=True, native_alarm_at=fields.Datetime.now())
        values.update(overrides)
        return self.env['mail.activity.schedule'].with_user(self.owner).with_context(
            active_model='res.partner', active_ids=self.partner.ids).create(values)

    def test_new_record_alarm_uses_company_options(self):
        self.configure()
        alarm = self.env['native.alarm'].with_user(self.owner).create({
            'name': 'Default delivery', 'model_id': self.target.model_id.id,
            'res_id': self.partner.id, 'alarm_at': fields.Datetime.now()})
        self.assertEqual((alarm.delivery, alarm.device_id, alarm.ring_seconds, alarm.snooze_minutes,
                          alarm.repeat_minutes, alarm.cancel_on_completion),
                         ('both', self.device, 0, 7, 12, False))
        defaults = self.env['native.alarm'].with_user(self.owner).default_get(['delivery', 'device_id', 'repeat_minutes'])
        self.assertEqual(defaults, dict(delivery='both', device_id=self.device.id, repeat_minutes=12))

    def test_activity_defaults_and_overrides_are_copied_to_alarm(self):
        self.configure()
        wizard = self.wizard(native_alarm_repeat_minutes=0, native_alarm_ring_seconds=90)
        self.assertEqual(wizard.native_alarm_delivery, 'both')
        self.assertEqual(wizard.native_alarm_device_id, self.device)
        activities = wizard._action_schedule_activities()
        alarm = self.env['native.alarm'].search([('res_model', '=', 'mail.activity'), ('res_id', 'in', activities.ids)])
        self.assertEqual((alarm.delivery, alarm.device_id, alarm.ring_seconds, alarm.repeat_minutes,
                          alarm.snooze_minutes, alarm.cancel_on_completion), ('both', self.device, 90, 0, 7, False))

    def test_explicit_false_zero_and_context_defaults_are_preserved(self):
        self.configure()
        alarm = self.alarm(delivery='browser', device_id=False, ring_seconds=0,
                           repeat_minutes=0, cancel_on_completion=True)
        self.assertEqual((alarm.delivery, alarm.device_id.id, alarm.ring_seconds,
                          alarm.repeat_minutes, alarm.cancel_on_completion), ('browser', False, 0, 0, True))
        defaults = self.env['native.alarm'].with_context(default_ring_seconds=33).default_get(['ring_seconds'])
        self.assertEqual(defaults['ring_seconds'], 33)

    def test_settings_changes_do_not_rewrite_existing_alarms(self):
        alarm = self.alarm()
        previous = (alarm.delivery, alarm.ring_seconds, alarm.repeat_minutes, alarm.cancel_on_completion)
        self.configure()
        self.assertEqual((alarm.delivery, alarm.ring_seconds, alarm.repeat_minutes, alarm.cancel_on_completion), previous)

    def test_unauthorized_pc_is_not_prefilled(self):
        self.configure()
        defaults = self.env.company._native_alarm_defaults(self.other)
        self.assertFalse(defaults['device_id'])
        self.assertEqual(defaults['delivery'], 'both')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['native.alarm'].with_user(self.other).create({
                'name': 'No PC permission', 'model_id': self.target.model_id.id,
                'res_id': self.partner.id, 'alarm_at': fields.Datetime.now()})

    def test_invalid_defaults_and_settings_permissions(self):
        for values in ({'alarm_repeat_minutes': -1}, {'alarm_delivery': 'device', 'alarm_device_id': False}):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.env.company.write(values)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env.company.with_user(self.owner).write({'alarm_repeat_minutes': 10})

    def test_native_settings_save_delivery_and_pc_together(self):
        settings = self.env['res.config.settings'].create({
            'company_id': self.env.company.id, 'alarm_delivery': 'both',
            'alarm_device_id': self.device.id, 'alarm_repeat_minutes': 18,
        })
        settings.set_values()
        self.assertEqual((self.env.company.alarm_delivery, self.env.company.alarm_device_id,
                          self.env.company.alarm_repeat_minutes), ('both', self.device, 18))
        settings.write({'alarm_delivery': 'browser', 'alarm_device_id': False})
        self.assertEqual(self.env.company.alarm_delivery, 'browser')
        self.assertFalse(self.env.company.alarm_device_id)
        settings.write({'alarm_delivery': 'device', 'alarm_device_id': self.device.id})
        self.assertEqual(self.env.company.alarm_delivery, 'device')

    def test_company_and_device_boundaries(self):
        company = self.env['res.company'].create({'name': 'Alarm defaults company', 'alarm_ring_seconds': 23})
        self.owner.company_ids |= company
        self.partner.company_id = company
        alarm = self.alarm(company_id=company.id)
        self.assertEqual(alarm.ring_seconds, 23)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            company.write({'alarm_device_id': self.device.id})

    def test_native_activity_form_initializes_company_defaults(self):
        self.configure()
        model = self.env['mail.activity.schedule'].with_user(self.owner).with_context(
            active_model='res.partner', active_ids=self.partner.ids)
        with Form(model) as form:
            self.assertEqual(form.native_alarm_delivery, 'both')
            self.assertEqual(form.native_alarm_device_id, self.device)
            self.assertEqual(form.native_alarm_ring_seconds, 0)
            self.assertEqual(form.native_alarm_repeat_minutes, 12)
