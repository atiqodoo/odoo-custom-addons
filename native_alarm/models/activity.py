from odoo import api, fields, models
from .instrumentation import logged_operation

class MailActivity(models.Model):
    _inherit = 'mail.activity'

    def action_set_native_alarm(self):
        return self.env['native.alarm'].action_from_record(self._name, self.ids)

    def _native_alarm_is_active(self):
        self.ensure_one()
        return self.active and self.state != 'done'

    def _native_alarm_source_record(self):
        self.ensure_one()
        return self.env[self.res_model].browse(self.res_id)


class ActivitySchedule(models.TransientModel):
    _inherit = 'mail.activity.schedule'

    native_alarm_enabled = fields.Boolean(string='Ring an alarm')
    native_alarm_at = fields.Datetime(string='Alarm date and time')
    native_alarm_delivery = fields.Selection(
        selection=lambda self: self.env['native.alarm']._fields['delivery']._description_selection(self.env),
        string='Delivery', required=True)
    native_alarm_device_id = fields.Many2one('native.alarm.device', string='Alarm PC')
    native_alarm_snooze_minutes = fields.Integer(string='Snooze minutes')
    native_alarm_ring_seconds = fields.Integer(string='Ring seconds', help='Zero rings until stopped.')
    native_alarm_repeat_minutes = fields.Integer(string='Repeat minutes', help='Zero disables repeat; repeats after Stop.')
    native_alarm_cancel_on_completion = fields.Boolean(string='Silence when completed')

    _native_alarm_option_map = {
        'native_alarm_delivery': 'delivery', 'native_alarm_device_id': 'device_id',
        'native_alarm_snooze_minutes': 'snooze_minutes', 'native_alarm_ring_seconds': 'ring_seconds',
        'native_alarm_repeat_minutes': 'repeat_minutes', 'native_alarm_cancel_on_completion': 'cancel_on_completion',
    }

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if set(fields_list).intersection(self._native_alarm_option_map):
            defaults = self.env.company._native_alarm_defaults()
            for name in fields_list:
                if name in self._native_alarm_option_map:
                    values.setdefault(name, defaults[self._native_alarm_option_map[name]])
        return values

    @api.model_create_multi
    @logged_operation('ACTIVITY_DEFAULTS')
    def create(self, vals_list):
        records = super().create(vals_list)
        for wizard, explicit in zip(records, vals_list):
            defaults = wizard.company_id._native_alarm_defaults(wizard.activity_user_id or self.env.user)
            wizard.write({name: defaults[target] for name, target in self._native_alarm_option_map.items()
                          if name not in explicit and 'default_' + name not in self.env.context})
        return records

    @api.onchange('company_id', 'activity_user_id')
    def _onchange_native_alarm_recipient(self):
        for wizard in self:
            defaults = (wizard.company_id or self.env.company)._native_alarm_defaults(
                wizard.activity_user_id or self.env.user)
            wizard.update({name: defaults[target] for name, target in self._native_alarm_option_map.items()})

    @logged_operation('ACTIVITY_SCHEDULE')
    def _action_schedule_activities(self):
        activities = super()._action_schedule_activities()
        if self.native_alarm_enabled:
            self.env['native.alarm'].create([{
                'name': activity.summary or activity.display_name,
                'model_id': self.env['ir.model']._get_id('mail.activity'), 'res_id': activity.id,
                'user_id': activity.user_id.id, 'alarm_at': self.native_alarm_at,
                **{target: (self[name].id if target == 'device_id' else self[name])
                   for name, target in self._native_alarm_option_map.items()},
                'company_id': self.company_id.id,
            } for activity in activities])
        return activities
