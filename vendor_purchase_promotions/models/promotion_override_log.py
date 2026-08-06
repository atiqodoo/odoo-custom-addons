import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


_logger = logging.getLogger(__name__)

SYSTEM_CONTEXT_KEY = 'vendor_promotion_checker_system_operation'
REVIEW_FIELDS = {'review_state', 'review_notes'}


class VendorPromotionOverrideLog(models.Model):
    _name = 'vendor.promotion.override.log'
    _description = 'Vendor Promotion Checker Override'
    _order = 'id desc'

    name = fields.Char(required=True, default='New', readonly=True, copy=False, index=True)
    purchase_id = fields.Many2one(
        'purchase.order', required=True, readonly=True, index=True, ondelete='cascade'
    )
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', required=True, readonly=True, index=True)
    user_id = fields.Many2one('res.users', required=True, readonly=True, index=True)
    fingerprint = fields.Char(required=True, readonly=True, index=True, copy=False)
    warning_shown_count = fields.Integer(default=0, readonly=True, copy=False)
    dismissal_count = fields.Integer(default=0, readonly=True, copy=False)
    first_dismissed_at = fields.Datetime(readonly=True, copy=False)
    second_dismissed_at = fields.Datetime(readonly=True, copy=False)
    override_available = fields.Boolean(default=False, readonly=True, copy=False)
    override_used = fields.Boolean(default=False, readonly=True, copy=False, index=True)
    override_confirmed_at = fields.Datetime(readonly=True, copy=False)
    line_ids = fields.One2many(
        'vendor.promotion.override.log.line', 'log_id', string='Promotion Opportunities', readonly=True
    )
    event_ids = fields.One2many(
        'vendor.promotion.override.event', 'log_id', string='Audit Events', readonly=True
    )
    review_state = fields.Selection(
        [
            ('pending', 'Pending Review'),
            ('reviewed', 'Reviewed'),
            ('action_required', 'Action Required'),
        ],
        required=True,
        default='pending',
        index=True,
    )
    review_notes = fields.Text()
    reviewed_by = fields.Many2one('res.users', readonly=True, copy=False)
    reviewed_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get(SYSTEM_CONTEXT_KEY):
            raise AccessError(_('Promotion override logs can only be created by the checker.'))
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'vendor.promotion.override.log'
                ) or 'New'
        records = super().create(vals_list)
        _logger.info(
            '[VPP_CHECKER_AUDIT] log_created ids=%s purchase_ids=%s user_ids=%s',
            records.ids,
            records.mapped('purchase_id').ids,
            records.mapped('user_id').ids,
        )
        return records

    def write(self, vals):
        if self.env.context.get(SYSTEM_CONTEXT_KEY):
            return super().write(vals)
        if not self.env.user.has_group('purchase.group_purchase_manager'):
            raise AccessError(_('Only Purchase Managers can review promotion overrides.'))
        unexpected = set(vals) - REVIEW_FIELDS
        if unexpected:
            raise AccessError(_('Core promotion override audit details cannot be modified.'))
        vals = dict(vals)
        vals.update({
            'reviewed_by': self.env.user.id,
            'reviewed_at': fields.Datetime.now(),
        })
        _logger.info(
            '[VPP_CHECKER_REVIEW] log_ids=%s reviewer_id=%s state=%s',
            self.ids,
            self.env.user.id,
            vals.get('review_state'),
        )
        return super(VendorPromotionOverrideLog, self.with_context(
            **{SYSTEM_CONTEXT_KEY: True}
        )).write(vals)

    def unlink(self):
        raise AccessError(_('Promotion override audit logs cannot be deleted.'))

    def _create_event(self, event_type, details=None):
        self.ensure_one()
        return self.env['vendor.promotion.override.event'].sudo().with_context(
            **{SYSTEM_CONTEXT_KEY: True}
        ).create({
            'log_id': self.id,
            'event_type': event_type,
            'user_id': self.env.user.id,
            'details': details or {},
        })

    def _dismissal_limit(self):
        self.ensure_one()
        limits = self.line_ids.mapped('promotion_id').mapped(
            lambda rule: rule.effective_profile().dismissal_limit
            if rule.effective_profile() and rule.effective_profile().recommendation_enabled
            else 3
        )
        return max(limits or [3])

    def action_register_dismissal(self, fingerprint):
        """Called by the notification X button; two valid dismissals arm override."""
        self.ensure_one()
        log = self
        if log.user_id != self.env.user:
            _logger.warning(
                '[VPP_CHECKER_SECURITY] dismissal_user_mismatch log_id=%s owner_id=%s caller_id=%s',
                log.id,
                log.user_id.id,
                self.env.user.id,
            )
            raise AccessError(_('You can only dismiss your own promotion warning.'))
        if log.fingerprint != fingerprint:
            _logger.warning(
                '[VPP_CHECKER_SECURITY] dismissal_fingerprint_mismatch log_id=%s caller_id=%s',
                log.id,
                self.env.user.id,
            )
            raise UserError(_('This promotion warning is no longer current. Confirm the RFQ again.'))
        if log.purchase_id.state not in ('draft', 'sent'):
            return {
                'dismissal_count': log.dismissal_count,
                'dismissal_limit': log._dismissal_limit(),
                'override_available': log.override_available,
                'ignored': True,
            }
        dismissal_limit = log._dismissal_limit()
        if log.override_used or log.dismissal_count >= dismissal_limit:
            return {
                'dismissal_count': log.dismissal_count,
                'dismissal_limit': dismissal_limit,
                'override_available': log.override_available,
                'ignored': True,
            }

        dismissed_at = fields.Datetime.now()
        dismissal_count = log.dismissal_count + 1
        values = {
            'dismissal_count': dismissal_count,
            'override_available': dismissal_count >= dismissal_limit,
        }
        if dismissal_count == 1:
            values['first_dismissed_at'] = dismissed_at
        elif dismissal_count == 2:
            values['second_dismissed_at'] = dismissed_at
        log.sudo().with_context(**{SYSTEM_CONTEXT_KEY: True}).write(values)
        log._create_event('dismissed', {
            'dismissal_count': dismissal_count,
            'dismissal_limit': dismissal_limit,
            'override_available': dismissal_count >= dismissal_limit,
        })
        _logger.warning(
            '[VPP_CHECKER_DISMISS] log_id=%s po_id=%s user_id=%s count=%s limit=%s override_available=%s',
            log.id,
            log.purchase_id.id,
            self.env.user.id,
            dismissal_count,
            dismissal_limit,
            dismissal_count >= dismissal_limit,
        )
        return {
            'dismissal_count': dismissal_count,
            'dismissal_limit': dismissal_limit,
            'override_available': dismissal_count >= dismissal_limit,
            'ignored': False,
        }


class VendorPromotionOverrideLogLine(models.Model):
    _name = 'vendor.promotion.override.log.line'
    _description = 'Vendor Promotion Override Detail'
    _order = 'id'

    log_id = fields.Many2one(
        'vendor.promotion.override.log', required=True, readonly=True, index=True, ondelete='cascade'
    )
    order_line_id = fields.Many2one('purchase.order.line', readonly=True, ondelete='set null')
    product_id = fields.Many2one('product.product', required=True, readonly=True)
    promotion_id = fields.Many2one('vendor.purchase.promotion', required=True, readonly=True)
    product_uom_id = fields.Many2one('uom.uom', required=True, readonly=True)
    charged_qty = fields.Float(required=True, readonly=True)
    buy_qty = fields.Float(required=True, readonly=True)
    free_qty = fields.Float(required=True, readonly=True)
    repeat_offer = fields.Boolean(readonly=True)
    current_foc_qty = fields.Float(readonly=True)
    quantity_to_add = fields.Float(required=True, readonly=True)
    recommended_qty = fields.Float(required=True, readonly=True)
    recommended_foc_qty = fields.Float(required=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get(SYSTEM_CONTEXT_KEY):
            raise AccessError(_('Promotion override details can only be created by the checker.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Promotion override details cannot be modified.'))

    def unlink(self):
        raise AccessError(_('Promotion override details cannot be deleted.'))


class VendorPromotionOverrideEvent(models.Model):
    _name = 'vendor.promotion.override.event'
    _description = 'Vendor Promotion Override Audit Event'
    _order = 'id desc'

    log_id = fields.Many2one(
        'vendor.promotion.override.log', required=True, readonly=True, index=True, ondelete='cascade'
    )
    event_type = fields.Selection(
        [
            ('warning_shown', 'Warning Shown'),
            ('dismissed', 'Warning Dismissed'),
            ('override_confirmed', 'Override Confirmed'),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one('res.users', required=True, readonly=True)
    event_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    details = fields.Json(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get(SYSTEM_CONTEXT_KEY):
            raise AccessError(_('Promotion override events can only be created by the checker.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Promotion override events cannot be modified.'))

    def unlink(self):
        raise AccessError(_('Promotion override events cannot be deleted.'))
