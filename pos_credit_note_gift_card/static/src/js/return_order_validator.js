/** @odoo-module **/
/**
 * return_order_validator.js
 * =========================
 * Pure-JS helper that holds all validation and computation logic used
 * BEFORE and DURING the credit-note issuance flow.
 *
 * It is intentionally separated from the payment-screen component so it
 * can be unit-tested or reused without mounting OWL components.
 *
 * Public API
 * ----------
 * ReturnOrderValidator.isRefundOrder(order)
 *     Detect whether the current POS order is a return/refund order.
 *
 * ReturnOrderValidator.hasNonReturnableLines(order)
 *     Returns [] (clean) or [{product, reason}] (blocked lines).
 *
 * ReturnOrderValidator.getAdjustedAmountBreakdown(amountData)
 *     Format the server's breakdown array for display in a popup.
 *
 * ReturnOrderValidator.formatCurrency(amount, currencySymbol)
 *     Simple currency formatter for receipt/popup display.
 *
 * Logging
 * -------
 * Set window.CN_DEBUG = true to activate console.debug output.
 */

const LOG_PREFIX = "[ReturnOrderValidator]";

function dbg(...args) {
    if (window.CN_DEBUG) {
        console.debug(LOG_PREFIX, ...args);
    }
}

export class ReturnOrderValidator {

    // =========================================================================
    // Refund detection
    // =========================================================================

    /**
     * An order is a refund/return when every non-reward line has qty < 0.
     * A completely empty order is NOT considered a refund.
     *
     * @param {Object} order  — POS order model instance
     * @returns {boolean}
     */
    static isRefundOrder(order) {
        if (!order) {
            dbg("isRefundOrder: no order");
            return false;
        }
        const lines = (order.lines || []).filter(
            (l) => !l.is_reward_line
        );
        if (lines.length === 0) {
            dbg("isRefundOrder: no non-reward lines → false");
            return false;
        }
        const allNegative = lines.every((l) => (l.qty || l.get_quantity?.() || 0) < 0);
        dbg("isRefundOrder:", allNegative, "lines:", lines.length);
        return allNegative;
    }

    // =========================================================================
    // Non-returnable product check (client-side, uses loaded POS data)
    // =========================================================================

    /**
     * Check all non-reward lines for the ``pos_not_returnable`` flag.
     *
     * Returns an array of blocked-line descriptors.  An empty array
     * means every product is returnable.
     *
     * @param {Object} order  — POS order model instance
     * @returns {Array<{product: string, reason: string}>}
     */
    static hasNonReturnableLines(order) {
        if (!order) return [];
        const blocked = [];
        for (const line of (order.lines || [])) {
            if (line.is_reward_line) continue;
            const product = line.product_id;
            const notReturnable =
                product?.pos_not_returnable ||
                product?.product_tmpl_id?.pos_not_returnable ||
                false;
            if (notReturnable) {
                const name = product?.display_name || product?.name || "Unknown product";
                dbg("Non-returnable product detected:", name);
                blocked.push({
                    product: name,
                    reason:  "Product is not eligible for return or refund.",
                });
            }
        }
        return blocked;
    }

    // =========================================================================
    // Amount breakdown formatter
    // =========================================================================

    /**
     * Format the server's breakdown array for display in the confirmation popup.
     *
     * @param {Array}  breakdown  — [{product, gross, discount_adj, commission_adj, net}]
     * @param {string} symbol     — currency symbol, e.g. "KSh"
     * @returns {Array<{product, gross, discountAdj, commissionAdj, net, grossFmt, netFmt}>}
     */
    static getAdjustedAmountBreakdown(breakdown, symbol = "") {
        return (breakdown || []).map((item) => ({
            product:       item.product || "?",
            gross:         item.gross || 0,
            discountAdj:   item.discount_adj || 0,
            commissionAdj: item.commission_adj || 0,
            net:           item.net || 0,
            grossFmt:      ReturnOrderValidator.formatCurrency(item.gross || 0, symbol),
            netFmt:        ReturnOrderValidator.formatCurrency(item.net || 0, symbol),
        }));
    }

    // =========================================================================
    // Currency formatter
    // =========================================================================

    /**
     * Simple number→currency string formatter.
     * Uses Intl.NumberFormat when available, falls back to toFixed(2).
     *
     * @param {number} amount
     * @param {string} symbol
     * @returns {string}
     */
    static formatCurrency(amount, symbol = "") {
        let formatted;
        try {
            formatted = new Intl.NumberFormat(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            }).format(amount);
        } catch {
            formatted = (amount || 0).toFixed(2);
        }
        return symbol ? `${symbol} ${formatted}` : formatted;
    }

    // =========================================================================
    // Client-side net amount computation
    // =========================================================================

    /**
     * Compute the net credit-note amount entirely on the client, mirroring the
     * server-side ``PosOrder.compute_credit_note_amount`` logic.
     *
     * All data required (price_subtotal_incl, discount, total_extra_amount,
     * total_base_profit) is already loaded into the POS session payload.
     *
     * @param {Object} order     — POS order model instance (refund order)
     * @param {Object} posConfig — pos.config model instance
     * @returns {{ total: number, currency: string, breakdown: Array }}
     */
    /**
     * @param {Object} order
     * @param {Object} posConfig
     * @param {Object} [commissionMap]  Pre-fetched server data keyed by
     *   str(originalLineId) → {total_extra_amount, total_base_profit, qty}.
     *   When provided this takes priority over the (zeroed) return-line fields.
     */
    static computeNetAmount(order, posConfig, commissionMap = {}) {
        const cfg       = ReturnOrderValidator.readConfig(posConfig);
        const distMode  = cfg.discountDistribution;
        const commMode  = cfg.commissionMode;
        const extraW    = cfg.extraWeight;
        const baseW     = cfg.baseWeight;

        const lines = (order.lines || []).filter((l) => !l.is_reward_line);

        // Pre-compute equal discount share if needed
        let equalSharePerLine = 0;
        if (distMode === "equal" && lines.length > 0) {
            const totalDiscount = lines.reduce((sum, l) => {
                const gross = Math.abs(l.price_subtotal_incl || 0);
                const disc  = (l.discount || 0) / 100;
                return sum + gross * disc;
            }, 0);
            equalSharePerLine = totalDiscount / lines.length;
        }

        const breakdown = [];
        let total = 0;

        dbg("computeNetAmount: line count =", lines.length, "| order =", order?.name);

        for (const line of lines) {
            // Prefer the dynamic getter over the stored field — for locally-created
            // refund lines in Odoo 18 the stored price_subtotal_incl may still be 0
            // while get_price_with_tax() always reflects the current qty × price.
            const rawTotal = line.get_price_with_tax?.()
                          ?? line.price_subtotal_incl
                          ?? 0;
            const gross   = Math.abs(rawTotal);
            const discPct = (line.discount || 0) / 100;

            dbg(
                "  line:", line.product_id?.display_name || line.product_id?.name,
                "| rawTotal:", rawTotal, "| gross:", gross,
                "| discount%:", line.discount,
            );

            // ---- Resolve server data for this line (used by BOTH discount
            //      and commission blocks below) ----------------------------
            const refLine      = line.refunded_orderline_id;
            const refId        = refLine
                ? (typeof refLine === "object" ? String(refLine.id) : String(refLine))
                : null;
            const serverComm    = refId ? (commissionMap[refId] || {}) : {};
            const retQty        = Math.abs(line.qty || line.get_quantity?.() || 0);
            const serverOrigQty = Math.abs(serverComm.qty || 1);
            const serverScale   = serverOrigQty > 0 ? retQty / serverOrigQty : 1;

            // ---- Discount adjustment -------------------------------------
            // Three sources of discount, all deducted when distMode != "none":
            //   1. Line-level percentage  (line.discount %)
            //   2. Equal share            (only when distMode === "equal")
            //   3. Global/reward discount (order-level reward lines, always
            //      proportional — server-computed and qty-scaled)
            // -------------------------------------------------------------
            let discountAdj      = 0;
            let netAfterDiscount = gross;

            if (distMode !== "none") {
                // Source 1 / 2 — line-level discount
                if (distMode === "proportional") {
                    discountAdj = gross * discPct;
                } else if (distMode === "equal") {
                    discountAdj = Math.min(equalSharePerLine, gross);
                }

                // Source 3 — global reward/coupon discount from original order
                // server returns the amount attributed to this line (proportional
                // to its revenue share); we scale by returned-qty fraction.
                const globalDiscAdj = (serverComm.global_discount_adj || 0) * serverScale;
                discountAdj += globalDiscAdj;

                if (globalDiscAdj > 0) {
                    console.log(
                        LOG_PREFIX, "[computeNetAmount] global_discount_adj |",
                        "refId=", refId,
                        "| server global_discount_adj=", (serverComm.global_discount_adj || 0).toFixed(4),
                        "| scale=", serverScale.toFixed(4),
                        "| applied=", globalDiscAdj.toFixed(4),
                    );
                }

                // Cap: discount can never exceed gross
                discountAdj = Math.min(discountAdj, gross);
            }

            netAfterDiscount = gross - discountAdj;

            // ---- Commission adjustment (Option B — deduct actual payout) ----
            // commissionMap keyed by str(original_line_id):
            //   { tier1_paid: float,   ← Tier-1 actual payout for this line
            //     tier2_paid: float,   ← Tier-2 actual payout for this line
            //     global_discount_adj: float,
            //     qty:        float }
            //
            // If the RPC failed, commissionMap = {} → deduction is 0 (safe).
            // -----------------------------------------------------------------
            let commissionAdj = 0;
            if (commMode !== "none") {
                const tier1Paid = (serverComm.tier1_paid || 0) * serverScale;
                const tier2Paid = (serverComm.tier2_paid || 0) * serverScale;

                console.log(
                    LOG_PREFIX, "[computeNetAmount] commission (Option B — actual payout) |",
                    "refId=", refId,
                    "| server tier1_paid=", (serverComm.tier1_paid || 0).toFixed(4),
                    "tier2_paid=", (serverComm.tier2_paid || 0).toFixed(4),
                    "qty=", serverComm.qty,
                    "| retQty=", retQty,
                    "scale=", serverScale.toFixed(4),
                    "| scaled tier1=", tier1Paid.toFixed(4),
                    "tier2=", tier2Paid.toFixed(4),
                );

                if (commMode === "extra_amount" || commMode === "both") {
                    commissionAdj += tier1Paid * (extraW / 100);
                }
                if (commMode === "base_profit" || commMode === "both") {
                    commissionAdj += tier2Paid * (baseW / 100);
                }
            }

            const net = Math.max(0, netAfterDiscount - commissionAdj);

            const product     = line.product_id;
            const productName = product?.display_name || product?.name || "?";

            breakdown.push({
                product:        productName,
                gross:          gross,
                discount_adj:   discountAdj,
                commission_adj: commissionAdj,
                net:            net,
            });
            total += net;
        }

        const currency =
            posConfig?.currency_id?.name ||
            posConfig?.currency_id?.symbol ||
            "";

        const result = {
            total:     Math.round(total * 100) / 100,
            currency:  currency,
            breakdown: breakdown,
        };
        // Always log so the developer can inspect without CN_DEBUG
        console.log("[ReturnOrderValidator][computeNetAmount] result:", JSON.stringify(result));
        dbg("computeNetAmount →", result);
        return result;
    }

    // =========================================================================
    // Client-side validation
    // =========================================================================

    /**
     * Validate the return order client-side and return {ok, errors, warnings}.
     * Mirrors the server-side ``validate_return_for_credit_note`` logic.
     *
     * @param {Object} order
     * @param {Object} posConfig
     * @returns {{ ok: boolean, errors: string[], warnings: string[] }}
     */
    static validateReturn(order, posConfig) {
        const errors   = [];
        const warnings = [];
        const cfg      = ReturnOrderValidator.readConfig(posConfig);

        if (!cfg.programId) {
            errors.push(
                "No credit-note gift-card program configured. " +
                "Please set one in POS Settings → Credit Note."
            );
        }

        if (!cfg.paymentMethodId) {
            errors.push(
                "No credit-note payment method configured. " +
                "Create a 'Miscellaneous' journal + payment method for credit note issuances, " +
                "add it to this POS terminal, then select it in POS Settings → Credit Note → Payment Method."
            );
        }

        const blocked = ReturnOrderValidator.hasNonReturnableLines(order);
        for (const b of blocked) {
            errors.push(`'${b.product}' is not eligible for return or refund (non-returnable product).`);
        }

        return { ok: errors.length === 0, errors, warnings };
    }

    // =========================================================================
    // Original order lookup helpers (used by the JS popup)
    // =========================================================================

    /**
     * Given a refund order, find the id of the original sale order.
     * In Odoo 18 POS the refund lines carry ``refunded_orderline_id``
     * which references the original line; the order id is one level up.
     *
     * Returns the id or null if it cannot be determined.
     *
     * @param {Object} refundOrder  — POS order model instance
     * @returns {number|null}
     */
    static getOriginalOrderId(refundOrder) {
        if (!refundOrder) return null;
        for (const line of (refundOrder.lines || [])) {
            const refLine = line.refunded_orderline_id;
            if (refLine) {
                const origOrderId =
                    (typeof refLine === "object" ? refLine.order_id?.id : null) ||
                    (typeof refLine === "object" ? refLine.order_id : null);
                if (origOrderId) {
                    dbg("getOriginalOrderId →", origOrderId);
                    return typeof origOrderId === "object"
                        ? origOrderId.id
                        : origOrderId;
                }
            }
        }
        dbg("getOriginalOrderId → null (no refunded_orderline_id found)");
        return null;
    }

    // =========================================================================
    // Config accessor helper
    // =========================================================================

    /**
     * Read credit-note config from the POS config model record.
     *
     * @param {Object} posConfig  — pos.config model instance (loaded in POS)
     * @returns {{
     *   programId: number|null,
     *   paymentMethodId: number|null,
     *   discountDistribution: string,
     *   commissionMode: string,
     *   extraWeight: number,
     *   baseWeight: number,
     *   requireReason: boolean,
     * }}
     */
    static readConfig(posConfig) {
        if (!posConfig) {
            return {
                programId:            null,
                paymentMethodId:      null,
                discountDistribution: "proportional",
                commissionMode:       "none",
                extraWeight:          100,
                baseWeight:           100,
                requireReason:        false,
            };
        }
        const cfg = {
            programId: posConfig.credit_note_gift_card_program_id
                ? (posConfig.credit_note_gift_card_program_id.id ||
                   posConfig.credit_note_gift_card_program_id)
                : null,
            paymentMethodId: posConfig.credit_note_payment_method_id
                ? (posConfig.credit_note_payment_method_id.id ||
                   posConfig.credit_note_payment_method_id)
                : null,
            discountDistribution: posConfig.credit_note_discount_distribution || "proportional",
            commissionMode:       posConfig.credit_note_commission_mode || "none",
            extraWeight:          posConfig.credit_note_extra_weight ?? 100,
            baseWeight:           posConfig.credit_note_base_weight ?? 100,
            requireReason:        Boolean(posConfig.credit_note_require_reason),
        };
        dbg("readConfig →", cfg);
        return cfg;
    }
}
