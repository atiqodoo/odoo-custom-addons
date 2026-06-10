/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

const LOG_PREFIX = "pos_block_price_cost [create_sale_order_guard]";

console.log(`${LOG_PREFIX}: loaded`);

function getOrderLines(order) {
    if (!order) {
        return [];
    }
    if (order.getOrderlines) {
        return order.getOrderlines();
    }
    if (order.get_orderlines) {
        return order.get_orderlines();
    }
    return order.lines || order.orderlines || [];
}

function getProduct(line) {
    return line.getProduct ? line.getProduct() : line.get_product ? line.get_product() : line.product_id;
}

function primitiveId(value) {
    const rawId = typeof value === "object" && value !== null ? value.id ?? value.raw?.id : value;
    const id = Number(rawId);
    return Number.isFinite(id) ? id : false;
}

function getQuantity(line) {
    return line.getQuantity ? line.getQuantity() : line.get_quantity ? line.get_quantity() : line.qty || 0;
}

function getTaxIds(line) {
    let taxes = [];
    if (line.get_taxes) {
        taxes = line.get_taxes() || [];
    } else if (line.tax_ids) {
        taxes = line.tax_ids || [];
    }
    return taxes.map((tax) => primitiveId(tax)).filter(Boolean);
}

function formatOffenders(offenders) {
    return offenders
        .map(
            (item) =>
                `${item.product_name}\n` +
                `Selling incl. VAT: ${Number(item.price_incl).toFixed(2)} | ` +
                `Cost incl. VAT: ${Number(item.cost_incl).toFixed(2)}`
        )
        .join("\n\n");
}

patch(PosStore.prototype, {
    async createSaleOrder() {
        const blocked = await this._pcBlockBelowCostSaleOrder();
        if (blocked) {
            return false;
        }
        if (!super.createSaleOrder) {
            console.error(`${LOG_PREFIX}: super.createSaleOrder is not available`);
            this.dialog.add(AlertDialog, {
                title: _t("Sale Order Unavailable"),
                body: _t("The sale order creation action is not available in this POS session."),
            });
            return false;
        }
        return super.createSaleOrder(...arguments);
    },

    async _pcBlockBelowCostSaleOrder() {
        const order = this.get_order?.();
        if (!order) {
            console.warn(`${LOG_PREFIX}: no current order, skipping guard`);
            return false;
        }

        const payload = [];
        for (const [index, line] of getOrderLines(order).entries()) {
            const qty = Number(getQuantity(line) || 0);
            if (qty <= 0) {
                console.debug(`${LOG_PREFIX}: skipping line ${index + 1}, qty=${qty}`);
                continue;
            }

            const product = getProduct(line);
            const productId = primitiveId(product);
            if (!productId) {
                console.warn(`${LOG_PREFIX}: skipping line ${index + 1}, product missing`, line);
                continue;
            }

            let priceIncl = null;
            try {
                priceIncl = line.get_all_prices(1).priceWithTax;
            } catch (error) {
                console.warn(
                    `${LOG_PREFIX}: could not compute priceWithTax for product ${product.display_name}`,
                    error
                );
            }

            const taxIds = getTaxIds(line);
            payload.push({
                line_index: index + 1,
                product_id: productId,
                product_name: String(product.display_name || product.name || productId),
                qty: Number(qty),
                price_incl: priceIncl === null ? null : Number(priceIncl),
                price_unit: Number(line.get_unit_price ? line.get_unit_price() : line.price_unit || 0),
                discount: Number(line.get_discount ? line.get_discount() : line.discount || 0),
                tax_ids: taxIds,
            });
        }

        console.info(`${LOG_PREFIX}: checking ${payload.length} line(s) before sale order`, payload);
        if (!payload.length) {
            return false;
        }

        let offenders = [];
        try {
            offenders = await this.data.call("pos.session", "validate_sale_order_below_cost", [
                [this.session.id],
                payload,
            ]);
        } catch (error) {
            console.error(`${LOG_PREFIX}: RPC failed, blocking defensively`, error);
            this.dialog.add(AlertDialog, {
                title: _t("Cost Check Failed"),
                body: _t(
                    "The system could not verify product cost prices. Sale order creation has been blocked. Please try again or contact an administrator."
                ),
            });
            return true;
        }

        if (!offenders.length) {
            console.info(`${LOG_PREFIX}: pass, no below-cost sale order lines`);
            return false;
        }

        console.warn(`${LOG_PREFIX}: blocked, below-cost lines found`, offenders);
        this.dialog.add(AlertDialog, {
            title: _t("Sale Order Blocked"),
            body:
                _t("These products are below cost price including VAT:") +
                "\n\n" +
                formatOffenders(offenders),
        });
        return true;
    },
});
