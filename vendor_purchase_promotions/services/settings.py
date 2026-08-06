PROMOTION_SPLIT_GROUPS_BY_UOM_PARAM = 'vendor_purchase_promotions.split_groups_by_uom'
PROMOTION_SPLIT_GROUPS_BY_CATEGORY_PARAM = 'vendor_purchase_promotions.split_groups_by_category'


def config_bool(env, key, default=True):
    value = env['ir.config_parameter'].sudo().get_param(key)
    if value is False:
        return default
    return str(value).lower() not in ('false', '0', 'no', 'off')


def split_promotion_groups_by_uom(env):
    return config_bool(env, PROMOTION_SPLIT_GROUPS_BY_UOM_PARAM, default=True)


def split_promotion_groups_by_category(env):
    return config_bool(env, PROMOTION_SPLIT_GROUPS_BY_CATEGORY_PARAM, default=True)
