# -*- coding: utf-8 -*-
import logging
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command

_logger = logging.getLogger(__name__)

_SO_HEAD = "[LPM_SO_EARN_POLICY]"


class SaleOrderLoyaltyPolicy(models.Model):
    _inherit = "sale.order"

    lpm_backend_loyalty_awarded = fields.Boolean(
        string="Backend Loyalty Awarded",
        copy=False,
        readonly=True,
        help="Technical flag: backend Sale Order loyalty points were awarded after delivery, invoicing, and full payment.",
    )
    lpm_backend_loyalty_awarded_at = fields.Datetime(
        string="Backend Loyalty Awarded At",
        copy=False,
        readonly=True,
    )

    def action_confirm(self):
        self._lpm_validate_sale_order_loyalty_redemption_policy()
        return super().action_confirm()

    def _add_loyalty_history_lines(self):
        """Do not issue backend SO earning points during confirmation.

        Sale loyalty normally creates issued/used history before the order is
        confirmed. This policy keeps redemption history at confirmation time,
        but defers issued points until the final paid-invoice gate.
        """
        if self.env.context.get("lpm_allow_sale_order_loyalty_history"):
            return super()._add_loyalty_history_lines()

        for order in self:
            order._lpm_add_deferred_confirmation_history_lines()

    def _add_points_for_coupon(self, coupon_points):
        """Keep coupon_point_ids current, but do not credit confirmed SOs early."""
        self.ensure_one()
        if (
            self.state == "sale"
            and not self.env.context.get("lpm_allow_confirmed_so_point_write")
        ):
            _logger.info(
                "%s CONFIRMED_UPDATE_DEFERRED | order=%s | order_id=%s | coupon_points=%s",
                _SO_HEAD,
                self.name,
                self.id,
                {coupon.id: points for coupon, points in coupon_points.items()},
            )
            coupon_points = dict(coupon_points)
            for pe in self.coupon_point_ids.sudo():
                if pe.coupon_id in coupon_points:
                    pe.points = coupon_points.pop(pe.coupon_id)
            if coupon_points:
                self.sudo().with_context(tracking_disable=True).write({
                    "coupon_point_ids": [Command.create({
                        "coupon_id": coupon.id,
                        "points": points,
                    }) for coupon, points in coupon_points.items()]
                })
            return None
        return super()._add_points_for_coupon(coupon_points)

    def _get_point_changes(self):
        """Return only the point movements that have actually become effective.

        Before backend SO earning is awarded, confirmation/cancellation should
        only affect redeemed points. Once awarded, cancellation must reverse
        both issued points and redeemed points.
        """
        if self.env.context.get("lpm_standard_sale_order_point_changes"):
            return super()._get_point_changes()

        points_per_coupon = defaultdict(lambda: 0)
        for order in self:
            if order.lpm_backend_loyalty_awarded:
                histories = self.env["loyalty.history"].sudo().search([
                    ("order_model", "=", order._name),
                    ("order_id", "=", order.id),
                    ("issued", ">", 0),
                ])
                for history in histories:
                    points_per_coupon[history.card_id] += history.issued
            for line in order.order_line:
                if line.reward_id and line.coupon_id:
                    points_per_coupon[line.coupon_id] -= line.points_cost
        return points_per_coupon

    def _action_cancel(self):
        awarded = self.filtered("lpm_backend_loyalty_awarded")
        res = super()._action_cancel()
        if awarded:
            awarded.sudo().write({
                "lpm_backend_loyalty_awarded": False,
                "lpm_backend_loyalty_awarded_at": False,
            })
            _logger.info(
                "%s CANCEL_RESET | orders=%s",
                _SO_HEAD,
                awarded.mapped("name"),
            )
        return res

    def _lpm_add_deferred_confirmation_history_lines(self):
        self.ensure_one()
        points_per_coupon = defaultdict(partial_dict)
        for line in self.order_line:
            if line.coupon_id and line.points_cost:
                points_per_coupon[line.coupon_id]["cost"] += line.points_cost

        create_values = []
        base_values = {
            "order_id": self.id,
            "order_model": self._name,
            "description": "Order %s" % self.display_name,
        }
        for coupon, point_dict in points_per_coupon.items():
            used = point_dict.get("cost", 0.0)
            if not used:
                continue
            create_values.append({
                **base_values,
                "card_id": coupon.id,
                "used": used,
                "issued": 0.0,
            })

        if create_values:
            self.env["loyalty.history"].sudo().create(create_values)
            _logger.info(
                "%s CONFIRM_HISTORY_USED_ONLY | order=%s | order_id=%s | rows=%s",
                _SO_HEAD,
                self.name,
                self.id,
                create_values,
            )
        else:
            _logger.debug(
                "%s CONFIRM_HISTORY_SKIPPED | order=%s | order_id=%s | reason=no_redemption_cost",
                _SO_HEAD,
                self.name,
                self.id,
            )

    def _lpm_backend_loyalty_blockers(self):
        """Extension point for backend SO earning eligibility."""
        self.ensure_one()
        blockers = []
        if self.lpm_backend_loyalty_awarded:
            blockers.append("already_awarded")
        if self.state not in ("sale", "done"):
            blockers.append("not_confirmed")
        if not self._lpm_has_positive_backend_loyalty_points():
            blockers.append("no_positive_points")
        if self.partner_id and not self.partner_id._lpm_can_earn_points():
            blockers.append("partner_earn_disabled")
        if not self._lpm_is_fully_delivered_for_loyalty():
            blockers.append("not_delivered")
        if not self._lpm_has_posted_customer_invoice_for_loyalty():
            blockers.append("not_invoiced")
        if not self._lpm_is_fully_paid_for_loyalty():
            blockers.append("not_fully_paid")
        if self._lpm_has_pos_transfer_for_loyalty():
            blockers.append("pos_transfer_exists")
        return blockers

    def _lpm_validate_sale_order_loyalty_redemption_policy(self):
        for order in self:
            if not order.partner_id:
                continue
            redeemed_points = order._lpm_sale_order_redeemed_points()
            if redeemed_points <= 0:
                continue
            if order.partner_id._lpm_can_redeem_points():
                continue
            _logger.warning(
                "%s REDEMPTION_BLOCKED | order=%s | order_id=%s | partner=%s "
                "| partner_id=%s | redeemed_points=%.4f",
                _SO_HEAD,
                order.name,
                order.id,
                order.partner_id.display_name,
                order.partner_id.id,
                redeemed_points,
            )
            raise ValidationError(_(
                "Loyalty redemption is disabled for customer %(customer)s.",
                customer=order.partner_id.display_name,
            ))

    def _lpm_sale_order_redeemed_points(self):
        self.ensure_one()
        return sum(
            float(line.points_cost or 0.0)
            for line in self.order_line
            if line.reward_id and line.coupon_id
        )

    def _lpm_has_positive_backend_loyalty_points(self):
        self.ensure_one()
        return any(float(coupon_point.points or 0.0) > 0 for coupon_point in self.coupon_point_ids)

    def _lpm_is_fully_delivered_for_loyalty(self):
        self.ensure_one()
        return self.delivery_status == "full"

    def _lpm_invoice_records_for_loyalty(self):
        self.ensure_one()
        return self.invoice_ids.filtered(lambda move: move.move_type == "out_invoice")

    def _lpm_has_posted_customer_invoice_for_loyalty(self):
        self.ensure_one()
        return bool(self._lpm_invoice_records_for_loyalty().filtered(lambda move: move.state == "posted"))

    def _lpm_is_fully_paid_for_loyalty(self):
        self.ensure_one()
        invoices = self._lpm_invoice_records_for_loyalty().filtered(lambda move: move.state == "posted")
        return bool(invoices) and all(move.payment_state == "paid" for move in invoices)

    def _lpm_has_pos_transfer_for_loyalty(self):
        self.ensure_one()
        domain = [
            ("order_id.state", "!=", "cancel"),
            "|",
            ("sale_order_origin_id", "=", self.id),
            ("sale_order_line_id.order_id", "=", self.id),
        ]
        return bool(self.env["pos.order.line"].sudo().search_count(domain))

    def _lpm_award_backend_loyalty_if_ready(self, trigger="manual"):
        for order in self:
            blockers = order._lpm_backend_loyalty_blockers()
            _logger.info(
                "%s DECISION | trigger=%s | order=%s | order_id=%s | partner_id=%s "
                "| delivered=%s | invoice_status=%s | blockers=%s",
                _SO_HEAD,
                trigger,
                order.name,
                order.id,
                order.partner_id.id,
                order.delivery_status,
                order.invoice_status,
                blockers,
            )
            if blockers:
                continue
            order._lpm_award_backend_loyalty_points(trigger=trigger)

    def _lpm_award_backend_loyalty_points(self, trigger="manual"):
        self.ensure_one()
        issued_rows = []
        for coupon_point in self.coupon_point_ids:
            base_points = float(coupon_point.points or 0.0)
            if base_points <= 0:
                continue
            tier_result = self.env["loyalty.tier.engine"].lpm_apply_tier_earning_policy(
                self.partner_id,
                coupon_point.coupon_id.program_id,
                self,
                base_points,
                source_label="sale_order_award",
            )
            points = float(tier_result["final_points"] or 0.0)
            if points <= 0:
                _logger.info(
                    "%s AWARD_SKIPPED_AFTER_TIER | trigger=%s | order=%s | order_id=%s "
                    "| card_id=%s | base_points=%.6f | tier_result=%s",
                    _SO_HEAD,
                    trigger,
                    self.name,
                    self.id,
                    coupon_point.coupon_id.id,
                    base_points,
                    tier_result,
                )
                continue

            card = coupon_point.coupon_id.sudo()
            self.env.cr.execute(
                "SELECT points FROM loyalty_card WHERE id = %s FOR UPDATE",
                (card.id,),
            )
            row = self.env.cr.fetchone()
            before = float(row[0] if row else (card.points or 0.0))
            after = before + points
            card.write({"points": after})

            history = self.env["loyalty.history"].sudo().search([
                ("card_id", "=", card.id),
                ("order_model", "=", self._name),
                ("order_id", "=", self.id),
            ], limit=1)
            if history:
                history.write({"issued": float(history.issued or 0.0) + points})
            else:
                history = self.env["loyalty.history"].sudo().create({
                    "card_id": card.id,
                    "order_model": self._name,
                    "order_id": self.id,
                    "description": "Order %s" % self.display_name,
                    "issued": points,
                    "used": 0.0,
                })

            issued_rows.append({
                "card_id": card.id,
                "base_issued": base_points,
                "issued": points,
                "before": before,
                "after": after,
                "history_id": history.id,
                "tier_result": tier_result,
            })

        if issued_rows:
            self.sudo().write({
                "lpm_backend_loyalty_awarded": True,
                "lpm_backend_loyalty_awarded_at": fields.Datetime.now(),
            })
            _logger.info(
                "%s AWARDED | trigger=%s | order=%s | order_id=%s | rows=%s",
                _SO_HEAD,
                trigger,
                self.name,
                self.id,
                issued_rows,
            )


def partial_dict():
    return defaultdict(float)


class AccountMoveSaleOrderLoyaltyPolicy(models.Model):
    _inherit = "account.move"

    def action_post(self):
        res = super().action_post()
        self._lpm_check_sale_order_loyalty_from_invoices(trigger="invoice_post")
        return res

    def write(self, vals):
        res = super().write(vals)
        if {"payment_state", "state", "amount_residual"} & set(vals):
            self._lpm_check_sale_order_loyalty_from_invoices(trigger="invoice_write")
        return res

    def _lpm_check_sale_order_loyalty_from_invoices(self, trigger):
        orders = self._lpm_sale_orders_from_invoices()
        if orders:
            _logger.info(
                "%s INVOICE_TRIGGER | trigger=%s | invoices=%s | orders=%s",
                _SO_HEAD,
                trigger,
                self.mapped("name"),
                orders.mapped("name"),
            )
            orders._lpm_award_backend_loyalty_if_ready(trigger=trigger)

    def _lpm_sale_orders_from_invoices(self):
        lines = self.filtered(lambda move: move.move_type == "out_invoice").invoice_line_ids
        return lines.sale_line_ids.order_id


class AccountPartialReconcileSaleOrderLoyaltyPolicy(models.Model):
    _inherit = "account.partial.reconcile"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        moves = (records.debit_move_id.move_id | records.credit_move_id.move_id).filtered(
            lambda move: move.move_type == "out_invoice"
        )
        orders = moves._lpm_sale_orders_from_invoices()
        if orders:
            _logger.info(
                "%s RECONCILE_TRIGGER | reconciles=%s | invoices=%s | orders=%s",
                _SO_HEAD,
                records.ids,
                moves.mapped("name"),
                orders.mapped("name"),
            )
            orders._lpm_award_backend_loyalty_if_ready(trigger="invoice_reconcile")
        return records


class StockPickingSaleOrderLoyaltyPolicy(models.Model):
    _inherit = "stock.picking"

    def write(self, vals):
        res = super().write(vals)
        if vals.get("state") == "done":
            orders = self._lpm_sale_orders_from_pickings()
            if orders:
                _logger.info(
                    "%s DELIVERY_TRIGGER | pickings=%s | orders=%s",
                    _SO_HEAD,
                    self.mapped("name"),
                    orders.mapped("name"),
                )
                orders._lpm_award_backend_loyalty_if_ready(trigger="delivery_done")
        return res

    def _lpm_sale_orders_from_pickings(self):
        return (self.sale_id | self.move_ids.sale_line_id.order_id)
