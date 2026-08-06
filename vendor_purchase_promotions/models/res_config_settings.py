from odoo import fields, models

from ..services.settings import (
    PROMOTION_SPLIT_GROUPS_BY_CATEGORY_PARAM,
    PROMOTION_SPLIT_GROUPS_BY_UOM_PARAM,
)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    vendor_promotion_split_groups_by_uom = fields.Boolean(
        string='Separate Promotion Tiers by UoM',
        config_parameter=PROMOTION_SPLIT_GROUPS_BY_UOM_PARAM,
        default=True,
        help=(
            'When enabled, eligible variants are only combined for tier/slab promotions '
            'when their purchase order lines use the same unit of measure.'
        ),
    )
    vendor_promotion_split_groups_by_category = fields.Boolean(
        string='Separate Promotion Tiers by Product Category',
        config_parameter=PROMOTION_SPLIT_GROUPS_BY_CATEGORY_PARAM,
        default=True,
        help=(
            'When enabled, eligible variants are only combined for tier/slab promotions '
            'when their products use the same product category.'
        ),
    )
