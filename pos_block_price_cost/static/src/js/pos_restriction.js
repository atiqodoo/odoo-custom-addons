/** @odoo-module **/

/**
 * pos_restriction.js
 * ───────────────────
 * Patches PaymentScreen.validateOrder.
 * Uses proven dual-API (saas/legacy) pattern for orderlines iteration.
 *
 * If any positive-qty line is priced below cost:
 *   → shows ManagerPinDialog (manager must enter PIN to override)
 *   → if PIN denied or cancelled → blocks validation
 *   → if PIN accepted → proceeds to super.validateOrder
 *
 * Refund lines (qty < 0) are always exempt.
 */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ManagerPinDialog } from "./manager_pin_dialog";

console.log("pos_block_price_cost: pos_restriction.js loaded");

function getCostInclTax(line, cost) {
    const prices = line.get_all_prices(1);
    const taxMultiplier = prices.priceWithoutTax ? prices.priceWithTax / prices.priceWithoutTax : 1;
    return {
        costInclTax: cost * taxMultiplier,
        priceInclTax: prices.priceWithTax,
    };
}

function primitiveId(value) {
    if (!value) return null;
    if (typeof value === "number") return value;
    if (typeof value === "string") return Number(value) || null;
    if (Array.isArray(value)) return primitiveId(value[0]);
    return primitiveId(value.id || value.raw?.id);
}

function getTaxIds(line, product) {
    let taxes = [];
    if (line.get_taxes) {
        taxes = line.get_taxes() || [];
    } else if (line.tax_ids) {
        taxes = line.tax_ids || [];
    } else if (product?.taxes_id) {
        taxes = product.taxes_id;
    }
    return (taxes || []).map((tax) => primitiveId(tax)).filter(Boolean);
}

function getOrderlines(order) {
    return order.getOrderlines
        ? order.getOrderlines()
        : (order.get_orderlines ? order.get_orderlines() : order.orderlines || order.lines || []);
}

function buildBelowCostPayload(order) {
    const payload = [];
    for (const [index, line] of getOrderlines(order).entries()) {
        const qty = line.getQuantity
            ? line.getQuantity()
            : (line.get_quantity ? line.get_quantity() : line.qty || 0);
        if (qty <= 0) continue;

        const product = line.getProduct
            ? line.getProduct()
            : (line.get_product ? line.get_product() : null);
        const productId = primitiveId(product);
        if (!productId) continue;

        let priceIncl = null;
        try {
            priceIncl = line.get_all_prices(1).priceWithTax;
        } catch (_) {
            // The backend can recompute from price_unit and taxes when needed.
        }

        payload.push({
            line_index: index + 1,
            product_id: productId,
            qty: Number(qty),
            price_incl: priceIncl === null ? null : Number(priceIncl),
            price_unit: Number(line.get_unit_price ? line.get_unit_price() : line.price_unit || 0),
            discount: Number(line.get_discount ? line.get_discount() : line.discount || 0),
            tax_ids: getTaxIds(line, product),
        });
    }
    return payload;
}

patch(PosOrder.prototype, {
    serialize() {
        const data = super.serialize(...arguments);
        if (this.pc_below_cost_override_token) {
            data.pc_below_cost_override_token = this.pc_below_cost_override_token;
        }
        if (this.pc_below_cost_override_employee_id) {
            data.pc_below_cost_override_employee_id = this.pc_below_cost_override_employee_id;
        }
        if (this.pc_below_cost_override_at) {
            data.pc_below_cost_override_at = this.pc_below_cost_override_at;
        }
        return data;
    },
});

patch(PaymentScreen.prototype, {

    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        if (!order) return super.validateOrder(...arguments);

        // ── Collect offending lines using dual-API ────────────────────────────
        // Support both getOrderlines() (SaaS) and get_orderlines() (Enterprise)
        const lines = getOrderlines(order);

        const offenders = [];

        for (const line of lines) {
            // ── Skip refunds ──────────────────────────────────────────────────
            const qty = line.getQuantity
                ? line.getQuantity()
                : (line.get_quantity ? line.get_quantity() : line.qty);

            if (qty < 0) continue;

            // ── Get product ───────────────────────────────────────────────────
            const product = line.getProduct
                ? line.getProduct()
                : (line.get_product ? line.get_product() : null);

            if (!product) continue;

            const cost = product.standard_price || 0;
            if (cost <= 0) continue;

            // ── Effective ex-VAT price (apples-to-apples vs standard_price) ──────
            let prices;
            try {
                prices = getCostInclTax(line, cost);
            } catch (_) {
                continue;
            }

            if (prices.priceInclTax < prices.costInclTax) {
                offenders.push(
                    `${product.display_name}  —  ` +
                    `${_t("Cost (incl. VAT)")}: ${prices.costInclTax.toFixed(2)}  |  ` +
                    `${_t("Selling (incl. VAT)")}: ${prices.priceInclTax.toFixed(2)}`
                );
            }
        }

        // ── If offenders found → request manager PIN ──────────────────────────
        if (offenders.length > 0) {
            console.warn(
                `pos_block_price_cost: ${offenders.length} below-cost line(s) ` +
                `— requesting manager PIN`
            );

            const granted = await this._pcRequestManagerOverride(offenders, order);

            if (!granted) {
                console.log(
                    "pos_block_price_cost: Override DENIED or cancelled — validation blocked"
                );
                return false;
            }

            console.log("pos_block_price_cost: Override GRANTED — proceeding");
        }

        return super.validateOrder(...arguments);
    },

    // ── Show manager PIN dialog and await result ──────────────────────────────

    _pcRequestManagerOverride(invalidLines, order = null) {
        return new Promise((resolve) => {
            this.dialog.add(ManagerPinDialog, {
                invalidLines,
                overrideContext: order
                    ? {
                        type: "below_cost_order",
                        order_uuid: order.uuid || "",
                        lines: buildBelowCostPayload(order),
                    }
                    : {},
                onConfirm: (employeeName, result) => {
                    if (order && result?.below_cost_override_token) {
                        order.pc_below_cost_override_token = result.below_cost_override_token;
                        order.pc_below_cost_override_employee_id = result.employee_id;
                        order.pc_below_cost_override_at = new Date().toISOString();
                    }
                    console.log(
                        `pos_block_price_cost: Override granted by '${employeeName}'`
                    );
                    resolve(true);
                },
                onCancel: () => {
                    resolve(false);
                },
            });
        });
    },
});
