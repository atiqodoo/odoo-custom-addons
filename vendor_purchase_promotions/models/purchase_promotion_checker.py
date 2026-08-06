import hashlib
import json
import logging

from markupsafe import Markup

from odoo import fields, models, _
from odoo.tools import html_escape

from ..services.promotion_opportunity import calculate_next_promotion_tier
from ..services.settings import split_promotion_groups_by_category, split_promotion_groups_by_uom
from ..services.tier_engine import find_next_better_tier, select_best_tier
from .promotion_override_log import SYSTEM_CONTEXT_KEY


_logger = logging.getLogger(__name__)


class PurchaseOrderPromotionChecker(models.Model):
    _inherit = 'purchase.order'

    promotion_override_log_ids = fields.One2many(
        'vendor.promotion.override.log',
        'purchase_id',
        string='Promotion Checker Logs',
        readonly=True,
    )
    promotion_override_log_count = fields.Integer(
        compute='_compute_promotion_override_log_count'
    )

    def _compute_promotion_override_log_count(self):
        grouped = self.env['vendor.promotion.override.log']._read_group(
            [('purchase_id', 'in', self.ids)],
            ['purchase_id'],
            ['__count'],
        ) if self.ids else []
        counts = {purchase.id: count for purchase, count in grouped}
        for order in self:
            order.promotion_override_log_count = counts.get(order.id, 0)

    def _promotion_checker_candidate_rules(self, product):
        self.ensure_one()
        if not self.partner_id or not product:
            return self.env['vendor.purchase.promotion']
        today = fields.Date.context_today(self)
        commercial_vendor = self.partner_id.commercial_partner_id
        domain = [
            ('active', '=', True),
            ('company_id', '=', self.company_id.id),
            ('partner_id', 'in', [self.partner_id.id, commercial_vendor.id]),
            '|',
            ('product_tmpl_ids', 'in', [product.product_tmpl_id.id]),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            '|', ('product_id', '=', product.id), ('product_id', '=', False),
            '|', ('date_start', '=', False), ('date_start', '<=', today),
            '|', ('date_end', '=', False), ('date_end', '>=', today),
        ]
        return self.env['vendor.purchase.promotion'].search(
            domain, order=self.env['vendor.purchase.promotion']._order
        )

    def _promotion_checker_line_opportunity(self, line):
        self.ensure_one()
        Promotion = self.env['vendor.purchase.promotion']
        current_rule = Promotion.resolve_rule(
            self, line.product_id, line.product_qty
        )
        rules = current_rule or self._promotion_checker_candidate_rules(line.product_id)
        for rule in rules:
            opportunity = calculate_next_promotion_tier(
                charged_qty=line.product_qty,
                buy_qty=rule.buy_qty,
                free_qty=rule.free_qty,
                min_charged_qty=rule.min_charged_qty,
                max_charged_qty=rule.max_charged_qty,
                repeat_offer=rule.repeat_offer,
                precision_rounding=line.product_uom.rounding or 0.01,
            )
            if opportunity:
                return {
                    'line': line,
                    'rule': rule,
                    **opportunity,
                }
            # When the normal resolver selected a rule, its exact tier is final.
            if current_rule:
                break
        return None

    def _promotion_checker_opportunities(self):
        self.ensure_one()
        opportunities = []
        lines = self.order_line.filtered(
            lambda line: line.product_id
            and not line.display_type
            and not line.is_promotion_foc
            and line.product_qty > 0
        )
        grouped_line_ids = set()
        Promotion = self.env['vendor.purchase.promotion']
        grouped = {}
        split_by_category = split_promotion_groups_by_category(self.env)
        split_by_uom = split_promotion_groups_by_uom(self.env)
        for line in lines:
            candidate_rules = Promotion.resolve_candidate_rules(self, line.product_id)
            if not candidate_rules:
                continue
            seed_rule = candidate_rules[:1]
            if seed_rule.effective_qualification_mode() == 'per_line':
                continue
            base_group_key = seed_rule._promotion_group_key()
            group_key = base_group_key
            if split_by_uom:
                group_key = '%s:uom:%s' % (group_key, line.product_uom.id)
            if split_by_category:
                group_key = '%s:categ:%s' % (group_key, line.product_id.categ_id.id)
            group = grouped.setdefault(group_key, {
                'lines': self.env['purchase.order.line'],
                'rules': self.env['vendor.purchase.promotion'],
                'seed_rule': seed_rule,
            })
            group['lines'] |= line
            group['rules'] |= candidate_rules.filtered(lambda rule: rule._promotion_group_key() == base_group_key)
            grouped_line_ids.add(line.id)

        for group_key, group in grouped.items():
            group_lines = group['lines']
            rules = group['rules'].sorted(lambda rule: (rule.buy_qty, rule.priority, rule.id))
            total_qty = sum(group_lines.mapped('product_qty'))
            precision = min(group_lines.mapped('product_uom.rounding') or [0.01])
            selected_rule, foc_qty = select_best_tier(
                rules,
                total_qty,
                tier_method=group['seed_rule'].effective_tier_method(),
                precision_rounding=precision,
            )
            next_tier = find_next_better_tier(rules, total_qty, foc_qty, precision_rounding=precision)
            if next_tier:
                carrier_line = group_lines.sorted(lambda item: (item.sequence, item.id))[:1]
                opportunities.append({
                    'line': carrier_line,
                    'lines': group_lines,
                    'rule': selected_rule or next_tier['rule'],
                    'recommended_rule': next_tier['rule'],
                    'current_foc_qty': foc_qty,
                    'charged_qty': total_qty,
                    'quantity_to_add': next_tier['quantity_to_add'],
                    'recommended_qty': next_tier['recommended_qty'],
                    'recommended_foc_qty': next_tier['recommended_foc_qty'],
                    'group_key': group_key,
                })
                _logger.info(
                    '[VPP_CHECKER_GROUP_OPPORTUNITY] po_id=%s group_key=%s line_ids=%s '
                    'uom_ids=%s category_ids=%s split_by_uom=%s split_by_category=%s charged_qty=%s '
                    'current_rule_id=%s current_foc=%s next_rule_id=%s add_qty=%s',
                    self.id,
                    group_key,
                    group_lines.ids,
                    group_lines.mapped('product_uom').ids,
                    group_lines.mapped('product_id.categ_id').ids,
                    split_by_uom,
                    split_by_category,
                    total_qty,
                    selected_rule.id if selected_rule else False,
                    foc_qty,
                    next_tier['rule'].id,
                    next_tier['quantity_to_add'],
                )

        for line in lines.filtered(lambda item: item.id not in grouped_line_ids):
            opportunity = self._promotion_checker_line_opportunity(line)
            if opportunity:
                opportunity['lines'] = line
                opportunity['recommended_rule'] = opportunity['rule']
                opportunity['charged_qty'] = line.product_qty
                opportunities.append(opportunity)
        _logger.info(
            '[VPP_CHECKER_SCAN] po_id=%s po_name=%s user_id=%s charged_line_count=%s '
            'opportunity_count=%s line_ids=%s',
            self.id,
            self.name,
            self.env.user.id,
            len(lines),
            len(opportunities),
            [item['line'].id for item in opportunities],
        )
        return opportunities

    def _promotion_checker_fingerprint(self, opportunities):
        self.ensure_one()
        payload = {
            'purchase_id': self.id,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'lines': [
                {
                    'line_id': item['line'].id,
                    'product_id': item['line'].product_id.id,
                    'product_category_id': item['line'].product_id.categ_id.id,
                    'product_uom_id': item['line'].product_uom.id,
                    'charged_qty': item.get('charged_qty', item['line'].product_qty),
                    'promotion_id': item['rule'].id,
                    'recommended_promotion_id': item.get('recommended_rule', item['rule']).id,
                    'qualifying_line_ids': item.get('lines', item['line']).ids,
                    'promotion_write_date': str(item['rule'].write_date or ''),
                    'recommended_qty': item['recommended_qty'],
                    'recommended_foc_qty': item['recommended_foc_qty'],
                }
                for item in opportunities
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _promotion_checker_log_line_commands(self, opportunities):
        return [(0, 0, {
            'order_line_id': item['line'].id,
            'product_id': item['line'].product_id.id,
            'promotion_id': item['rule'].id,
            'product_uom_id': item['line'].product_uom.id,
            'charged_qty': item.get('charged_qty', item['line'].product_qty),
            'buy_qty': item['rule'].buy_qty,
            'free_qty': item['rule'].free_qty,
            'repeat_offer': item['rule'].repeat_offer,
            'current_foc_qty': item['current_foc_qty'],
            'quantity_to_add': item['quantity_to_add'],
            'recommended_qty': item['recommended_qty'],
            'recommended_foc_qty': item['recommended_foc_qty'],
        }) for item in opportunities]

    def _promotion_checker_get_log(self, opportunities, fingerprint):
        self.ensure_one()
        Log = self.env['vendor.promotion.override.log']
        log = Log.search([
            ('purchase_id', '=', self.id),
            ('user_id', '=', self.env.user.id),
            ('fingerprint', '=', fingerprint),
            ('override_used', '=', False),
        ], order='id desc', limit=1)
        if not log:
            created_log = Log.sudo().with_context(**{SYSTEM_CONTEXT_KEY: True}).create({
                'purchase_id': self.id,
                'company_id': self.company_id.id,
                'partner_id': self.partner_id.commercial_partner_id.id,
                'user_id': self.env.user.id,
                'fingerprint': fingerprint,
                'line_ids': self._promotion_checker_log_line_commands(opportunities),
            })
            log = Log.browse(created_log.id)
        return log

    @staticmethod
    def _promotion_checker_format_qty(quantity):
        return f'{quantity:.4f}'.rstrip('0').rstrip('.')

    def _promotion_checker_message(self, opportunities, dismissal_count):
        self.ensure_one()
        lines = [
            _('Promotion opportunity found. LPO confirmation has been paused.'),
            '',
        ]
        for item in opportunities:
            qty = self._promotion_checker_format_qty
            charged_qty = item.get('charged_qty', item['line'].product_qty)
            qualifying_lines = item.get('lines', item['line'])
            product_label = item['line'].product_id.display_name
            if len(qualifying_lines) > 1:
                product_label = _('%(count)s eligible lines', count=len(qualifying_lines))
            lines.extend([
                _('%(product)s — %(promotion)s',
                  product=product_label,
                  promotion=item['rule'].name),
                _('Quoted: %(quoted)s | Current FOC: %(current)s',
                  quoted=qty(charged_qty),
                  current=qty(item['current_foc_qty'])),
                _('Add %(add)s to reach %(recommended)s and receive %(foc)s total FOC.',
                  add=qty(item['quantity_to_add']),
                  recommended=qty(item['recommended_qty']),
                  foc=qty(item['recommended_foc_qty'])),
                '',
            ])
        dismissal_limit = max(
            [
                item['rule'].effective_profile().dismissal_limit
                if item['rule'].effective_profile()
                and item['rule'].effective_profile().recommendation_enabled
                else 3
                for item in opportunities
            ] or [3]
        )
        remaining = max(dismissal_limit - dismissal_count, 0)
        lines.append(
            _('Close this banner %(remaining)s more time(s) to enable an audited override.',
              remaining=remaining)
        )
        return '\n'.join(lines)

    def _promotion_checker_warning_action(self, log, opportunities, fingerprint):
        self.ensure_one()
        shown_count = log.warning_shown_count + 1
        log.sudo().with_context(**{SYSTEM_CONTEXT_KEY: True}).write({
            'warning_shown_count': shown_count,
        })
        log._create_event('warning_shown', {
            'warning_shown_count': shown_count,
            'dismissal_count': log.dismissal_count,
        })
        message = self._promotion_checker_message(opportunities, log.dismissal_count)
        _logger.warning(
            '[VPP_CHECKER_BLOCK] po_id=%s log_id=%s user_id=%s shown_count=%s '
            'dismissal_count=%s fingerprint=%s',
            self.id,
            log.id,
            self.env.user.id,
            shown_count,
            log.dismissal_count,
            fingerprint,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'vendor_purchase_promotions.promotion_warning',
            'params': {
                'title': _('Promotion Available — Confirmation Paused'),
                'message': message,
                'log_id': log.id,
                'fingerprint': fingerprint,
                'dismissal_count': log.dismissal_count,
            },
        }

    def _promotion_checker_mark_override_confirmed(self, log):
        self.ensure_one()
        confirmed_at = fields.Datetime.now()
        log.sudo().with_context(**{SYSTEM_CONTEXT_KEY: True}).write({
            'override_used': True,
            'override_confirmed_at': confirmed_at,
        })
        log._create_event('override_confirmed', {
            'dismissal_count': log.dismissal_count,
            'order_state': self.state,
        })
        detail_rows = ''.join(
            '<li>%s: quoted %s; recommended %s; current FOC %s; potential FOC %s</li>' % (
                html_escape(line.product_id.display_name),
                self._promotion_checker_format_qty(line.charged_qty),
                self._promotion_checker_format_qty(line.recommended_qty),
                self._promotion_checker_format_qty(line.current_foc_qty),
                self._promotion_checker_format_qty(line.recommended_foc_qty),
            )
            for line in log.line_ids
        )
        self.message_post(body=Markup(
            '<b>%s</b><br/>%s<ul>%s</ul>' % (
                html_escape(_('Promotion checker override used')),
                html_escape(_('The user dismissed the promotion warning twice and confirmed without changing the quantities.')),
                detail_rows,
            )
        ))
        _logger.warning(
            '[VPP_CHECKER_OVERRIDE] po_id=%s po_name=%s log_id=%s user_id=%s '
            'dismissal_count=%s state=%s',
            self.id,
            self.name,
            log.id,
            self.env.user.id,
            log.dismissal_count,
            self.state,
        )

    def button_confirm(self):
        pending_overrides = {}
        for order in self.filtered(lambda record: record.state in ('draft', 'sent')):
            opportunities = order._promotion_checker_opportunities()
            if not opportunities:
                continue
            fingerprint = order._promotion_checker_fingerprint(opportunities)
            log = order._promotion_checker_get_log(opportunities, fingerprint)
            dismissal_limit = log._dismissal_limit()
            if not log.override_available or log.dismissal_count < dismissal_limit:
                return order._promotion_checker_warning_action(
                    log, opportunities, fingerprint
                )
            pending_overrides[order.id] = log
            _logger.info(
                '[VPP_CHECKER_READY] po_id=%s log_id=%s user_id=%s dismissal_count=%s',
                order.id,
                log.id,
                self.env.user.id,
                log.dismissal_count,
            )

        result = super().button_confirm()
        for order in self:
            log = pending_overrides.get(order.id)
            if log and order.state not in ('draft', 'sent'):
                order._promotion_checker_mark_override_confirmed(log)
        return result

    def action_view_promotion_override_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Promotion Checker Logs'),
            'res_model': 'vendor.promotion.override.log',
            'view_mode': 'list,form',
            'domain': [('purchase_id', '=', self.id)],
            'context': {'create': False, 'delete': False},
        }
