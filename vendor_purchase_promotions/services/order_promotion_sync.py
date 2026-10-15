import logging

from odoo import _

from .settings import split_promotion_groups_by_category, split_promotion_groups_by_uom
from .tier_engine import find_next_better_tier, select_best_tier


_logger = logging.getLogger(__name__)


class OrderPromotionSync:
    """Build grouped promotion decisions for draft purchase orders."""

    def __init__(self, env):
        self.env = env

    def sync_order(self, order):
        Promotion = self.env['vendor.purchase.promotion']
        charged_lines = order.order_line.filtered(
            lambda line: line.product_id and not line.display_type and not line.is_promotion_foc
        )
        foc_lines = order.order_line.filtered('is_promotion_foc')
        if foc_lines:
            _logger.info(
                '[VPP_SYNC] remove_existing_foc po_id=%s foc_line_ids=%s',
                order.id,
                foc_lines.ids,
            )
            foc_lines.unlink()

        charged_lines.with_context(skip_rfq_bill_price=True).write({
            'promotion_id': False,
            'promotion_foc_qty': 0.0,
        })

        groups = self._build_groups(order, charged_lines, Promotion)
        for group in groups:
            self._apply_group(order, group)

        _logger.info(
            '[VPP_SYNC] completed po_id=%s charged_line_count=%s group_count=%s',
            order.id,
            len(charged_lines),
            len(groups),
        )

    def _build_groups(self, order, charged_lines, Promotion):
        groups = {}
        split_by_category = split_promotion_groups_by_category(self.env)
        split_by_uom = split_promotion_groups_by_uom(self.env)
        for line in charged_lines:
            candidate_rules = Promotion.resolve_candidate_rules(order, line.product_id)
            if not candidate_rules:
                _logger.debug(
                    '[VPP_SYNC_MATCH] no_candidate po_id=%s line_id=%s product_id=%s qty=%s',
                    order.id,
                    line.id,
                    line.product_id.id,
                    line.product_qty,
                )
                continue
            rule = candidate_rules[:1]
            base_group_key = rule._promotion_group_key()
            group_key = base_group_key
            if split_by_uom and rule.effective_qualification_mode() != 'per_line':
                group_key = '%s:uom:%s' % (group_key, line.product_uom.id)
            if split_by_category and rule.effective_qualification_mode() != 'per_line':
                group_key = '%s:categ:%s' % (group_key, line.product_id.categ_id.id)
            group = groups.setdefault(group_key, {
                'key': group_key,
                'lines': self.env['purchase.order.line'],
                'rules': candidate_rules.filtered(lambda item: item._promotion_group_key() == base_group_key),
                'seed_rule': rule,
            })
            group['lines'] |= line
            group['rules'] |= candidate_rules.filtered(lambda item: item._promotion_group_key() == base_group_key)
            _logger.debug(
                '[VPP_SYNC_MATCH] matched po_id=%s line_id=%s product_id=%s qty=%s '
                'uom_id=%s category_id=%s split_by_uom=%s split_by_category=%s '
                'seed_rule_id=%s group_key=%s rule_ids=%s',
                order.id,
                line.id,
                line.product_id.id,
                line.product_qty,
                line.product_uom.id,
                line.product_id.categ_id.id,
                split_by_uom,
                split_by_category,
                rule.id,
                group_key,
                group['rules'].ids,
            )
        return list(groups.values())

    def _apply_group(self, order, group):
        lines = group['lines']
        rules = group['rules'].sorted(lambda rule: (rule.buy_qty, rule.priority, rule.id))
        seed_rule = group['seed_rule']
        total_qty = sum(lines.mapped('product_qty'))
        precision = min(lines.mapped('product_uom.rounding') or [0.01])
        tier_method = seed_rule.effective_tier_method()

        if seed_rule.effective_qualification_mode() == 'per_line':
            for line in lines:
                rule = self.env['vendor.purchase.promotion'].resolve_rule(
                    order, line.product_id, line.product_qty
                )
                foc_qty = rule.calculate_foc_qty(line.product_qty) if rule else 0.0
                self._write_line_result(order, line, rule, foc_qty, line, line.product_qty)
            return

        selected_rule, foc_qty = select_best_tier(
            rules,
            total_qty,
            tier_method=tier_method,
            precision_rounding=precision,
        )
        for line in lines:
            line.with_context(skip_rfq_bill_price=True).write({
                'promotion_id': selected_rule.id if selected_rule else False,
                'promotion_foc_qty': 0.0,
            })
        if selected_rule and foc_qty > 0:
            carrier_line = self._select_foc_carrier(lines, selected_rule)
            self._write_line_result(order, carrier_line, selected_rule, foc_qty, lines, total_qty)
        else:
            _logger.info(
                '[VPP_SYNC_GROUP] no_foc po_id=%s group_key=%s line_ids=%s total_qty=%s rule_ids=%s',
                order.id,
                group['key'],
                lines.ids,
                total_qty,
                rules.ids,
            )

        next_tier = find_next_better_tier(rules, total_qty, foc_qty, precision_rounding=precision)
        _logger.info(
            '[VPP_SYNC_GROUP] evaluated po_id=%s group_key=%s line_ids=%s uom_ids=%s category_ids=%s '
            'total_qty=%s selected_rule_id=%s foc_qty=%s next_rule_id=%s qty_to_add=%s',
            order.id,
            group['key'],
            lines.ids,
            lines.mapped('product_uom').ids,
            lines.mapped('product_id.categ_id').ids,
            total_qty,
            selected_rule.id if selected_rule else False,
            foc_qty,
            next_tier['rule'].id if next_tier else False,
            next_tier['quantity_to_add'] if next_tier else 0.0,
        )

    def _select_foc_carrier(self, lines, rule):
        policy = rule.effective_foc_selection_policy()
        if policy == 'largest_line':
            return lines.sorted(lambda line: (-line.product_qty, line.sequence, line.id))[:1]
        return lines.sorted(lambda line: (line.sequence, line.id))[:1]

    def _write_line_result(self, order, line, rule, foc_qty, qualifying_lines, total_qty):
        line.with_context(skip_rfq_bill_price=True).write({
            'promotion_id': rule.id if rule else False,
            'promotion_foc_qty': foc_qty,
        })
        if not rule or foc_qty <= 0:
            return

        name = _('[FOC] %(product)s - %(promotion)s') % {
            'product': line.product_id.display_name,
            'promotion': rule.name,
        }
        if len(qualifying_lines) > 1:
            name = _('[FOC] %(product)s - %(promotion)s (qualified by %(count)s lines)') % {
                'product': line.product_id.display_name,
                'promotion': rule.name,
                'count': len(qualifying_lines),
            }
        foc_line = self.env['purchase.order.line'].with_context(
            skip_rfq_bill_price=True
        ).create({
            'order_id': order.id,
            'product_id': line.product_id.id,
            'name': name,
            'product_qty': foc_qty,
            'product_uom': line.product_uom.id,
            'price_unit': 0.0,
            'discount': 0.0,
            'taxes_id': [(5, 0, 0)],
            'date_planned': line.date_planned,
            'is_promotion_foc': True,
            'promotion_parent_line_id': line.id,
            'promotion_qualifying_line_ids': [(6, 0, qualifying_lines.ids)],
            'promotion_id': rule.id,
            'promotion_foc_qty': 0.0,
            'sequence': line.sequence + 1,
        })
        _logger.info(
            '[VPP_FOC] created po_id=%s promotion_id=%s carrier_line_id=%s qualifying_line_ids=%s '
            'qualified_qty=%s foc_line_id=%s foc_qty=%s product_id=%s selection_policy=%s',
            order.id,
            rule.id,
            line.id,
            qualifying_lines.ids,
            total_qty,
            foc_line.id,
            foc_qty,
            line.product_id.id,
            rule.effective_foc_selection_policy(),
        )
