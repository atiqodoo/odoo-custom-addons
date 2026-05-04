/** @odoo-module **/

/**
 * unpaid_invoice_guard.js
 *
 * Blocks loyalty point REDEMPTION in the POS when the current customer has
 * outstanding (unpaid) invoices.
 *
 * ─── Intercept point ──────────────────────────────────────────────────────
 *   PosOrder._applyReward(reward, coupon_id, args)
 *
 *   This is the single entry point for all reward applications — both
 *   auto-applied (updateRewards loop) and manually triggered by the cashier.
 *   Returning a non-empty string signals an error; the POS loyalty service
 *   aborts the apply and the caller renders the message to the cashier.
 *
 * ─── Which rewards are intercepted ───────────────────────────────────────
 *   Only rewards where reward.required_points > 0 (i.e. the reward costs
 *   loyalty points).  Earning programs (adds points, no required_points)
 *   pass through untouched.
 *
 * ─── Caching strategy ────────────────────────────────────────────────────
 *   Cache is pre-warmed via the set_partner hook: as soon as the cashier
 *   selects a customer the backend check fires in the background.  By the
 *   time the cashier taps a reward button the result is ready, so the check
 *   inside _applyReward is synchronous (no await).
 *
 *   Cache TTL is 30 seconds.  A POS "Settle Account" payment that clears the
 *   invoice is NOT yet posted to accounting in the same session; the backend
 *   deducts same-session settlement payments before reporting has_unpaid, so
 *   the first re-query after settlement (≤ 30 s) lifts the block.
 *
 * ─── No reactive-Proxy access ────────────────────────────────────────────
 *   this.models and this.pos are Owl reactive Proxies.  Accessing them
 *   inside an async method (especially before an await) registers spurious
 *   reactive dependencies and causes Owl VToggler crashes on re-render.
 *   This file deliberately avoids any access to those properties at runtime.
 *
 * ─── Backend companion ───────────────────────────────────────────────────
 *   models/unpaid_invoice_guard.py  — get_partner_unpaid_invoice_info()
 *                                   — _process_order() safety net
 */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";

console.log("[unpaid_invoice_guard] module loaded");

patch(PosOrder.prototype, {

    // ─────────────────────────────────────────────────────────────────────────
    // Partner selection hook — pre-warm the cache
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Extend set_partner to trigger a background unpaid-invoice check the
     * moment the cashier selects a customer.  By the time the cashier taps
     * a loyalty reward button the RPC result is already cached, so the
     * _applyReward check below is effectively synchronous.
     *
     * @override
     */
    set_partner(partner) {
        const result = super.set_partner(...arguments);

        // Clear any stale cache for the previous partner
        this._unpaidInvoiceCache = {};

        const partnerId = partner?.id;
        if (partnerId) {
            console.log(
                "[unpaid_invoice_guard] set_partner: pre-warming cache" +
                " | partner=" + (partner?.name ?? "?") +
                " | partner_id=" + partnerId
            );
            // Fire-and-forget — do NOT await here (set_partner is sync)
            this._fetchUnpaidInvoiceInfo(partnerId).catch((err) => {
                console.error(
                    "[unpaid_invoice_guard] set_partner: pre-warm RPC failed" +
                    " | partner_id=" + partnerId,
                    err
                );
            });
        }

        return result;
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Core intercept
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Before applying any point-costing (redemption) reward, verify that the
     * current customer has no outstanding invoices.
     *
     * Returns a translated error string if blocked — the POS loyalty
     * machinery treats any truthy return from _applyReward as an error and
     * does NOT add the reward line.
     *
     * Design note: we deliberately avoid accessing this.models / this.pos
     * here because those are Owl reactive Proxies.  Accessing them before an
     * await registers spurious Owl reactive dependencies that cause
     * VToggler crashes when the order updates.
     *
     * @override
     */
    async _applyReward(reward, coupon_id, args) {
        const requiredPoints = reward?.required_points ?? 0;

        console.log(
            "[unpaid_invoice_guard] _applyReward intercept" +
            " | reward_id=" + (reward?.id ?? "?") +
            " | reward_type=" + (reward?.reward_type ?? "?") +
            " | required_points=" + requiredPoints +
            " | coupon_id=" + coupon_id
        );

        // Only intercept redemption rewards (those that consume loyalty points)
        if (requiredPoints > 0) {

            // ── Points balance pre-check (synchronous, before first await) ──────
            // Reads the loyalty card from the in-memory POS model cache.
            // Must be done BEFORE any await so we stay outside Owl reactive
            // tracking scope and avoid spurious dependency registration.
            //
            // This catches auto-applied rewards that Odoo's reward engine adds
            // without the cashier's explicit action — POS does not guard against
            // applying a reward the customer can't afford, so we do it here.
            // Returning a non-empty string prevents the reward line from being
            // added to the order; for auto-apply the string is silently discarded
            // (no error shown, checkout proceeds); for manual apply our
            // loyalty_block_popup.js patch shows it as an AlertDialog.
            const loyaltyCard = this.pos?.models?.['loyalty.card']?.get?.(coupon_id);
            if (loyaltyCard) {
                const availablePoints = loyaltyCard.points ?? 0;
                if (requiredPoints > availablePoints + 0.001) {
                    const errMsg = _t(
                        "Insufficient loyalty points: %(req)s points required but " +
                        "only %(avail)s available for this customer.",
                        {
                            req:   requiredPoints.toFixed(0),
                            avail: availablePoints.toFixed(0),
                        }
                    );
                    console.warn(
                        "[unpaid_invoice_guard] BLOCKED (insufficient points)" +
                        " | reward_id=" + (reward?.id ?? "?") +
                        " | required=" + requiredPoints +
                        " | available=" + availablePoints
                    );
                    return errMsg;
                }
                console.log(
                    "[unpaid_invoice_guard] points OK" +
                    " | required=" + requiredPoints +
                    " | available=" + (loyaltyCard.points ?? 0)
                );
            } else {
                console.log(
                    "[unpaid_invoice_guard] loyalty card not in cache" +
                    " | coupon_id=" + coupon_id +
                    " — skipping points check, backend will validate"
                );
            }

            const partner   = this.get_partner?.();
            const partnerId = partner?.id;

            console.log(
                "[unpaid_invoice_guard] redemption reward — checking unpaid invoices" +
                " | partner=" + (partner?.name ?? "none") +
                " | partner_id=" + (partnerId ?? "none")
            );

            if (partnerId) {
                // Prefer the synchronous cache path (pre-warmed by set_partner).
                // Falls back to async only on a cold start or expired cache.
                const info = await this._fetchUnpaidInvoiceInfo(partnerId);

                if (info?.has_unpaid) {
                    const errMsg = _t(
                        "Loyalty redemption blocked: %(name)s has %(count)s unpaid invoice(s)" +
                        " totalling %(total)s %(currency)s." +
                        " Please settle the outstanding balance before redeeming points.",
                        {
                            name:     partner.name,
                            count:    info.count,
                            total:    info.total.toFixed(2),
                            currency: info.currency,
                        }
                    );

                    console.warn(
                        "[unpaid_invoice_guard] BLOCKED" +
                        " | partner=" + partner.name +
                        " | unpaid_invoices=" + info.count +
                        " | unpaid_total=" + info.total.toFixed(2) + " " + info.currency
                    );

                    // Returning a non-empty string aborts the reward application.
                    // The POS loyalty UI surfaces this string to the cashier.
                    // NOTE: do NOT call any notification service here — accessing
                    // this.models.env (an Owl reactive Proxy) before returning
                    // from an async method causes VToggler render crashes.
                    return errMsg;
                }

                console.log(
                    "[unpaid_invoice_guard] no unpaid invoices" +
                    " | partner=" + partner.name +
                    " — redemption allowed"
                );
            } else {
                console.log(
                    "[unpaid_invoice_guard] no partner on order — skipping check," +
                    " proceeding with super"
                );
            }
        }

        return super._applyReward(...arguments);
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Backend fetch + TTL cache
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Fetch unpaid invoice info for a partner from the backend, with a
     * 30-second TTL cache on this order instance.
     *
     * Returns null on RPC error (fail-open) so a transient network issue
     * does not lock the cashier out of loyalty entirely.  The backend
     * _process_order safety net re-validates at payment time.
     *
     * @param  {number} partnerId  res.partner id
     * @returns {Promise<{has_unpaid:boolean,count:number,total:number,currency:string}|null>}
     */
    async _fetchUnpaidInvoiceInfo(partnerId) {
        const CACHE_TTL_MS = 30_000;

        if (!this._unpaidInvoiceCache) {
            this._unpaidInvoiceCache = {};
        }

        // Cache hit — only valid within TTL window
        const entry = this._unpaidInvoiceCache[partnerId];
        if (entry && (Date.now() - entry.ts) < CACHE_TTL_MS) {
            console.log(
                "[unpaid_invoice_guard] _fetchUnpaidInvoiceInfo: CACHE HIT" +
                " | partner_id=" + partnerId +
                " | has_unpaid=" + (entry.data?.has_unpaid ?? "null") +
                " | age_ms=" + (Date.now() - entry.ts)
            );
            return entry.data;
        }

        if (entry) {
            console.log(
                "[unpaid_invoice_guard] _fetchUnpaidInvoiceInfo: CACHE EXPIRED" +
                " | partner_id=" + partnerId +
                " | age_ms=" + (Date.now() - entry.ts) + " > TTL=" + CACHE_TTL_MS
            );
        }

        // Cache miss — call backend
        console.log(
            "[unpaid_invoice_guard] _fetchUnpaidInvoiceInfo: calling backend" +
            " | partner_id=" + partnerId
        );

        try {
            // @api.model: args is the positional args list passed directly to Python.
            // No leading [] IDs array — that is only for instance methods.
            const result = await rpc("/web/dataset/call_kw", {
                model: "pos.order",
                method: "get_partner_unpaid_invoice_info",
                args: [partnerId],
                kwargs: {},
            });

            console.log(
                "[unpaid_invoice_guard] backend response" +
                " | partner_id=" + partnerId +
                " | has_unpaid=" + (result?.has_unpaid ?? "?") +
                " | count=" + (result?.count ?? 0) +
                " | total=" + (result?.total ?? 0).toFixed(2) +
                " | currency=" + (result?.currency ?? "")
            );

            this._unpaidInvoiceCache[partnerId] = { data: result, ts: Date.now() };
            return result;

        } catch (err) {
            console.error(
                "[unpaid_invoice_guard] RPC error — failing OPEN (redemption allowed)." +
                " Backend _process_order will re-validate at payment time.",
                err
            );
            // Do not cache errors — retry next call
            return null;
        }
    },
});
