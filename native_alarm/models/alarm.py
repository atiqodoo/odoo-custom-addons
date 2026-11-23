from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from .instrumentation import logged_operation

class NativeAlarm(models.Model):
    _name = 'native.alarm'
    _description = 'Record Alarm'
    _order = 'alarm_at, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    user_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user,
                              domain=[('share', '=', False)], check_company=True)
    timezone = fields.Char(compute='_compute_timezone', string='Your display timezone')
    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade')
    res_model = fields.Char(related='model_id.model', string='Linked record type', store=True)
    res_id = fields.Many2oneReference(model_field='res_model', required=True, string='Record ID')
    alarm_at = fields.Datetime(required=True, index=True)
    state = fields.Selection([('scheduled', 'Scheduled'), ('acknowledged', 'Stopped'),
                              ('cancelled', 'Cancelled')], default='scheduled', required=True, index=True)
    delivery = fields.Selection([('browser', 'My Odoo browser'), ('device', 'Registered PC'),
                                 ('both', 'Browser and PC')], required=True)
    device_id = fields.Many2one('native.alarm.device', check_company=True)
    sound_id = fields.Many2one('native.alarm.sound', string='Sound override', check_company=True,
        domain=[('active', '=', True)], help='Leave empty to use the default sound configured in Settings > Alarms.')
    snooze_minutes = fields.Integer(required=True)
    ring_seconds = fields.Integer(required=True,
                                  help='Zero rings until stopped.')
    repeat_minutes = fields.Integer(help='Zero disables repeat; otherwise repeats after Stop, in elapsed minutes.')
    cancel_on_completion = fields.Boolean(string='Silence when completed',
        help='Suppress delivery while the linked record is completed or archived. Use Cancel Alarm to cancel permanently.')
    revision = fields.Integer(default=1, readonly=True, copy=False)

    _alarm_option_fields = ('delivery', 'device_id', 'snooze_minutes', 'ring_seconds',
                            'repeat_minutes', 'cancel_on_completion')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if set(fields_list).intersection(self._alarm_option_fields):
            company = self.env['res.company'].browse(values.get('company_id')
                or self.env.context.get('default_company_id') or self.env.company.id)
            user = self.env['res.users'].browse(values.get('user_id')
                or self.env.context.get('default_user_id') or self.env.uid)
            defaults = company._native_alarm_defaults(user)
            for name in fields_list:
                if name in defaults:
                    values.setdefault(name, defaults[name])
        return values

    @api.depends_context('uid', 'tz')
    def _compute_timezone(self):
        for alarm in self:
            alarm.timezone = self.env.context.get('tz') or self.env.user.tz or 'UTC'

    def _source(self, user=None):
        self.ensure_one()
        model = self.env[self.res_model].with_user(user or self.env.user)
        if user:
            model = model.with_context(allowed_company_ids=[self.company_id.id])
        record = model.browse(self.res_id).exists()
        if not record:
            raise UserError(self.env._('The linked record no longer exists.'))
        record.check_access('read')
        return record

    @api.model
    def _check_recipient_company(self, user, company):
        if user.share or company not in user.company_ids:
            raise ValidationError(self.env._('Choose an internal recipient with access to the alarm company.'))

    @api.constrains('model_id', 'res_id', 'user_id', 'company_id', 'delivery', 'device_id',
                    'snooze_minutes', 'ring_seconds', 'repeat_minutes', 'alarm_at')
    def _check_configuration(self):
        for alarm in self:
            if (not self.env.su and alarm.user_id != self.env.user
                    and not self.env.user.has_group('native_alarm.group_alarm_manager')):
                raise AccessError(_('Only an alarm administrator may schedule alarms for another user.'))
            if not self.env['native.alarm.target'].search_count([('model_id', '=', alarm.model_id.id)]):
                raise ValidationError(_('An administrator must enable this record type for alarms.'))
            alarm._check_recipient_company(alarm.user_id, alarm.company_id)
            if alarm.snooze_minutes <= 0 or alarm.ring_seconds < 0 or alarm.repeat_minutes < 0:
                raise ValidationError(_('Snooze must be positive; ring duration and repeat cannot be negative.'))
            alarm._source()
            source = alarm._source(alarm.user_id)
            if 'company_id' in source._fields and source.company_id and source.company_id != alarm.company_id:
                raise ValidationError(_('The alarm and linked record must belong to the same company.'))
            if alarm.delivery != 'browser':
                if not alarm.device_id or not alarm.device_id.active:
                    raise ValidationError(_('Select an active registered PC.'))
                if alarm.user_id not in alarm.device_id.allowed_user_ids:
                    raise AccessError(_('This recipient is not authorised to ring the selected PC.'))

    @api.model_create_multi
    @logged_operation('SCHEDULE')
    def create(self, vals_list):
        prepared = []
        defaults_cache = {}
        for vals in vals_list:
            vals = dict(vals)
            vals.pop('revision', None)
            if vals.get('state', 'scheduled') != 'scheduled':
                raise ValidationError(_('New alarms must be scheduled.'))
            key = (vals.get('company_id', self.env.context.get('default_company_id', self.env.company.id)),
                   vals.get('user_id', self.env.context.get('default_user_id', self.env.uid)))
            self._check_recipient_company(self.env['res.users'].browse(key[1]), self.env['res.company'].browse(key[0]))
            if key not in defaults_cache:
                defaults_cache[key] = self.with_context(default_company_id=key[0], default_user_id=key[1]).default_get(
                    list(self._alarm_option_fields))
            prepared.append(dict(defaults_cache[key], **vals))
        return super().create(prepared)

    @logged_operation('UPDATE')
    def write(self, vals):
        vals = dict(vals)
        vals.pop('revision', None)
        # Serialize mutations through ORM row updates; each edit invalidates cached deliveries.
        for alarm in self:
            super(NativeAlarm, alarm).write(dict(vals, revision=alarm.revision + 1))
        return True

    @logged_operation('DELETE')
    def unlink(self):
        return super().unlink()

    @api.model
    @logged_operation('OPEN_SCHEDULER')
    def action_from_record(self, model, record_ids):
        if len(record_ids) != 1:
            raise UserError(_('Select exactly one saved record to set its alarm.'))
        target = self.env['native.alarm.target'].search([('res_model', '=', model)], limit=1)
        if not target:
            raise AccessError(_('Alarms are not enabled for this record type.'))
        record = self.env[model].browse(record_ids).exists()
        record.check_access('read')
        if not record:
            raise UserError(_('Save the record before setting an alarm.'))
        company = record.company_id if 'company_id' in record._fields and record.company_id else self.env.company
        return {'type': 'ir.actions.act_window', 'name': _('Set Alarm'), 'res_model': self._name,
                'view_mode': 'form', 'target': 'new', 'context': {
                    'default_name': record.display_name, 'default_model_id': target.model_id.id,
                    'default_res_id': record.id, 'default_company_id': company.id,
                    'default_user_id': self.env.uid,
                }}

    def _navigation_source(self):
        """Connectors can resolve a technical reminder to its business document."""
        record = self._source()
        resolver = getattr(record, '_native_alarm_source_record', None)
        if resolver:
            record = resolver().with_user(self.env.user).exists()
        if not record:
            raise UserError(_('The source record no longer exists.'))
        record.ensure_one()
        record.check_access('read')
        if 'company_id' in record._fields and record.company_id and record.company_id != self.company_id:
            raise AccessError(_('The source record belongs to another company.'))
        return record

    @logged_operation('OPEN_SOURCE')
    def action_open_record(self):
        self.ensure_one()
        self.check_access('read')
        record = self._navigation_source()
        return {'type': 'ir.actions.act_window', 'res_model': record._name,
                'res_id': record.id, 'view_mode': 'form', 'target': 'current'}

    def _is_deliverable(self, source=None, enabled_models=None):
        self.ensure_one()
        if enabled_models is None:
            enabled_models = self.env['native.alarm.target'].search([]).model_id.ids
        if (not self.user_id.active or self.user_id.share or self.company_id not in self.user_id.company_ids
                or self.model_id.id not in enabled_models):
            return False
        try:
            if source is None:
                source = self._source(self.user_id)
        except (AccessError, UserError):
            return False
        if 'company_id' in source._fields and source.company_id and source.company_id != self.company_id:
            return False
        if self.cancel_on_completion:
            hook = getattr(source, '_native_alarm_is_active', None)
            return hook() if hook else ('active' not in source._fields or source.active)
        return True

    def _deliverable_alarms(self):
        """Resolve source access in batches per recipient/model, rather than per alarm."""
        result = self.browse()
        enabled = self.env['native.alarm.target'].search([]).model_id.ids
        for user, user_alarms in self.grouped('user_id').items():
            for model, alarms in user_alarms.grouped('res_model').items():
                try:
                    sources = self.env[model].with_user(user).with_context(
                        allowed_company_ids=user.company_ids.ids, active_test=False,
                    ).search([('id', 'in', alarms.mapped('res_id'))])
                    if not sources.has_access('read'):
                        # Custom access checks (notably Activities' source-document check)
                        # must also be honoured after search. Fall back only for mixed-access batches.
                        sources = sources.filtered(lambda source: source.has_access('read'))
                except AccessError:
                    continue
                by_id = {source.id: source for source in sources}
                result |= alarms.filtered(lambda a: a.res_id in by_id and a._is_deliverable(by_id[a.res_id], enabled))
        return result

    def _payload(self):
        self.ensure_one()
        sound = self.sound_id or self.company_id.alarm_sound_id
        if sound and not sound.active:
            sound = self.env['native.alarm.sound']
        return {'id': self.id, 'revision': self.revision, 'name': self.name,
                'alarm_at': fields.Datetime.to_string(self.alarm_at),
                'ring_seconds': self.ring_seconds, 'snooze_minutes': self.snooze_minutes,
                'sound': sound._descriptor() if sound else False}

    @api.model
    @logged_operation('BROWSER_SYNC')
    def browser_schedule(self):
        company = self.env.company
        now = fields.Datetime.now()
        alarms = self.search([('user_id', '=', self.env.uid), ('company_id', '=', company.id),
                              ('state', '=', 'scheduled'), ('delivery', 'in', ['browser', 'both']),
                              ('alarm_at', '<=', now + timedelta(hours=company.alarm_cache_hours))])
        return {'alarms': [a._payload() for a in alarms._deliverable_alarms()],
                'server_time': fields.Datetime.to_string(now), 'poll_seconds': company.alarm_poll_seconds,
                'missed_minutes': company.alarm_missed_minutes}

    def action_stop(self):
        return self._respond('stop')

    def action_snooze(self):
        return self._respond('snooze')

    def action_cancel(self):
        return self.write({'state': 'cancelled'})

    @logged_operation('RESPOND')
    def _respond(self, operation, expected_revision=None):
        self.ensure_one()
        self.check_access('write')
        # A row lock is necessary for atomic device/browser acknowledgement of a revision.
        # ORM reads alone cannot make the compare-and-update atomic across workers.
        self.flush_recordset()
        self.env.cr.execute('SELECT id FROM native_alarm WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset(['revision', 'state', 'alarm_at'])
        if self.state != 'scheduled' or (expected_revision is not None and self.revision != expected_revision):
            return False
        if operation == 'snooze':
            values = {'alarm_at': fields.Datetime.now() + timedelta(minutes=self.snooze_minutes)}
        elif operation == 'stop':
            values = ({'alarm_at': max(fields.Datetime.now(), self.alarm_at) + timedelta(minutes=self.repeat_minutes)}
                      if self.repeat_minutes else {'state': 'acknowledged'})
        else:
            raise ValidationError(_('Unsupported alarm response.'))
        return self.write(values)

    def browser_respond(self, operation, revision):
        self.ensure_one()
        if self.user_id != self.env.user or self.delivery not in ('browser', 'both'):
            raise AccessError(_('This browser is not an alarm recipient.'))
        return self._respond(operation, revision)
