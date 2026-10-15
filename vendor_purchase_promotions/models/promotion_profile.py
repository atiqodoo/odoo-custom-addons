import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class VendorPromotionProfile(models.Model):
    _name = 'vendor.promotion.profile'
    _description = 'Vendor Promotion Profile'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    qualification_mode = fields.Selection(
        [
            ('per_line', 'Per Order Line'),
            ('across_eligible_variants', 'Across Eligible Variants'),
        ],
        required=True,
        default='per_line',
    )
    tier_method = fields.Selection(
        [
            ('highest_slab', 'Highest Qualified Slab'),
            ('cumulative', 'Cumulative Slabs'),
        ],
        required=True,
        default='highest_slab',
    )
    substitution_policy = fields.Selection(
        [
            ('none', 'No Substitution'),
            ('requested_variants', 'Requested Variants Only'),
            ('eligible_variants', 'Any Eligible Promotion Variant'),
        ],
        required=True,
        default='none',
    )
    foc_selection_policy = fields.Selection(
        [
            ('first_line', 'First Qualifying Line'),
            ('largest_line', 'Largest Qualifying Line'),
        ],
        required=True,
        default='first_line',
    )
    recommendation_enabled = fields.Boolean(default=True)
    dismissal_limit = fields.Integer(default=3)
    notes = fields.Text()

    _sql_constraints = [
        (
            'vendor_promotion_profile_code_unique',
            'UNIQUE(code)',
            'Promotion profile code must be unique.',
        ),
        (
            'vendor_promotion_profile_dismissal_limit_nonnegative',
            'CHECK(dismissal_limit >= 0)',
            'Dismissal limit cannot be negative.',
        ),
    ]

    @api.constrains('code')
    def _check_code(self):
        for profile in self:
            if profile.code and not profile.code.replace('_', '').replace('-', '').isalnum():
                raise ValidationError(_('Promotion profile code may only contain letters, numbers, dashes, and underscores.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        _logger.info(
            '[VPP_PROFILE] created profile_ids=%s codes=%s qualification_modes=%s tier_methods=%s',
            records.ids,
            records.mapped('code'),
            records.mapped('qualification_mode'),
            records.mapped('tier_method'),
        )
        return records

    def write(self, vals):
        result = super().write(vals)
        _logger.info(
            '[VPP_PROFILE] updated profile_ids=%s vals_keys=%s user_id=%s',
            self.ids,
            sorted(vals),
            self.env.user.id,
        )
        return result
