from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from .instrumentation import logged_operation

class ResCompany(models.Model):
    _inherit = 'res.company'

    alarm_poll_seconds = fields.Integer(default=15)
    alarm_cache_hours = fields.Integer(default=24)
    alarm_missed_minutes = fields.Integer(default=60)
    alarm_snooze_minutes = fields.Integer(default=5)
    alarm_ring_seconds = fields.Integer(default=60, help='Zero rings until acknowledged.')
    alarm_sound_id = fields.Many2one('native.alarm.sound', string='Default alarm sound', check_company=True,
        help='Company-wide default. Individual alarms can select another sound. Empty uses the built-in tone.')
    alarm_sound_max_mb = fields.Integer(string='Maximum audio upload (MB)', default=20)
    alarm_delivery = fields.Selection(
        selection=lambda self: self.env['native.alarm']._fields['delivery']._description_selection(self.env),
        string='Default delivery', default='browser', required=True)
    alarm_device_id = fields.Many2one('native.alarm.device', string='Default alarm PC', check_company=True)
    alarm_repeat_minutes = fields.Integer(string='Default repeat (minutes)', default=0)
    alarm_cancel_on_completion = fields.Boolean(string='Silence when completed by default', default=True)

    def _native_alarm_defaults(self, user=None):
        """One source of defaults for record alarms and the activity scheduler."""
        self.ensure_one()
        recipient = user or self.env.user
        device = self.env['native.alarm.device']
        if self.alarm_device_id:
            device = device.with_user(recipient).with_context(allowed_company_ids=[self.id]).search([
                ('id', '=', self.alarm_device_id.id), ('active', '=', True),
                ('company_id', '=', self.id), ('allowed_user_ids', 'in', recipient.ids)], limit=1)
        return {'delivery': self.alarm_delivery, 'device_id': device.id or False,
                'snooze_minutes': self.alarm_snooze_minutes, 'ring_seconds': self.alarm_ring_seconds,
                'repeat_minutes': self.alarm_repeat_minutes,
                'cancel_on_completion': self.alarm_cancel_on_completion}

    @api.constrains('alarm_delivery', 'alarm_device_id')
    def _check_default_alarm_device(self):
        for company in self:
            device = company.alarm_device_id
            if device and (device.company_id != company or not device.active):
                raise ValidationError(_('The default alarm PC must be active and belong to this company.'))
            if company.alarm_delivery != 'browser' and not device:
                raise ValidationError(_('Select a default alarm PC for PC delivery.'))

    @api.constrains('alarm_sound_id')
    def _check_sound_company(self):
        for company in self:
            sound = company.alarm_sound_id
            if sound.company_id and sound.company_id != company:
                raise ValidationError(_('The default sound must be shared or belong to this company.'))

    @api.constrains('alarm_poll_seconds', 'alarm_cache_hours', 'alarm_missed_minutes',
                    'alarm_snooze_minutes', 'alarm_ring_seconds', 'alarm_sound_max_mb', 'alarm_repeat_minutes')
    def _check_alarm_settings(self):
        for company in self:
            if (company.alarm_poll_seconds <= 0 or company.alarm_cache_hours <= 0
                    or company.alarm_missed_minutes < 0 or company.alarm_snooze_minutes <= 0
                    or company.alarm_ring_seconds < 0 or company.alarm_sound_max_mb <= 0
                    or company.alarm_repeat_minutes < 0):
                raise ValidationError(_('Alarm intervals must be positive; ring duration, repeat and missed tolerance may be zero.'))


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    alarm_poll_seconds = fields.Integer(related='company_id.alarm_poll_seconds', readonly=False)
    alarm_cache_hours = fields.Integer(related='company_id.alarm_cache_hours', readonly=False)
    alarm_missed_minutes = fields.Integer(related='company_id.alarm_missed_minutes', readonly=False)
    alarm_snooze_minutes = fields.Integer(related='company_id.alarm_snooze_minutes', readonly=False)
    alarm_ring_seconds = fields.Integer(related='company_id.alarm_ring_seconds', readonly=False)
    alarm_sound_id = fields.Many2one(related='company_id.alarm_sound_id', readonly=False)
    alarm_sound_max_mb = fields.Integer(related='company_id.alarm_sound_max_mb', readonly=False)
    alarm_delivery = fields.Selection(related='company_id.alarm_delivery', readonly=False)
    alarm_device_id = fields.Many2one(related='company_id.alarm_device_id', readonly=False)
    alarm_repeat_minutes = fields.Integer(related='company_id.alarm_repeat_minutes', readonly=False)
    alarm_cancel_on_completion = fields.Boolean(related='company_id.alarm_cancel_on_completion', readonly=False)

    @logged_operation('SAVE_DELIVERY_DEFAULTS')
    def _write_alarm_delivery_defaults(self, company, values):
        # Related-field inverses run individually. Stage the coupled options in one
        # company write so its constraints never see half of a valid Settings save.
        company.write({name: values[name] for name in ('alarm_delivery', 'alarm_device_id') if name in values})

    @api.model_create_multi
    def create(self, vals_list):
        self.check_access('create')
        for values in vals_list:
            if 'alarm_delivery' in values or 'alarm_device_id' in values:
                company = self.env['res.company'].browse(values.get('company_id') or self.env.company.id)
                self._write_alarm_delivery_defaults(company, values)
        return super().create(vals_list)

    def write(self, values):
        if 'alarm_delivery' in values or 'alarm_device_id' in values:
            self.check_access('write')
            for settings in self:
                company = self.env['res.company'].browse(values.get('company_id') or settings.company_id.id)
                settings._write_alarm_delivery_defaults(company, values)
        return super().write(values)

    @logged_operation('SAVE_SETTINGS')
    def set_values(self):
        return super().set_values()


class AlarmTarget(models.Model):
    _name = 'native.alarm.target'
    _description = 'Enabled Alarm Record Type'
    _rec_name = 'res_model'

    model_id = fields.Many2one('ir.model', required=True, ondelete='cascade',
                              domain=[('transient', '=', False)])
    res_model = fields.Char(related='model_id.model', string='Technical model', store=True, readonly=True)
    action_id = fields.Many2one('ir.actions.server', readonly=True, copy=False, ondelete='set null')
    _sql_constraints = [('model_unique', 'unique(model_id)', 'This record type already supports alarms.')]

    @api.model_create_multi
    @logged_operation('ENABLE_MODEL')
    def create(self, vals_list):
        records = super().create(vals_list)
        for target in records:
            if target.model_id.transient or target.model_id.model.startswith('native.alarm'):
                raise ValidationError(_('Choose a persistent business record type.'))
            # The fixed action is created only through the administrator-only target ACL.
            action = self.env['ir.actions.server'].sudo().create({
                'name': _('Set Alarm'), 'model_id': target.model_id.id,
                'binding_model_id': target.model_id.id, 'binding_view_types': 'form,list',
                'groups_id': [(4, self.env.ref('base.group_user').id)],
                'state': 'code',
                'code': "action = env['native.alarm'].action_from_record(records._name, records.ids)",
            })
            super(AlarmTarget, target).write({'action_id': action.id})
        return records

    def write(self, vals):
        if ('action_id' in vals or ('model_id' in vals and any(t.model_id.id != vals['model_id'] for t in self))):
            raise ValidationError(_('Remove and recreate the integration to change its record type.'))
        return super().write(vals)

    @logged_operation('DISABLE_MODEL')
    def unlink(self):
        actions = self.action_id
        result = super().unlink()
        actions.sudo().unlink()
        return result
