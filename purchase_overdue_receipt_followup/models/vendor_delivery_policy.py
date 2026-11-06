import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class VendorDeliveryPolicy(models.Model):
    _name = 'purchase.vendor.delivery.policy'
    _description = 'Vendor delivery working-time policy'
    _rec_name = 'partner_id'
    _check_company_auto = True

    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    partner_id = fields.Many2one('res.partner', string='Vendor', required=True, check_company=True,
        domain=[('supplier_rank', '>', 0)], index=True)
    days = fields.Integer(string='Lead-time Days', default=0)
    hours = fields.Float(string='Additional Working Hours', default=0)
    calendar_id = fields.Many2one('resource.calendar', string='Receiving Calendar', check_company=True,
        help='Leave empty to use the purchasing company receiving calendar.')
    use_preferred_time = fields.Boolean(string='Preferred Arrival Time')
    preferred_time = fields.Float(string='Arrival Time', help='Local time in the receiving calendar timezone.')

    _sql_constraints = [('vendor_company_unique', 'unique(partner_id, company_id)',
                         'A vendor already has a delivery policy for this company. Edit or reactivate that policy.')]

    @api.constrains('partner_id', 'company_id', 'days', 'hours', 'calendar_id', 'use_preferred_time', 'preferred_time')
    def _check_policy(self):
        for policy in self:
            if policy.partner_id != policy.partner_id.commercial_partner_id:
                raise ValidationError(_('Configure delivery policy on the commercial vendor, not an individual contact.'))
            if policy.days < 0 or policy.hours < 0:
                raise ValidationError(_('Delivery days and hours cannot be negative.'))
            calendar = policy.calendar_id or policy.company_id.receipt_followup_calendar_id
            self.env['purchase.delivery.planning']._validate_calendar(calendar, policy.company_id)
            if policy.use_preferred_time:
                self.env['purchase.delivery.planning']._validate_preferred_time(calendar, policy.preferred_time)

    @api.model_create_multi
    def create(self, values_list):
        _logger.debug('[OVERDUE_RECEIPT][DELIVERY_POLICY_CREATE][START] count=%s user_id=%s', len(values_list), self.env.uid)
        try:
            records = super().create(values_list)
            _logger.debug('[OVERDUE_RECEIPT][DELIVERY_POLICY_CREATE][END] policy_ids=%s', records.ids)
            return records
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][DELIVERY_POLICY_CREATE][ERROR] user_id=%s', self.env.uid)
            raise

    def write(self, values):
        _logger.debug('[OVERDUE_RECEIPT][DELIVERY_POLICY_WRITE][START] policy_ids=%s', self.ids)
        try:
            result = super().write(values)
            _logger.debug('[OVERDUE_RECEIPT][DELIVERY_POLICY_WRITE][END] policy_ids=%s', self.ids)
            return result
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][DELIVERY_POLICY_WRITE][ERROR] policy_ids=%s', self.ids)
            raise

    def unlink(self):
        policy_ids = self.ids
        _logger.debug('[OVERDUE_RECEIPT][DELIVERY_POLICY_DELETE][START] policy_ids=%s', policy_ids)
        try:
            result = super().unlink()
            _logger.debug('[OVERDUE_RECEIPT][DELIVERY_POLICY_DELETE][END] policy_ids=%s', policy_ids)
            return result
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][DELIVERY_POLICY_DELETE][ERROR] policy_ids=%s', policy_ids)
            raise


class ResPartner(models.Model):
    _inherit = 'res.partner'

    delivery_policy_ids = fields.One2many('purchase.vendor.delivery.policy', 'partner_id', string='Delivery Policies')
