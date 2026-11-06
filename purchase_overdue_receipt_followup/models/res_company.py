from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    receipt_followup_enabled = fields.Boolean(string='Overdue receipt follow-up')
    receipt_followup_calendar_id = fields.Many2one(
        'resource.calendar', string='Receiving calendar', check_company=True,
        default=lambda self: self.env.ref('purchase_overdue_receipt_followup.receiving_calendar',
                                         raise_if_not_found=False))
    receipt_followup_grace_hours = fields.Float(string='Overdue grace (working hours)', default=0)
    delivery_hours_per_day = fields.Float(string='Hours per lead-time day', default=9,
        help='Converts delivery lead-time days into working hours; each calendar day still contributes its actual open hours.')
    delivery_planning_horizon_days = fields.Integer(string='Delivery planning lookahead (days)', default=366,
        help='Maximum elapsed days to search when planning delivery or a preferred arrival time.')

    @api.constrains('delivery_hours_per_day', 'delivery_planning_horizon_days')
    def _check_delivery_hours_per_day(self):
        if any(company.delivery_hours_per_day <= 0 for company in self):
            raise ValidationError(_('Hours per lead-time day must be positive.'))
        if any(company.delivery_planning_horizon_days < 1 for company in self):
            raise ValidationError(_('Delivery planning lookahead must be positive.'))

    @api.constrains('receipt_followup_grace_hours', 'receipt_followup_enabled', 'receipt_followup_calendar_id')
    def _check_receipt_followup_settings(self):
        for company in self:
            if company.receipt_followup_grace_hours < 0:
                raise ValidationError(_('Overdue grace hours cannot be negative.'))
            if (company.receipt_followup_calendar_id.company_id
                    and company.receipt_followup_calendar_id.company_id != company):
                raise ValidationError(_('The receiving calendar must be shared or belong to this company.'))
            if company.receipt_followup_enabled and (
                not company.receipt_followup_calendar_id
                or not company.receipt_followup_calendar_id.attendance_ids
                or company.receipt_followup_calendar_id.flexible_hours
            ):
                raise ValidationError(_('Choose a receiving calendar with fixed working hours.'))
