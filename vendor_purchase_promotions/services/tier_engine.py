import logging
import math

from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


def calculate_rule_foc_qty(rule, charged_qty, precision_rounding=0.01):
    """Calculate FOC quantity for one promotion rule without touching records."""
    charged_qty = float(charged_qty or 0.0)
    precision_rounding = float(precision_rounding or 0.01)
    if float_compare(charged_qty, rule.min_charged_qty, precision_rounding=precision_rounding) < 0:
        return 0.0
    if rule.max_charged_qty and float_compare(
        charged_qty, rule.max_charged_qty, precision_rounding=precision_rounding
    ) > 0:
        return 0.0
    if rule.repeat_offer:
        return math.floor(charged_qty / rule.buy_qty) * rule.free_qty
    return rule.free_qty if float_compare(
        charged_qty, rule.buy_qty, precision_rounding=precision_rounding
    ) >= 0 else 0.0


def select_best_tier(rules, charged_qty, tier_method='highest_slab', precision_rounding=0.01):
    """Return the winning rule and FOC qty for a slab/tier group."""
    precision_rounding = float(precision_rounding or 0.01)
    qualified = []
    for rule in rules:
        foc_qty = calculate_rule_foc_qty(rule, charged_qty, precision_rounding)
        if float_compare(foc_qty, 0.0, precision_rounding=precision_rounding) > 0:
            qualified.append((rule, foc_qty))

    if not qualified:
        _logger.info(
            '[VPP_TIER_ENGINE] no_qualified_tier qty=%s rule_ids=%s method=%s',
            charged_qty,
            rules.ids,
            tier_method,
        )
        return rules.browse(), 0.0

    if tier_method == 'cumulative':
        rule = qualified[-1][0]
        foc_qty = sum(item[1] for item in qualified)
    else:
        rule, foc_qty = max(
            qualified,
            key=lambda item: (
                item[0].buy_qty,
                item[1],
                item[0].priority,
                item[0].id,
            ),
        )

    _logger.info(
        '[VPP_TIER_ENGINE] selected_tier qty=%s method=%s selected_rule_id=%s foc_qty=%s '
        'qualified_rule_ids=%s all_rule_ids=%s',
        charged_qty,
        tier_method,
        rule.id,
        foc_qty,
        [item[0].id for item in qualified],
        rules.ids,
    )
    return rule, foc_qty


def find_next_better_tier(rules, charged_qty, current_foc_qty, precision_rounding=0.01):
    """Return the next higher tier the user can reach, if one exists."""
    precision_rounding = float(precision_rounding or 0.01)
    candidates = rules.filtered(
        lambda rule: float_compare(
            rule.buy_qty, charged_qty, precision_rounding=precision_rounding
        ) > 0
        and float_compare(
            rule.free_qty, current_foc_qty, precision_rounding=precision_rounding
        ) > 0
    ).sorted(lambda rule: (rule.buy_qty, rule.free_qty, -rule.priority, rule.id))
    next_rule = candidates[:1]
    if not next_rule:
        return None
    return {
        'rule': next_rule,
        'recommended_qty': next_rule.buy_qty,
        'quantity_to_add': next_rule.buy_qty - charged_qty,
        'recommended_foc_qty': next_rule.free_qty,
    }
