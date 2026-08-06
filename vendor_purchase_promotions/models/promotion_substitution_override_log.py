import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .promotion_override_log import SYSTEM_CONTEXT_KEY


_logger = logging.getLogger(__name__)

REVIEW_FIELDS = {'review_state', 'review_notes'}
DEFAULT_DISMISSAL_LIMIT = 3


class VendorPromotionSubstitutionOverrideLog(models.Model):
    _name = 'vendor.promotion.substitution.override.log'
    _description = 'Vendor Promotion FOC Substitute Mismatch Override'
    _order = 'id desc'

    name = fields.Char(required=True, default='New', readonly=True, copy=False, index=True)
    picking_id = fields.Many2one(
        'stock.picking', required=True, readonly=True, index=True, ondelete='cascade'
    )
    purchase_id = fields.Many2one('purchase.order', readonly=True, index=True, ondelete='set null')
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', required=True, readonly=True, index=True)
    user_id = fields.Many2one('res.users', required=True, readonly=True, index=True)
    fingerprint = fields.Char(required=True, readonly=True, index=True, copy=False)
    warning_shown_count = fields.Integer(default=0, readonly=True, copy=False)
    dismissal_count = fields.Integer(default=0, readonly=True, copy=False)
    first_dismissed_at = fields.Datetime(readonly=True, copy=False)
    second_dismissed_at = fields.Datetime(readonly=True, copy=False)
    third_dismissed_at = fields.Datetime(readonly=True, copy=False)
    override_available = fields.Boolean(default=False, readonly=True, copy=False)
    override_used = fields.Boolean(default=False, readonly=True, copy=False, index=True)
    override_confirmed_at = fields.Datetime(readonly=True, copy=False)
    line_ids = fields.One2many(
        'vendor.promotion.substitution.override.log.line',
        'log_id',
        string='Mismatch Lines',
        readonly=True,
    )
    event_ids = fields.One2many(
        'vendor.promotion.substitution.override.event',
        'log_id',
        string='Audit Events',
        readonly=True,
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
            raise AccessError(_('Substitution mismatch override logs can only be created by the checker.'))
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'vendor.promotion.substitution.override.log'
                ) or 'New'
        records = super().create(vals_list)
        _logger.info(
            '[VPP_SUBSTITUTE_AUDIT] log_created ids=%s picking_ids=%s purchase_ids=%s user_ids=%s',
            records.ids,
            records.mapped('picking_id').ids,
            records.mapped('purchase_id').ids,
            records.mapped('user_id').ids,
        )
        return records

    def write(self, vals):
        if self.env.context.get(SYSTEM_CONTEXT_KEY):
            return super().write(vals)
        if not self.env.user.has_group('purchase.group_purchase_manager'):
            raise AccessError(_('Only Purchase Managers can review substitution mismatch overrides.'))
        unexpected = set(vals) - REVIEW_FIELDS
        if unexpected:
            raise AccessError(_('Core substitution mismatch audit details cannot be modified.'))
        vals = dict(vals)
        vals.update({
            'reviewed_by': self.env.user.id,
            'reviewed_at': fields.Datetime.now(),
        })
        _logger.info(
            '[VPP_SUBSTITUTE_REVIEW] log_ids=%s reviewer_id=%s state=%s',
            self.ids,
            self.env.user.id,
            vals.get('review_state'),
        )
        return super(VendorPromotionSubstitutionOverrideLog, self.with_context(
            **{SYSTEM_CONTEXT_KEY: True}
        )).write(vals)

    def unlink(self):
        raise AccessError(_('Substitution mismatch audit logs cannot be deleted.'))

    def _dismissal_limit(self):
        return DEFAULT_DISMISSAL_LIMIT

    def _create_event(self, event_type, details=None):
        self.ensure_one()
        return self.env['vendor.promotion.substitution.override.event'].sudo().with_context(
            **{SYSTEM_CONTEXT_KEY: True}
        ).create({
            'log_id': self.id,
            'event_type': event_type,
            'user_id': self.env.user.id,
            'details': details or {},
        })

    def action_register_dismissal(self, fingerprint):
        self.ensure_one()
        if self.user_id != self.env.user:
            _logger.warning(
                '[VPP_SUBSTITUTE_SECURITY] dismissal_user_mismatch log_id=%s owner_id=%s caller_id=%s',
                self.id,
                self.user_id.id,
                self.env.user.id,
            )
            raise AccessError(_('You can only dismiss your own substitution warning.'))
        if self.fingerprint != fingerprint:
            _logger.warning(
                '[VPP_SUBSTITUTE_SECURITY] dismissal_fingerprint_mismatch log_id=%s caller_id=%s',
                self.id,
                self.env.user.id,
            )
            raise UserError(_('This substitution warning is no longer current. Apply the substitute again.'))
        if self.picking_id.state in ('done', 'cancel'):
            return {
                'dismissal_count': self.dismissal_count,
                'dismissal_limit': self._dismissal_limit(),
                'override_available': self.override_available,
                'ignored': True,
            }
        dismissal_limit = self._dismissal_limit()
        if self.override_used or self.dismissal_count >= dismissal_limit:
            return {
                'dismissal_count': self.dismissal_count,
                'dismissal_limit': dismissal_limit,
                'override_available': self.override_available,
                'ignored': True,
            }

        dismissed_at = fields.Datetime.now()
        dismissal_count = self.dismissal_count + 1
        values = {
            'dismissal_count': dismissal_count,
            'override_available': dismissal_count >= dismissal_limit,
        }
        if dismissal_count == 1:
            values['first_dismissed_at'] = dismissed_at
        elif dismissal_count == 2:
            values['second_dismissed_at'] = dismissed_at
        elif dismissal_count == 3:
            values['third_dismissed_at'] = dismissed_at
        self.sudo().with_context(**{SYSTEM_CONTEXT_KEY: True}).write(values)
        self._create_event('dismissed', {
            'dismissal_count': dismissal_count,
            'dismissal_limit': dismissal_limit,
            'override_available': dismissal_count >= dismissal_limit,
        })
        _logger.warning(
            '[VPP_SUBSTITUTE_DISMISS] log_id=%s picking_id=%s user_id=%s count=%s limit=%s override_available=%s',
            self.id,
            self.picking_id.id,
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


class VendorPromotionSubstitutionOverrideLogLine(models.Model):
    _name = 'vendor.promotion.substitution.override.log.line'
    _description = 'Vendor Promotion FOC Substitute Mismatch Detail'
    _order = 'id'

    log_id = fields.Many2one(
        'vendor.promotion.substitution.override.log',
        required=True,
        readonly=True,
        index=True,
        ondelete='cascade',
    )
    application_id = fields.Many2one('vendor.purchase.promotion.application', readonly=True)
    foc_line_id = fields.Many2one('purchase.order.line', required=True, readonly=True)
    source_move_id = fields.Many2one('stock.move', required=True, readonly=True)
    expected_product_id = fields.Many2one('product.product', required=True, readonly=True)
    substitute_product_id = fields.Many2one('product.product', required=True, readonly=True)
    substitute_uom_id = fields.Many2one('uom.uom', required=True, readonly=True)
    substitute_category_id = fields.Many2one('product.category', required=True, readonly=True)
    substitute_qty = fields.Float(required=True, readonly=True)
    charged_line_ids = fields.Many2many(
        'purchase.order.line',
        'vendor_promotion_substitution_override_charged_line_rel',
        'line_id',
        'order_line_id',
        string='Qualifying Charged Lines',
        readonly=True,
    )
    charged_uom_ids = fields.Many2many(
        'uom.uom',
        'vendor_promotion_substitution_override_uom_rel',
        'line_id',
        'uom_id',
        string='Qualifying UoMs',
        readonly=True,
    )
    charged_category_ids = fields.Many2many(
        'product.category',
        'vendor_promotion_substitution_override_category_rel',
        'line_id',
        'category_id',
        string='Qualifying Categories',
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get(SYSTEM_CONTEXT_KEY):
            raise AccessError(_('Substitution mismatch details can only be created by the checker.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Substitution mismatch details cannot be modified.'))

    def unlink(self):
        raise AccessError(_('Substitution mismatch details cannot be deleted.'))


class VendorPromotionSubstitutionOverrideEvent(models.Model):
    _name = 'vendor.promotion.substitution.override.event'
    _description = 'Vendor Promotion FOC Substitute Mismatch Audit Event'
    _order = 'id desc'

    log_id = fields.Many2one(
        'vendor.promotion.substitution.override.log',
        required=True,
        readonly=True,
        index=True,
        ondelete='cascade',
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
            raise AccessError(_('Substitution mismatch events can only be created by the checker.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Substitution mismatch events cannot be modified.'))

    def unlink(self):
        raise AccessError(_('Substitution mismatch events cannot be deleted.'))
