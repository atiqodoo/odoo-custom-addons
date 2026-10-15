# -*- coding: utf-8 -*-
import logging
from odoo import _, models, api
from odoo.exceptions import ValidationError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)


class PosOrderLoyaltyOverride(models.Model):
    _inherit = 'pos.order'

    # -------------------------------------------------------------------------
    # Entry point — Odoo 18 signature: _process_order(self, order, existing_order)
    # `order` is the raw order dict (session_id, partner_id, lines, … at top level)
    # There is NO `draft` parameter — it is computed internally from order['state']
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # sync_from_ui override — loyalty deduction for sbl-intercepted orders
    #
    # sensible_pos_offline_sale_order.sync_from_ui converts orders to sale.order
    # only when the POS frontend sends the explicit sbl_create_sale_order flag.
    # Because confirm_coupon_programs is only called after a pos.order record is
    # created, it never runs for those explicit sale-order conversions and
    # loyalty.card.points is never reduced.
    #
    # Fix: pre-scan before super(), let sbl intercept, then apply deductions.
    # -------------------------------------------------------------------------

    @api.model
    def sync_from_ui(self, orders):
        """
        Pre-scan orders for loyalty redemptions on orders that the cashier
        explicitly sends to sale.order, then apply the point
        deductions directly after super() returns.
        """
        pending_deductions = {}  # { order_name: {'partner_id': int, 'uuid': str, 'deductions': {cid_str: pts}} }

        for order in orders:
            try:
                session_id = order.get('session_id')
                if not session_id:
                    continue
                pos_session = self.env['pos.session'].browse(session_id)
                if not self._loyalty_sbl_will_intercept(order, pos_session):
                    continue
            except Exception as exc:
                _logger.warning(
                    "[loyalty_sync_fix] pre-scan error for order %s: %s",
                    order.get('name', '?'), exc,
                )
                continue

            # Skip if sale.order already exists for this uuid — duplicate resync,
            # deduction was already applied on the first sync.
            order_uuid = order.get('uuid')
            if order_uuid:
                existing_so = self.env['sale.order'].sudo().search(
                    [('sbl_uuid', '=', order_uuid)], limit=1
                )
                if existing_so:
                    _logger.info(
                        "[loyalty_sync_fix] PRE-SCAN SKIP | order=%s (uuid=%s)"
                        " sale.order %s already exists — deduction already applied, skipping",
                        order.get('name', '?'), order_uuid, existing_so.name,
                    )
                    continue

            deductions = self._scan_raw_order_loyalty_deductions(order)
            if not deductions:
                _logger.debug(
                    "[loyalty_sync_fix] order=%s will be intercepted but has no loyalty redemptions",
                    order.get('name', '?'),
                )
                continue

            partner = self.env['res.partner'].browse(order.get('partner_id')).exists()
            if partner and not partner._lpm_can_redeem_points():
                _logger.warning(
                    "[LPM_PARTNER_LOYALTY_POLICY] POS_SO_INTERCEPT_REDEEM_BLOCKED "
                    "| order=%s | partner=%s | partner_id=%s | deductions=%s",
                    order.get('name', '?'),
                    partner.display_name,
                    partner.id,
                    deductions,
                )
                raise ValidationError(_(
                    "Loyalty redemption is disabled for customer %(customer)s.",
                    customer=partner.display_name,
                ))

            order_name = order.get('name', 'unknown')
            pending_deductions[order_name] = {
                'partner_id': order.get('partner_id'),
                'uuid': order.get('uuid'),
                'deductions': deductions,
            }
            _logger.info(
                "[loyalty_sync_fix] PRE-SCAN | order=%s | partner_id=%s"
                " | will be intercepted | redemptions=%s"
                " → queued for direct loyalty deduction after super()",
                order_name, order.get('partner_id'), deductions,
            )

        result = super().sync_from_ui(orders)

        if pending_deductions:
            _logger.info(
                "[loyalty_sync_fix] post-super: applying loyalty deductions"
                " for %d intercepted order(s): %s",
                len(pending_deductions), list(pending_deductions.keys()),
            )
            updated_cards = self._apply_intercepted_loyalty_deductions(pending_deductions)
            if updated_cards:
                # Inject updated loyalty.card records into the sync result so the
                # POS frontend's missingRecursive/loadData pipeline calls
                # oldRecord.update({id, points}) and refreshes the local cache.
                # This makes the receipt and customer-search balance correct in real-time.
                result.setdefault('loyalty.card', []).extend(updated_cards)
                _logger.info(
                    "[loyalty_sync_fix] injected %d updated loyalty.card record(s) into sync result: %s",
                    len(updated_cards),
                    [{'id': c['id'], 'points': c['points']} for c in updated_cards],
                )
        else:
            _logger.debug(
                "[loyalty_sync_fix] post-super: no intercepted loyalty orders — nothing to apply"
            )

        return result

    def _loyalty_sbl_will_intercept(self, order, pos_session):
        """
        Predict whether sensible_pos_offline_sale_order will intercept this order.
        It must only be true when the cashier clicked Create Sale Order and the
        frontend serialized the explicit sbl_create_sale_order flag.
        Returns False if sbl feature is not enabled or module is not installed.
        """
        config = pos_session.config_id if pos_session else None
        if not config:
            return False
        if not getattr(config, 'sbl_create_sale_order', False):
            return False
        if not order.get('sbl_create_sale_order'):
            return False
        return True

    def _scan_raw_order_loyalty_deductions(self, order):
        """
        Extract { str(coupon_id): float(pts_cost) } from a raw POS order dict.
        Only includes reward lines with points_cost > 0 and a positive coupon_id.
        """
        deductions = {}
        for entry in order.get('lines', []):
            if isinstance(entry, (list, tuple)) and len(entry) == 3:
                vals = entry[2]
            elif isinstance(entry, dict):
                vals = entry
            else:
                continue

            if not vals.get('is_reward_line'):
                continue

            pts_cost = float(vals.get('points_cost') or 0)
            if pts_cost <= 0:
                continue

            coupon_id = vals.get('coupon_id')
            if not coupon_id:
                continue
            try:
                cid_int = int(coupon_id)
            except (ValueError, TypeError):
                continue
            if cid_int <= 0:
                continue

            cid_str = str(cid_int)
            deductions[cid_str] = deductions.get(cid_str, 0) + pts_cost
            _logger.debug(
                "[loyalty_sync_fix]   reward line: coupon_id=%s | points_cost=%.2f | running_total=%.2f",
                cid_str, pts_cost, deductions[cid_str],
            )

        return deductions

    def _apply_intercepted_loyalty_deductions(self, pending_deductions):
        """
        Directly deduct loyalty.card.points for orders intercepted by
        sensible_pos_offline_sale_order.  Uses SELECT FOR UPDATE to serialise
        concurrent redemptions and prevent over-deduction.

        Args:
            pending_deductions: {
                order_name: {
                    'partner_id': int,
                    'uuid': str,
                    'deductions': { str(coupon_id): float(pts) }
                }
            }

        Returns:
            list of {'id': int, 'points': float} for each card updated,
            so the caller can inject these into the sync_from_ui result and
            trigger a real-time POS frontend cache refresh.
        """
        LoyaltyCard = self.env['loyalty.card'].sudo()
        updated_cards = []

        for order_name, info in pending_deductions.items():
            partner_id = info['partner_id']
            order_uuid = info.get('uuid')
            deductions = info['deductions']
            sale_order = self.env['sale.order'].sudo().search(
                [('sbl_uuid', '=', order_uuid)], limit=1
            ) if order_uuid else self.env['sale.order']

            _logger.info(
                "[loyalty_sync_fix] _apply_intercepted_loyalty_deductions"
                " | order=%s | partner_id=%s | deductions=%s",
                order_name, partner_id, deductions,
            )

            for cid_str, pts_to_deduct in deductions.items():
                if pts_to_deduct <= 0:
                    _logger.debug(
                        "[loyalty_sync_fix]   SKIP coupon=%s pts_to_deduct=%.2f <= 0",
                        cid_str, pts_to_deduct,
                    )
                    continue

                try:
                    cid_int = int(cid_str)
                except (ValueError, TypeError):
                    _logger.error(
                        "[loyalty_sync_fix]   SKIP invalid coupon_id=%s | order=%s",
                        cid_str, order_name,
                    )
                    continue

                card = LoyaltyCard.browse(cid_int)
                if not card.exists():
                    _logger.error(
                        "[loyalty_sync_fix]   SKIP coupon_id=%s not found in loyalty.card | order=%s",
                        cid_str, order_name,
                    )
                    continue

                # Row-level lock — serialise concurrent redemptions for the same card
                self.env.cr.execute(
                    "SELECT points FROM loyalty_card WHERE id = %s FOR UPDATE",
                    (cid_int,),
                )
                row = self.env.cr.fetchone()
                locked_balance = float(row[0]) if row else 0.0

                _logger.info(
                    "[loyalty_sync_fix]   PRE-DEDUCT | order=%s | coupon_id=%s"
                    " | partner=%s | locked_balance=%.4f | pts_to_deduct=%.4f",
                    order_name, cid_str,
                    card.partner_id.name if card.partner_id else str(partner_id),
                    locked_balance, pts_to_deduct,
                )

                if pts_to_deduct > locked_balance + 0.001:
                    _logger.warning(
                        "[loyalty_sync_fix]   OVER-DEDUCTION GUARD | order=%s | coupon_id=%s"
                        " | requested=%.4f > locked=%.4f → capping to locked_balance",
                        order_name, cid_str, pts_to_deduct, locked_balance,
                    )
                    pts_to_deduct = locked_balance

                new_balance = round(max(0.0, locked_balance - pts_to_deduct), 6)
                card.write({'points': new_balance})
                self._create_intercepted_loyalty_history(
                    card, sale_order, order_name, pts_to_deduct
                )
                updated_cards.append({'id': cid_int, 'points': new_balance})

                _logger.info(
                    "[loyalty_sync_fix]   DEDUCTED | order=%s | coupon_id=%s"
                    " | locked_before=%.4f | deducted=%.4f | new_balance=%.4f",
                    order_name, cid_str,
                    locked_balance, pts_to_deduct, new_balance,
                )

        return updated_cards

    def _create_intercepted_loyalty_history(self, card, sale_order, order_name, points_used):
        """Mirror pos_loyalty history for Sensible sale-order intercepted redemptions."""
        history_vals = {
            'card_id': card.id,
            'description': "Onsite %s" % (sale_order.display_name if sale_order else order_name),
            'used': points_used,
            'issued': 0.0,
        }
        if sale_order:
            history_vals.update({
                'order_model': sale_order._name,
                'order_id': sale_order.id,
            })
        self.env['loyalty.history'].sudo().create(history_vals)

    # -------------------------------------------------------------------------
    # Zero-payment earning guard — mirrors frontend order_model_patch.js
    # -------------------------------------------------------------------------

    def confirm_coupon_programs(self, coupon_data):
        """
        Backend authority for loyalty point earning and spending.

        Three-step pipeline:
          1. Build an authoritative spending map from the saved reward order lines
             (points_cost per coupon_id).  This is the ground truth — it does not
             depend on whatever the frontend sent in coupon_data.
          2. Inject the authoritative spending into coupon_data so that
             points = won − authoritative_spent (correct net delta).
          3. Zero-payment earning guard: when amount_total = 0, zero the earning
             portion (won → 0) while PRESERVING the spending deduction
             (points stays at −spent).  The previous implementation set points = 0
             which wiped both earning AND spending, causing the card balance to
             remain unchanged instead of being reduced.

        coupon_data keys may be str or int (JSON always sends str; Odoo internals
        may pass int).  All key comparisons are normalised to str.
        """
        precision = (self.currency_id.rounding if self.currency_id else None) or 0.01

        _logger.info(
            "[loyalty_backend] confirm_coupon_programs START"
            " | order=%s | amount_total=%.4f | coupon_data_keys=%s",
            self.name, self.amount_total, list(coupon_data.keys()),
        )
        _logger.debug(
            "[loyalty_backend] confirm_coupon_programs | raw coupon_data=%s",
            {k: {fk: fv for fk, fv in v.items() if fk in ('points', 'won', 'spent')}
             for k, v in coupon_data.items()},
        )

        # ── Step 1: Build authoritative spending map from saved order lines ──────
        # By the time confirm_coupon_programs is called, self.lines are in the DB.
        # points_cost on each reward line is the exact points the customer redeemed.
        # We use this to correct the coupon_data the frontend sent, which may be
        # wrong due to stale balance, scale-factor bugs, or over-zeroing.
        spending_by_coupon = {}   # { str(coupon_id): float }
        for line in self.lines:
            if not line.is_reward_line or not line.coupon_id:
                continue
            pts_cost = float(line.points_cost or 0)
            if pts_cost <= 0:
                continue
            cid_str = str(line.coupon_id.id)
            prev = spending_by_coupon.get(cid_str, 0)
            spending_by_coupon[cid_str] = prev + pts_cost
            _logger.debug(
                "[loyalty_backend]   spending line | order=%s | coupon=%s"
                " | product=%s | points_cost=%.2f | running_total=%.2f",
                self.name, cid_str,
                line.product_id.name if line.product_id else '?',
                pts_cost, spending_by_coupon[cid_str],
            )

        _logger.info(
            "[loyalty_backend] authoritative spending map | order=%s | map=%s",
            self.name, spending_by_coupon,
        )

        # ── Step 2: Inject authoritative spending into coupon_data ───────────────
        # For each coupon that has reward lines on this order, recalculate:
        #   points = won − authoritative_spent
        # If coupon_data already reflects the correct spending, the values stay the
        # same.  If the frontend sent earning-only (spent = 0), this corrects it.
        # Negative coupon IDs are temporary client-side IDs for new cards not yet
        # in the DB; skip them (no card record to deduct from).
        corrected = {}
        for k, vals in coupon_data.items():
            # Normalise key to str for lookup
            k_str = str(k)
            try:
                k_int = int(k_str)
            except (ValueError, TypeError):
                k_int = None

            if k_int is not None and k_int < 0:
                # Temporary client-side ID — new card not yet persisted; leave unchanged
                _logger.debug(
                    "[loyalty_backend]   coupon=%s: negative ID (new card) — skipping correction",
                    k_str,
                )
                corrected[k] = vals
                continue

            authoritative_spent = spending_by_coupon.get(k_str, 0)
            original_points = vals.get('points', 0)
            original_spent  = vals.get('spent', 0)
            # Derive 'won' if absent: won = points + spent (since points = won − spent)
            derived_spent = authoritative_spent or float(original_spent)
            original_won = vals.get('won', max(0.0, float(original_points) + derived_spent))

            if authoritative_spent > 0:
                corrected_points = original_won - authoritative_spent
                _logger.info(
                    "[loyalty_backend]   CORRECTING coupon=%s"
                    " | original: points=%.2f  won=%.2f  spent=%.2f"
                    " | authoritative_spent=%.2f"
                    " | corrected: points=%.2f  won=%.2f  spent=%.2f",
                    k_str,
                    original_points, original_won, original_spent,
                    authoritative_spent,
                    corrected_points, original_won, authoritative_spent,
                )
                corrected[k] = {**vals,
                                'points': corrected_points,
                                'won':    original_won,
                                'spent':  authoritative_spent}
            else:
                _logger.debug(
                    "[loyalty_backend]   coupon=%s: no authoritative spending"
                    " | keeping original: points=%.2f  won=%.2f  spent=%.2f",
                    k_str, original_points, original_won, original_spent,
                )
                corrected[k] = vals

        coupon_data = corrected

        # ── Step 3: Zero-payment earning guard (fixed) ───────────────────────────
        # When amount_total = 0 the entire bill was covered by loyalty redemption.
        # Zero ONLY the earning (won → 0).  The spending deduction must survive so
        # the card balance is actually reduced.
        # Bug that existed before this fix: setting points = 0 cancelled BOTH
        # earning AND spending, leaving the card balance unchanged.
        if float_is_zero(self.amount_total, precision_rounding=precision):
            _logger.info(
                "[loyalty_backend] ZERO-PAYMENT guard | order=%s | amount_total=%.4f"
                " → zeroing earning, preserving spending deductions",
                self.name, self.amount_total,
            )
            cleaned = {}
            for k, vals in coupon_data.items():
                won   = float(vals.get('won',   0))
                spent = float(vals.get('spent', 0))
                pts   = float(vals.get('points', 0))
                if won > 0:
                    # Zero the earning; spending deduction (−spent) is preserved
                    new_pts = -spent if spent > 0 else 0.0
                    _logger.info(
                        "[loyalty_backend]   zero-pay coupon=%s:"
                        " won=%.2f → 0 | spent=%.2f | points: %.2f → %.2f",
                        k, won, spent, pts, new_pts,
                    )
                    vals = {**vals, 'points': new_pts, 'won': 0.0}
                else:
                    _logger.debug(
                        "[loyalty_backend]   zero-pay coupon=%s:"
                        " won already 0 | points=%.2f (unchanged)",
                        k, pts,
                    )
                cleaned[k] = vals
            coupon_data = cleaned

        coupon_data = self._lpm_apply_partner_loyalty_policy_to_coupon_data(
            coupon_data,
            spending_by_coupon=spending_by_coupon,
        )
        coupon_data = self._lpm_apply_tier_earning_policy_to_coupon_data(coupon_data)

        _logger.info(
            "[loyalty_backend] confirm_coupon_programs FINAL coupon_data | order=%s | data=%s",
            self.name,
            {k: {fk: round(fv, 4) if isinstance(fv, float) else fv
                 for fk, fv in v.items() if fk in ('points', 'won', 'spent')}
             for k, v in coupon_data.items()},
        )

        return super().confirm_coupon_programs(coupon_data)

    def _lpm_apply_tier_earning_policy_to_coupon_data(self, coupon_data):
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            return coupon_data

        adjusted = {}
        for coupon_key, vals in coupon_data.items():
            spent = float(vals.get('spent', 0.0) or 0.0)
            points = float(vals.get('points', 0.0) or 0.0)
            won = float(vals.get('won', max(0.0, points + spent)) or 0.0)
            if won <= 0:
                adjusted[coupon_key] = vals
                continue

            program = self._lpm_program_from_coupon_data(coupon_key, vals)
            if not program or program.lpm_tier_earning_policy == "none":
                adjusted[coupon_key] = vals
                continue

            tier_result = self.env["loyalty.tier.engine"].lpm_apply_tier_earning_policy(
                partner,
                program,
                self,
                won,
                source_label="pos_confirm_coupon_programs",
            )
            final_won = float(tier_result["final_points"] or 0.0)
            new_points = final_won - spent
            _logger.info(
                "[LPM_TIER_POS] COUPON_DATA_ADJUSTED | order=%s | partner=%s | partner_id=%s "
                "| coupon=%s | program=%s | program_id=%s | won=%.6f->%.6f "
                "| spent=%.6f | points=%.6f | tier_result=%s",
                self.name,
                partner.display_name,
                partner.id,
                coupon_key,
                program.display_name,
                program.id,
                won,
                final_won,
                spent,
                new_points,
                tier_result,
            )
            adjusted[coupon_key] = {**vals, 'won': final_won, 'points': new_points}
        return adjusted

    def _lpm_program_from_coupon_data(self, coupon_key, vals):
        program_id = vals.get('program_id')
        if program_id:
            return self.env['loyalty.program'].browse(program_id).exists()
        try:
            coupon_id = int(coupon_key)
        except (TypeError, ValueError):
            coupon_id = 0
        if coupon_id > 0:
            return self.env['loyalty.card'].browse(coupon_id).exists().program_id
        return self.env['loyalty.program']

    def _lpm_apply_partner_loyalty_policy_to_coupon_data(self, coupon_data, spending_by_coupon=None):
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            return coupon_data

        redeemed_points = self._lpm_coupon_data_redeemed_points(
            coupon_data,
            spending_by_coupon=spending_by_coupon,
        )
        if redeemed_points > 0 and not partner._lpm_can_redeem_points():
            _logger.warning(
                "[LPM_PARTNER_LOYALTY_POLICY] POS_REDEEM_BLOCKED | order=%s "
                "| partner=%s | partner_id=%s | redeemed_points=%.4f",
                self.name,
                partner.display_name,
                partner.id,
                redeemed_points,
            )
            raise ValidationError(_(
                "Loyalty redemption is disabled for customer %(customer)s.",
                customer=partner.display_name,
            ))

        if partner._lpm_can_earn_points():
            return coupon_data

        cleaned = {}
        for coupon_key, vals in coupon_data.items():
            won = float(vals.get('won', 0.0) or 0.0)
            spent = float(vals.get('spent', 0.0) or 0.0)
            points = float(vals.get('points', 0.0) or 0.0)
            if points < 0 and spent <= 0:
                spent = abs(points)

            if won > 0 or points > 0:
                new_points = -spent if spent > 0 else 0.0
                _logger.info(
                    "[LPM_PARTNER_LOYALTY_POLICY] POS_EARN_ZEROED | order=%s "
                    "| partner=%s | partner_id=%s | coupon=%s | won=%.4f->0 "
                    "| spent=%.4f | points=%.4f->%.4f",
                    self.name,
                    partner.display_name,
                    partner.id,
                    coupon_key,
                    won,
                    spent,
                    points,
                    new_points,
                )
                vals = {**vals, 'won': 0.0, 'points': new_points}
                if spent > 0:
                    vals['spent'] = spent
            cleaned[coupon_key] = vals
        return cleaned

    def _lpm_coupon_data_redeemed_points(self, coupon_data, spending_by_coupon=None):
        authoritative = sum(float(value or 0.0) for value in (spending_by_coupon or {}).values())
        declared_spent = 0.0
        declared_negative = 0.0
        for vals in coupon_data.values():
            declared_spent += max(0.0, float(vals.get('spent', 0.0) or 0.0))
            points = float(vals.get('points', 0.0) or 0.0)
            if points < 0:
                declared_negative += abs(points)
        return max(authoritative, declared_spent, declared_negative)

    # -------------------------------------------------------------------------
    # Entry point — Odoo 18 signature: _process_order(self, order, existing_order)
    # -------------------------------------------------------------------------

    @api.model
    def _process_order(self, order, existing_order):
        partner_id = order.get('partner_id')
        order_name = order.get('name', 'unknown')

        _logger.debug(
            "[loyalty_backend] _process_order called | order=%s | partner_id=%s | existing=%s",
            order_name, partner_id, existing_order is not None,
        )

        if partner_id:
            self._validate_loyalty_redemption_backend(order, partner_id)
        else:
            _logger.debug(
                "[loyalty_backend] _process_order: no partner on order %s — skipping loyalty check",
                order_name,
            )

        return super()._process_order(order, existing_order)

    # -------------------------------------------------------------------------
    # Redemption guard — atomic, race-condition safe
    # -------------------------------------------------------------------------

    def _validate_loyalty_redemption_backend(self, order, partner_id):
        """
        Audit log only — does NOT block the order.

        The primary enforcement is the frontend points-balance pre-check in
        _applyReward (unpaid_invoice_guard.js).  A backend raise here is too
        coarse: POS loyalty auto-applies rewards without the cashier's intent,
        so blocking the ENTIRE checkout when the auto-applied reward is over
        budget creates false-positive "Validation Error" dialogs on ordinary
        cash transactions.

        We keep the detection so that any slip-through (frontend bypassed or
        card balance changed between session start and payment) is visible in
        server logs.  The SELECT FOR UPDATE lock is kept so concurrent
        redemptions from multiple terminals are serialised and the log entry
        reflects the true locked balance at payment time.
        """
        order_name = order.get('name', 'unknown')

        _logger.debug(
            "[loyalty_backend] _validate_loyalty_redemption_backend | order=%s | partner_id=%s",
            order_name, partner_id,
        )

        loyalty_card = self.env['loyalty.card'].search(
            [
                ('partner_id', '=', partner_id),
                ('program_id.program_type', '=', 'loyalty'),
            ],
            order='points desc',
            limit=1,
        )

        if not loyalty_card:
            _logger.debug(
                "[loyalty_backend] No loyalty card found for partner_id=%s — skipping redemption check",
                partner_id,
            )
            return

        _logger.debug(
            "[loyalty_backend] Loyalty card found | card_id=%s | program=%s | points_before_lock=%.2f",
            loyalty_card.id,
            loyalty_card.program_id.name,
            loyalty_card.points,
        )

        # Row-level lock: serialise concurrent redemptions for the same card
        self.env.cr.execute(
            "SELECT points FROM loyalty_card WHERE id = %s FOR UPDATE",
            (loyalty_card.id,),
        )
        row = self.env.cr.fetchone()
        current_points = float(row[0]) if row else 0.0

        _logger.debug(
            "[loyalty_backend] Row-locked balance | card_id=%s | locked_points=%.2f",
            loyalty_card.id, current_points,
        )

        total_redeemed = self._extract_redeemed_points(order)

        _logger.debug(
            "[loyalty_backend] Redemption audit | order=%s | requested=%.2f | available=%.2f | partner=%s",
            order_name, total_redeemed, current_points, partner_id,
        )

        if total_redeemed > 0:
            partner = self.env['res.partner'].browse(partner_id).exists()
            if partner and not partner._lpm_can_redeem_points():
                _logger.warning(
                    "[LPM_PARTNER_LOYALTY_POLICY] POS_PROCESS_REDEEM_BLOCKED "
                    "| order=%s | partner=%s | partner_id=%s | redeemed_points=%.4f",
                    order_name,
                    partner.display_name,
                    partner.id,
                    total_redeemed,
                )
                raise ValidationError(_(
                    "Loyalty redemption is disabled for customer %(customer)s.",
                    customer=partner.display_name,
                ))

        if total_redeemed > 0 and total_redeemed > current_points + 0.001:
            _logger.warning(
                "[loyalty_backend] AUDIT: order=%s | requested=%.0f pts > available=%.0f pts"
                " | partner_id=%s | card_id=%s"
                " — frontend guard should have blocked this; allowing through (backend does not raise)",
                order_name, total_redeemed, current_points,
                partner_id, loyalty_card.id,
            )
        else:
            _logger.debug(
                "[loyalty_backend] PASSED | order=%s | redeemed=%.2f | remaining_after_order=%.2f",
                order_name,
                total_redeemed,
                current_points - total_redeemed,
            )

    def _extract_redeemed_points(self, order):
        """
        Sum the points_cost of every reward line in the order.

        `points_cost` is declared in pos_loyalty/models/pos_order.py (line 226)
        and is always serialised in the POS order payload for Odoo 18.

        Fallback for edge cases: estimate from line value / discount_per_point.

        Order lines arrive as ORM create-tuples: [0, 0, {vals}]
        """
        lines = order.get('lines', [])
        total_points = 0.0

        _logger.debug(
            "[loyalty_backend] _extract_redeemed_points | processing %d order lines",
            len(lines),
        )

        for idx, entry in enumerate(lines):
            if isinstance(entry, (list, tuple)) and len(entry) == 3:
                vals = entry[2]
            elif isinstance(entry, dict):
                vals = entry
            else:
                _logger.debug(
                    "[loyalty_backend]   line[%d]: unexpected format %s — skipped",
                    idx, type(entry).__name__,
                )
                continue

            if not vals.get('is_reward_line'):
                continue

            # Primary: pos_loyalty always sets points_cost on reward lines
            points_cost = vals.get('points_cost') or 0
            if points_cost:
                _logger.debug(
                    "[loyalty_backend]   reward line[%d]: points_cost=%.2f | reward_id=%s",
                    idx, float(points_cost), vals.get('reward_id'),
                )
                total_points += float(points_cost)
                continue

            # Fallback: derive from monetary value ÷ discount_per_point
            reward_id = vals.get('reward_id')
            if not reward_id:
                _logger.debug(
                    "[loyalty_backend]   reward line[%d]: no points_cost and no reward_id — skipped",
                    idx,
                )
                continue

            reward = self.env['loyalty.reward'].browse(reward_id).exists()
            if not reward or not reward.discount_per_point:
                _logger.debug(
                    "[loyalty_backend]   reward line[%d]: reward_id=%s has no discount_per_point — skipped",
                    idx, reward_id,
                )
                continue

            line_value = abs(vals.get('price_subtotal_incl', 0.0))
            estimated = line_value / reward.discount_per_point
            _logger.debug(
                "[loyalty_backend]   reward line[%d]: fallback estimate"
                " | line_value=%.2f | discount_per_point=%.4f | estimated_points=%.2f",
                idx, line_value, reward.discount_per_point, estimated,
            )
            total_points += estimated

        _logger.debug(
            "[loyalty_backend] _extract_redeemed_points total: %.2f", total_points,
        )
        return total_points

    # -------------------------------------------------------------------------
    # Net earning base — server mirror of loyalty_earning_engine.js
    # -------------------------------------------------------------------------

    def _compute_net_earning_base_server(self, order_lines_data):
        """
        Compute the tax-inclusive net paid value per product line after:
          Pass 1 — proportional allocation of global discount rewards
          Pass 2 — proportional allocation of other redemption rewards

        Mirrors computeNetLineValues() in loyalty_earning_engine.js.

        Returns: { line_index: net_paid_value }
        """
        product_lines = [l for l in order_lines_data if not l.get('is_reward_line')]
        discount_lines = [
            l for l in order_lines_data
            if l.get('is_reward_line') and l.get('reward_type') == 'discount'
        ]
        other_reward_lines = [
            l for l in order_lines_data
            if l.get('is_reward_line') and l.get('reward_type') != 'discount'
        ]

        gross = {}
        grand_total = 0.0
        for idx, line in enumerate(product_lines):
            val = abs(line.get('price_subtotal_incl', 0.0))
            gross[idx] = val
            grand_total += val

        _logger.debug(
            "[loyalty_backend] _compute_net_earning_base_server"
            " | product_lines=%d | grand_total=%.2f"
            " | discount_lines=%d | other_reward_lines=%d",
            len(product_lines), grand_total,
            len(discount_lines), len(other_reward_lines),
        )

        if grand_total == 0.0:
            return {i: 0.0 for i in range(len(product_lines))}

        discount_pool = sum(abs(l.get('price_subtotal_incl', 0.0)) for l in discount_lines)
        discount_share = _distribute_proportionally(gross, discount_pool, grand_total)
        post_discount = {k: max(0.0, gross[k] - discount_share[k]) for k in gross}

        redemption_pool = sum(abs(l.get('price_subtotal_incl', 0.0)) for l in other_reward_lines)
        pd_total = sum(post_discount.values())
        redemption_share = _distribute_proportionally(post_discount, redemption_pool, pd_total)

        net = {k: max(0.0, post_discount[k] - redemption_share[k]) for k in post_discount}

        _logger.debug(
            "[loyalty_backend] _compute_net_earning_base_server result"
            " | discount_pool=%.2f | redemption_pool=%.2f | net_total=%.2f",
            discount_pool, redemption_pool, sum(net.values()),
        )

        return net


# -------------------------------------------------------------------------
# Module-level helper
# -------------------------------------------------------------------------

def _distribute_proportionally(values_dict, pool, base_total):
    """
    Allocate `pool` across entries of `values_dict` proportionally to their
    values. Applies Largest Remainder Method to eliminate rounding drift so
    that sum(result.values()) == pool exactly.
    """
    if pool <= 0.0 or base_total <= 0.0:
        return {k: 0.0 for k in values_dict}

    result = {}
    fractionals = []
    total_floored = 0.0

    for k, v in values_dict.items():
        exact = (v / base_total) * pool
        floored = int(exact * 100) / 100.0
        result[k] = floored
        total_floored += floored
        fractionals.append((exact - floored, k))

    residual = round(pool - total_floored, 2)
    fractionals.sort(reverse=True)
    for _, k in fractionals:
        if residual <= 0.0:
            break
        bump = min(0.01, residual)
        result[k] = round(result[k] + bump, 2)
        residual = round(residual - bump, 2)

    return result
