# -*- coding: utf-8 -*-
import logging
import json

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosOrderCodLoyalty(models.Model):
    _inherit = 'pos.order'

    lpm_cod_tier_snapshot_json = fields.Text(
        string="COD Tier Snapshot",
        copy=False,
        readonly=True,
        help="Technical JSON snapshot used to freeze COD tier earning per program when configured.",
    )

    @api.model
    def collect_cod_payment(self, *args, **kwargs):
        action = self._lpm_extract_cod_action(args, kwargs)
        result = super().collect_cod_payment(*args, **kwargs)
        if result.get('success') and action == 'payment':
            try:
                order = self._lpm_resolve_cod_order_from_result(result)
                if order:
                    loyalty_result = order._lpm_award_cod_payment_points(result)
                    if loyalty_result:
                        result['loyalty_points'] = loyalty_result
            except Exception as exc:
                _logger.exception(
                    "[loyalty_cod] failed to award COD loyalty points; "
                    "COD payment remains successful. result=%s error=%s",
                    result, exc,
                )
                result['loyalty_error'] = str(exc)
        return result

    @staticmethod
    def _lpm_extract_cod_action(args, kwargs):
        if args and isinstance(args[0], dict):
            return args[0].get('action') or 'payment'
        if len(args) >= 5:
            return args[4] or 'payment'
        if len(args) >= 4 and args[3] in ('payment', 'return'):
            return args[3]
        return kwargs.get('action') or 'payment'

    def _lpm_resolve_cod_order_from_result(self, result):
        order_name = result.get('order_name')
        if order_name:
            order = self.search([('name', '=', order_name)], limit=1)
            if order:
                return order
        if len(self) == 1 and self.exists() and self.is_cod:
            return self
        return self.browse()

    def _lpm_award_cod_payment_points(self, result):
        self.ensure_one()
        if not self.is_cod or not self.partner_id:
            return False
        if result.get('cod_state') == 'returned':
            return False
        if not self.partner_id._lpm_can_earn_points():
            _logger.info(
                "[loyalty_cod] earn blocked by partner policy | order=%s "
                "| partner=%s | partner_id=%s",
                self.name,
                self.partner_id.display_name,
                self.partner_id.id,
            )
            return False

        payment_amount = float(result.get('amount') or 0.0)
        if payment_amount <= 0:
            return False

        programs = self._lpm_cod_loyalty_programs()
        if not programs:
            _logger.debug(
                "[loyalty_cod] no active POS loyalty programs for COD order %s",
                self.name,
            )
            return False

        cumulative_paid = self._lpm_cod_paid_total()
        order_total = float(self.amount_total or 0.0)
        if order_total <= 0:
            return False

        paid_ratio = min(max(cumulative_paid / order_total, 0.0), 1.0)
        updates = []

        for program in programs:
            full_points = self._lpm_cod_points_for_program(program)
            if full_points <= 0:
                continue
            tier_full_points = self._lpm_cod_tier_adjusted_full_points(program, full_points)

            target_issued = round(tier_full_points * paid_ratio, 6)
            already_issued = self._lpm_cod_issued_points(program)
            delta = round(target_issued - already_issued, 6)
            if delta <= 0.0001:
                _logger.debug(
                    "[loyalty_cod] skip program=%s order=%s full=%.4f ratio=%.6f "
                    "tier_full=%.4f target=%.4f already=%.4f",
                    program.display_name, self.name, full_points, paid_ratio,
                    tier_full_points,
                    target_issued, already_issued,
                )
                continue

            card = self._lpm_get_or_create_loyalty_card(program)
            self.env.cr.execute(
                "SELECT points FROM loyalty_card WHERE id = %s FOR UPDATE",
                (card.id,),
            )
            row = self.env.cr.fetchone()
            before = float(row[0] if row else (card.points or 0.0))
            card.sudo().write({'points': before + delta})
            self.env['loyalty.history'].sudo().create({
                'card_id': card.id,
                'order_model': self._name,
                'order_id': self.id,
                'description': 'COD Payment %s' % self.display_name,
                'issued': delta,
                'used': 0.0,
            })
            updates.append({
                'program_id': program.id,
                'program_name': program.display_name,
                'card_id': card.id,
                'issued': delta,
                'points': before + delta,
            })
            _logger.info(
                "[loyalty_cod] awarded COD points | order=%s partner=%s "
                "program=%s payment=%.2f cumulative_paid=%.2f ratio=%.6f "
                "base_full_points=%.4f tier_full_points=%.4f issued_now=%.4f new_balance=%.4f",
                self.name,
                self.partner_id.display_name,
                program.display_name,
                payment_amount,
                cumulative_paid,
                paid_ratio,
                full_points,
                tier_full_points,
                delta,
                before + delta,
            )

        return updates or False

    def _lpm_cod_tier_adjusted_full_points(self, program, full_points):
        self.ensure_one()
        if program.lpm_tier_earning_policy == "none":
            return full_points

        snapshots = self._lpm_cod_tier_snapshots()
        program_key = str(program.id)
        if program.lpm_cod_tier_freeze_policy == "order" and program_key in snapshots:
            snapshot = snapshots[program_key]
            _logger.info(
                "[LPM_TIER_COD] USING_FROZEN_SNAPSHOT | order=%s | program=%s | program_id=%s "
                "| base_full_points=%.6f | frozen_final=%.6f | snapshot=%s",
                self.name,
                program.display_name,
                program.id,
                full_points,
                float(snapshot.get("final_points") or full_points),
                snapshot,
            )
            return float(snapshot.get("final_points") or full_points)

        tier_result = self.env["loyalty.tier.engine"].lpm_apply_tier_earning_policy(
            self.partner_id,
            program,
            self,
            full_points,
            source_label="cod_payment_collection",
        )
        final_points = float(tier_result["final_points"] or 0.0)
        if program.lpm_cod_tier_freeze_policy == "order":
            snapshots[program_key] = tier_result
            self.sudo().write({"lpm_cod_tier_snapshot_json": json.dumps(snapshots, sort_keys=True)})
            _logger.info(
                "[LPM_TIER_COD] SNAPSHOT_FROZEN | order=%s | program=%s | program_id=%s "
                "| base_full_points=%.6f | final_full_points=%.6f | tier_result=%s",
                self.name,
                program.display_name,
                program.id,
                full_points,
                final_points,
                tier_result,
            )
        return final_points

    def _lpm_cod_tier_snapshots(self):
        self.ensure_one()
        if not self.lpm_cod_tier_snapshot_json:
            return {}
        try:
            data = json.loads(self.lpm_cod_tier_snapshot_json)
        except (TypeError, ValueError):
            _logger.warning(
                "[LPM_TIER_COD] INVALID_SNAPSHOT_JSON | order=%s | raw=%s",
                self.name,
                self.lpm_cod_tier_snapshot_json,
            )
            return {}
        return data if isinstance(data, dict) else {}

    def _lpm_cod_loyalty_programs(self):
        self.ensure_one()
        config = self.session_id.config_id if self.session_id else False
        if config:
            programs = config._get_program_ids()
        else:
            today = fields.Date.context_today(self)
            programs = self.env['loyalty.program'].search([
                ('pos_ok', '=', True),
                '|', ('date_from', '=', False), ('date_from', '<=', today),
                '|', ('date_to', '=', False), ('date_to', '>=', today),
            ]).filtered(lambda p: not p.limit_usage or p.sudo().total_order_count < p.max_usage)

        return programs.filtered(
            lambda p: p.active
            and p.program_type == 'loyalty'
            and p.is_nominative
            and (not p.pricelist_ids or self.pricelist_id in p.pricelist_ids)
        )

    def _lpm_get_or_create_loyalty_card(self, program):
        self.ensure_one()
        card = self.env['loyalty.card'].sudo().search([
            ('partner_id', '=', self.partner_id.id),
            ('program_id', '=', program.id),
        ], limit=1)
        if card:
            return card
        return self.env['loyalty.card'].sudo().create({
            'partner_id': self.partner_id.id,
            'program_id': program.id,
            'points': 0.0,
        })

    def _lpm_cod_paid_total(self):
        self.ensure_one()
        return sum(
            float(collection.amount or 0.0)
            for collection in self.cod_collection_ids.filtered(lambda c: c.kind == 'payment')
        )

    def _lpm_cod_issued_points(self, program):
        self.ensure_one()
        histories = self.env['loyalty.history'].sudo().search([
            ('order_model', '=', self._name),
            ('order_id', '=', self.id),
            ('card_id.program_id', '=', program.id),
        ])
        return sum(float(history.issued or 0.0) for history in histories)

    def _lpm_cod_points_for_program(self, program):
        self.ensure_one()
        points = 0.0
        for rule in program.rule_ids.filtered(lambda r: r.active and r.mode == 'auto'):
            matching_lines = self.lines.filtered(
                lambda line: not line.is_reward_line
                and line.qty > 0
                and self._lpm_rule_matches_line(rule, line)
            )
            if not matching_lines:
                continue

            amount_incl = sum(float(line.price_subtotal_incl or 0.0) for line in matching_lines)
            amount_excl = sum(float(line.price_subtotal or 0.0) for line in matching_lines)
            amount_check = amount_incl if rule.minimum_amount_tax_mode == 'incl' else amount_excl
            total_qty = sum(float(line.qty or 0.0) for line in matching_lines)

            if rule.minimum_amount > amount_check or total_qty < rule.minimum_qty:
                continue

            if rule.reward_point_mode == 'order':
                points += rule.reward_point_amount
            elif rule.reward_point_mode == 'money':
                points += rule.reward_point_amount * amount_incl
            elif rule.reward_point_mode == 'unit':
                points += rule.reward_point_amount * total_qty

        return round(points, 6)

    def _lpm_rule_matches_line(self, rule, line):
        product = line.product_id
        if not product:
            return False
        if getattr(rule, 'any_product', False):
            return True
        valid_products = rule.valid_product_ids
        if valid_products:
            return product in valid_products
        if rule.product_ids:
            return product in rule.product_ids
        if rule.product_category_id:
            product_path = product.categ_id.parent_path or ''
            rule_path = rule.product_category_id.parent_path or ''
            return product.categ_id == rule.product_category_id or (
                bool(rule_path) and product_path.startswith(rule_path)
            )
        return True
