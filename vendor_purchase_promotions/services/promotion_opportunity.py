import math

from odoo.tools.float_utils import float_compare, float_is_zero


def calculate_next_promotion_tier(
    charged_qty,
    buy_qty,
    free_qty,
    min_charged_qty=0.0,
    max_charged_qty=0.0,
    repeat_offer=True,
    precision_rounding=0.01,
):
    """Return the next useful promotion tier, or ``None`` when already aligned."""
    charged_qty = float(charged_qty or 0.0)
    buy_qty = float(buy_qty or 0.0)
    free_qty = float(free_qty or 0.0)
    min_charged_qty = float(min_charged_qty or 0.0)
    max_charged_qty = float(max_charged_qty or 0.0)
    # The existing FOC engine uses mathematical tiers, so keep comparisons
    # strict even when the purchase UoM itself rounds to whole units.
    precision_rounding = min(float(precision_rounding or 0.01), 0.000001)

    if charged_qty <= 0 or buy_qty <= 0 or free_qty <= 0:
        return None
    if max_charged_qty and float_compare(
        charged_qty, max_charged_qty, precision_rounding=precision_rounding
    ) > 0:
        return None

    within_range = float_compare(
        charged_qty, min_charged_qty, precision_rounding=precision_rounding
    ) >= 0 and (
        not max_charged_qty
        or float_compare(
            charged_qty, max_charged_qty, precision_rounding=precision_rounding
        ) <= 0
    )

    if repeat_offer:
        current_foc_qty = (
            math.floor(charged_qty / buy_qty) * free_qty
            if within_range
            else 0.0
        )
        base_qty = max(charged_qty, min_charged_qty)
        complete_tiers = math.floor(base_qty / buy_qty)
        lower_threshold = complete_tiers * buy_qty
        if float_is_zero(
            base_qty - lower_threshold, precision_rounding=precision_rounding
        ):
            recommended_qty = lower_threshold
        else:
            recommended_qty = (complete_tiers + 1) * buy_qty
        recommended_foc_qty = math.floor(recommended_qty / buy_qty) * free_qty
    else:
        current_foc_qty = free_qty if within_range and float_compare(
            charged_qty, buy_qty, precision_rounding=precision_rounding
        ) >= 0 else 0.0
        recommended_qty = max(buy_qty, min_charged_qty)
        recommended_foc_qty = free_qty

    if max_charged_qty and float_compare(
        recommended_qty, max_charged_qty, precision_rounding=precision_rounding
    ) > 0:
        return None
    if float_compare(
        recommended_qty, charged_qty, precision_rounding=precision_rounding
    ) <= 0:
        return None
    if float_compare(
        recommended_foc_qty, current_foc_qty, precision_rounding=precision_rounding
    ) <= 0:
        return None

    return {
        'current_foc_qty': current_foc_qty,
        'recommended_qty': recommended_qty,
        'quantity_to_add': recommended_qty - charged_qty,
        'recommended_foc_qty': recommended_foc_qty,
    }
