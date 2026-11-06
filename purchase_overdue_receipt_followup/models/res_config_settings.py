import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Stage edits on the wizard. Independent writable related fields inverse
    # separately and can enable a company before its calendar has been written.
    receipt_followup_enabled = fields.Boolean(
        string='Overdue receipt follow-up', compute='_compute_receipt_followup_settings',
        store=True, readonly=False)
    receipt_followup_calendar_id = fields.Many2one(
        'resource.calendar', string='Receiving calendar',
        compute='_compute_receipt_followup_settings', store=True, readonly=False,
        domain="[('company_id', 'in', [False, company_id]), ('flexible_hours', '=', False)]")
    receipt_followup_grace_hours = fields.Float(
        string='Overdue grace (working hours)', compute='_compute_receipt_followup_settings',
        store=True, readonly=False)
    delivery_hours_per_day = fields.Float(related='company_id.delivery_hours_per_day', readonly=False)
    delivery_planning_horizon_days = fields.Integer(related='company_id.delivery_planning_horizon_days', readonly=False)

    @api.depends('company_id')
    def _compute_receipt_followup_settings(self):
        for settings in self:
            company = settings.company_id
            settings.receipt_followup_enabled = company.receipt_followup_enabled
            settings.receipt_followup_calendar_id = company.receipt_followup_calendar_id
            settings.receipt_followup_grace_hours = company.receipt_followup_grace_hours

    def set_values(self):
        self.ensure_one()
        if not self.env.is_admin():
            raise AccessError(_('Only administrators can change the settings.'))
        _logger.debug('[OVERDUE_RECEIPT][SETTINGS_SAVE][START] company_id=%s user_id=%s',
                      self.company_id.id, self.env.uid)
        try:
            # Preserve company validation and ordinary write permissions. All three
            # values must reach the constraint in the same company.write call.
            with self.env.cr.savepoint():
                result = super().set_values()
                self.company_id.write({
                    'receipt_followup_enabled': self.receipt_followup_enabled,
                    'receipt_followup_calendar_id': self.receipt_followup_calendar_id.id,
                    'receipt_followup_grace_hours': self.receipt_followup_grace_hours,
                })
            _logger.debug('[OVERDUE_RECEIPT][SETTINGS_SAVE][END] company_id=%s enabled=%s calendar_id=%s grace_hours=%s',
                          self.company_id.id, self.receipt_followup_enabled,
                          self.receipt_followup_calendar_id.id, self.receipt_followup_grace_hours)
            return result
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][SETTINGS_SAVE][ERROR] company_id=%s user_id=%s',
                              self.company_id.id, self.env.uid)
            raise
