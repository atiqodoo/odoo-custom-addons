/** @odoo-module **/
/**
 * Exchange adjustment guard.
 *
 * Detects mixed POS exchange orders (negative refunded lines plus positive
 * replacement lines) and reduces the refunded line value by the same paid-out
 * commission/global-discount rules used by credit notes.  Chrome logs are
 * always visible with prefix [CNExchangeAdjustmentGuard].
 */

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const LOG_PREFIX = "[CNExchangeAdjustmentGuard]";

function qtyOf(line) {
    return Number(line?.qty ?? line?.get_quantity?.() ?? 0) || 0;
}

function getLineTotal(line) {
    if (line?._cnExchangeOriginalUnitPrice !== undefined) {
        return qtyOf(line) * (Number(line._cnExchangeOriginalUnitPrice) || 0);
    }
    return Number(line?.get_price_with_tax?.() ?? line?.price_subtotal_incl ?? 0) || 0;
}

function getOriginalLineId(line) {
    const ref = line?.refunded_orderline_id;
    if (!ref) return null;
    const raw = typeof ref === "object" ? ref.id : ref;
    return Number.isFinite(Number(raw)) ? Number(raw) : null;
}

function getProductName(line) {
    return line?.product_id?.display_name || line?.product_id?.name || "?";
}

function getReturnLines(order) {
    return (order?.lines || []).filter((line) => !line.is_reward_line && qtyOf(line) < 0);
}

function isExchangeOrder(order) {
    const lines = (order?.lines || []).filter((line) => !line.is_reward_line);
    const hasReturn = lines.some((line) => qtyOf(line) < 0 && getOriginalLineId(line));
    const hasSale = lines.some((line) => qtyOf(line) > 0);
    return hasReturn && hasSale;
}

function readAdjustmentConfig(serverConfig = {}) {
    return {
        discountDistribution: serverConfig.discount_distribution || "proportional",
        commissionMode: serverConfig.commission_mode || "none",
        extraWeight: Number(serverConfig.extra_weight ?? 100),
        baseWeight: Number(serverConfig.base_weight ?? 100),
    };
}

async function fetchAdjustmentContext(configId, originalLineIds) {
    console.log(LOG_PREFIX, "RPC exchange context request", { configId, originalLineIds });
    const response = await rpc("/pos/credit_note/exchange_adjustment_context", {
        config_id: configId,
        original_line_ids: originalLineIds,
    });
    console.log(LOG_PREFIX, "RPC exchange context response", response);
    if (!response?.ok) {
        throw new Error(response?.error || "Exchange adjustment context failed.");
    }
    const payload = response.payload || {};
    if (payload.ok === false) {
        throw new Error(payload.error || "Exchange adjustment context failed.");
    }
    return payload;
}

function computeLineAdjustment(line, cfg, serverLine) {
    if (line._cnExchangeOriginalUnitPrice === undefined) {
        line._cnExchangeOriginalUnitPrice = Number(line.price_unit || 0) || 0;
    }
    const gross = Math.abs(getLineTotal(line));
    const returnQty = Math.abs(qtyOf(line));
    const originalQty = Math.abs(Number(serverLine?.qty || 1));
    const scale = originalQty > 0 ? returnQty / originalQty : 1;

    let discountAdj = 0;
    if (cfg.discountDistribution !== "none") {
        discountAdj += (Number(serverLine?.global_discount_adj || 0) || 0) * scale;
        if (cfg.discountDistribution === "proportional") {
            discountAdj += gross * ((Number(line.discount || 0) || 0) / 100);
        }
        discountAdj = Math.min(discountAdj, gross);
    }

    let commissionAdj = 0;
    if (cfg.commissionMode !== "none") {
        const tier1Paid = (Number(serverLine?.tier1_paid || 0) || 0) * scale;
        const tier2Paid = (Number(serverLine?.tier2_paid || 0) || 0) * scale;
        if (cfg.commissionMode === "extra_amount" || cfg.commissionMode === "both") {
            commissionAdj += tier1Paid * (cfg.extraWeight / 100);
        }
        if (cfg.commissionMode === "base_profit" || cfg.commissionMode === "both") {
            commissionAdj += tier2Paid * (cfg.baseWeight / 100);
        }
    }

    const totalAdjustment = Math.min(gross, discountAdj + commissionAdj);
    const netRefund = Math.max(0, gross - totalAdjustment);
    return { gross, discountAdj, commissionAdj, totalAdjustment, netRefund, scale };
}

function setReturnLineUnitPrice(line, netRefund) {
    const absQty = Math.abs(qtyOf(line));
    if (!absQty) return false;

    if (line._cnExchangeOriginalUnitPrice === undefined) {
        line._cnExchangeOriginalUnitPrice = Number(line.price_unit || 0) || 0;
    }

    const newUnitPrice = Math.round((netRefund / absQty) * 10000) / 10000;
    if (Math.abs((Number(line.price_unit || 0) || 0) - newUnitPrice) < 0.0001) {
        return false;
    }

    if (typeof line.set_unit_price === "function") {
        line.set_unit_price(newUnitPrice);
    } else {
        line.price_unit = newUnitPrice;
    }
    line._cnExchangeAdjusted = true;
    line._cnExchangeAdjustedUnitPrice = newUnitPrice;
    return true;
}

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        console.log(LOG_PREFIX, "PaymentScreen exchange guard active.");
    },

    async _cnApplyExchangeAdjustments() {
        const order = this.currentOrder;
        if (!isExchangeOrder(order)) {
            return { adjusted: false, totalAdjustment: 0, lines: [] };
        }

        const returnLines = getReturnLines(order);
        const originalLineIds = [
            ...new Set(returnLines.map(getOriginalLineId).filter((id) => id !== null)),
        ];
        if (!originalLineIds.length) {
            console.log(LOG_PREFIX, "Exchange detected but no original line ids were found.");
            return { adjusted: false, totalAdjustment: 0, lines: [] };
        }

        const context = await fetchAdjustmentContext(this.pos.config.id, originalLineIds);
        const cfg = readAdjustmentConfig(context.config);
        const lineMap = context.lines || {};
        let totalAdjustment = 0;
        const adjustedLines = [];

        for (const line of returnLines) {
            const originalLineId = getOriginalLineId(line);
            const serverLine = lineMap[String(originalLineId)] || {};
            const details = computeLineAdjustment(line, cfg, serverLine);
            console.log(LOG_PREFIX, "Line exchange check", {
                product: getProductName(line),
                originalLineId,
                cfg,
                serverLine,
                details,
            });

            if (details.totalAdjustment <= 0) continue;

            const changed = setReturnLineUnitPrice(line, details.netRefund);
            totalAdjustment += details.totalAdjustment;
            adjustedLines.push({
                product: getProductName(line),
                changed,
                originalLineId,
                ...details,
            });
        }

        if (adjustedLines.length) {
            order.recomputeOrderData?.();
            this.render?.();
            console.warn(LOG_PREFIX, "EXCHANGE VALUE ADJUSTED", {
                order: order?.name,
                totalAdjustment,
                adjustedLines,
                due: order?.get_due?.(),
            });
            this.notification?.add?.(
                _t("Exchange value adjusted for paid commission/discount: %(amount)s", {
                    amount: totalAdjustment.toFixed(2),
                }),
                { type: "warning" }
            );
            return { adjusted: true, totalAdjustment, lines: adjustedLines };
        }

        console.log(LOG_PREFIX, "Exchange allowed with no commission/discount adjustment.", {
            order: order?.name,
            originalLineIds,
        });
        return { adjusted: false, totalAdjustment: 0, lines: [] };
    },

    async addNewPaymentLine(paymentMethod) {
        try {
            await this._cnApplyExchangeAdjustments();
        } catch (err) {
            console.error(LOG_PREFIX, "Blocking payment line because exchange check failed:", err);
            this.dialog.add(AlertDialog, {
                title: _t("Exchange Validation Failed"),
                body: err.message || String(err),
            });
            this.notification?.add?.(
                _t("Exchange validation failed: %(error)s", {
                    error: err.message || String(err),
                }),
                { type: "danger" }
            );
            return;
        }
        return super.addNewPaymentLine(...arguments);
    },

    async validateOrder(isForceValidate) {
        try {
            await this._cnApplyExchangeAdjustments();
        } catch (err) {
            console.error(LOG_PREFIX, "Blocking validation because exchange check failed:", err);
            this.dialog.add(AlertDialog, {
                title: _t("Exchange Validation Failed"),
                body: err.message || String(err),
            });
            this.notification?.add?.(
                _t("Exchange validation failed: %(error)s", {
                    error: err.message || String(err),
                }),
                { type: "danger" }
            );
            return;
        }
        return super.validateOrder(...arguments);
    },
});
