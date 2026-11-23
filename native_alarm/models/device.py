from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from .instrumentation import logged_operation

class AlarmDevice(models.Model):
    _name = 'native.alarm.device'
    _description = 'Registered Alarm PC'
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    service_user_id = fields.Many2one('res.users', required=True, check_company=True,
                                     help='Dedicated internal account used by this PC with an Odoo API key.')
    allowed_user_ids = fields.Many2many('res.users', string='Users allowed to ring this PC', check_company=True)
    last_seen = fields.Datetime(readonly=True)

    @api.constrains('service_user_id', 'allowed_user_ids', 'company_id')
    def _check_users(self):
        for device in self:
            for user in device.service_user_id | device.allowed_user_ids:
                if user.share or device.company_id not in user.company_ids:
                    raise ValidationError(_('Device accounts must be internal users of the selected company.'))

    def _authorize_companion(self):
        self.ensure_one()
        self.check_access('read')
        if (not self.active or self.service_user_id != self.env.user
                or not self.env.user.has_group('native_alarm.group_alarm_companion')):
            raise AccessError(_('This account is not registered for this alarm PC.'))

    @logged_operation('DEVICE_SYNC')
    def companion_sync(self, responses=None):
        self._authorize_companion()
        responses = [] if responses is None else responses
        if not isinstance(responses, list):
            raise ValidationError(_('Invalid alarm response batch.'))
        for response in responses or []:
            if (not isinstance(response, dict) or not isinstance(response.get('id'), int)
                    or not isinstance(response.get('revision'), int)
                    or response.get('operation') not in ('stop', 'snooze')
                    or not isinstance(response.get('event_id'), str)):
                raise ValidationError(_('Invalid alarm response.'))
        # Deliberate privilege boundary: a registered service account can only exchange
        # minimal payloads for its own device; source access is checked as the recipient.
        alarms = self.env['native.alarm'].sudo().with_company(self.company_id)
        accepted = []
        for response in responses or []:
            alarm = alarms.search([('id', '=', response['id']), ('device_id', '=', self.id),
                                   ('company_id', '=', self.company_id.id),
                                   ('delivery', 'in', ['device', 'both'])], limit=1)
            if alarm and alarm.user_id in self.allowed_user_ids:
                if alarm._is_deliverable():
                    alarm._respond(response['operation'], response['revision'])
                accepted.append(response['event_id'])
            else:
                # Discard revoked/deleted deliveries without acknowledging another device's alarm.
                accepted.append(response['event_id'])
        now = fields.Datetime.now()
        company = self.company_id
        scheduled = alarms.search([('device_id', '=', self.id), ('company_id', '=', company.id),
                                    ('user_id', 'in', self.allowed_user_ids.ids), ('state', '=', 'scheduled'),
                                    ('delivery', 'in', ['device', 'both']),
                                    ('alarm_at', '<=', now + timedelta(hours=company.alarm_cache_hours))])
        payload = [alarm._payload() for alarm in scheduled._deliverable_alarms()]
        self.sudo().write({'last_seen': now})
        return {'alarms': payload, 'accepted': accepted, 'server_time': fields.Datetime.to_string(now),
                'poll_seconds': company.alarm_poll_seconds, 'missed_minutes': company.alarm_missed_minutes}

    @api.model_create_multi
    @logged_operation('REGISTER_DEVICE')
    def create(self, vals_list):
        return super().create(vals_list)

    @logged_operation('UPDATE_DEVICE')
    def write(self, vals):
        return super().write(vals)

    @logged_operation('DELETE_DEVICE')
    def unlink(self):
        return super().unlink()
