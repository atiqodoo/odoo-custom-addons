/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PosStore } from "@point_of_sale/app/store/pos_store";

const relationId = (value) => {
    if (!value) {
        return false;
    }
    if (typeof value === "number" || typeof value === "string") {
        return value;
    }
    if (Array.isArray(value)) {
        return value[0];
    }
    return value.id || value.raw?.id || false;
};

/**
 * Fix: When loading a confirmed Sale Order into POS, Odoo's settleSO method
 * can create two POS lines for the same lot-tracked sale.order.line:
 *
 *   1. the normal imported SO line without lot data
 *   2. the split line carrying the loaded lot data
 *
 * This happens especially with paint volume UoMs when the SO line is converted
 * after the tinted product has become lot-tracked.  The quotation/SO has the
 * correct number of lines; the duplicate appears during POS import.
 *
 * After core settleSO completes, collapse each sale_order_line_id group so the
 * lot-bearing line wins.  This keeps the POS cart from double-billing S00084.
 */
patch(PosStore.prototype, {
    _hasTintingSaleOrderLines(saleOrder) {
        return saleOrder?.order_line?.some((line) => line.is_tinted_product_line);
    },

    _isConfirmedSaleOrder(saleOrder) {
        return ["sale", "done"].includes(saleOrder?.state);
    },

    _showUnconfirmedTintingSaleOrderDialog(saleOrder) {
        const tintedLines = (saleOrder?.order_line || []).filter((line) => line.is_tinted_product_line);
        this.dialog.add(AlertDialog, {
            title: _t("Sales Order Not Confirmed"),
            body: _t(
                "This Sales Order contains tinted products from the tinting app, but the Sales Order is not confirmed yet.\n\nPlease confirm the Sales Order before selling these products in POS:\n%s",
                tintedLines.map((line) => line.display_name || line.name).join("\n")
            ),
        });
    },

    async pay() {
        const unconfirmedTintingOrders = await this._getUnconfirmedTintingSaleOrders();
        if (unconfirmedTintingOrders.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Sales Order Not Confirmed"),
                body: _t(
                    "This POS order contains tinted products from a Sales Order that is not confirmed yet.\n\nPlease confirm these Sales Order(s) before taking payment:\n%s",
                    unconfirmedTintingOrders.map((order) => order.name).join("\n")
                ),
            });
            return;
        }

        const pendingTintedLines = await this._getPendingTintedSaleOrderLines();
        if (pendingTintedLines.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Tinted Products Not Manufactured"),
                body: _t(
                    "This POS order contains tinted products from a Sales Order that are still pending manufacture/production.\n\nPlease manufacture/produce or remove these line(s) before taking payment:\n%s",
                    pendingTintedLines.map((line) => line.display_name || line.name).join("\n")
                ),
            });
            return;
        }
        return super.pay(...arguments);
    },

    async _refreshSaleOrderLines(lineIds) {
        if (!lineIds.length) {
            return [];
        }
        const refreshedLines = await this.data.read(
            "sale.order.line",
            lineIds,
            ["display_name", "name", "is_tinted_product_line", "tinted_product_created"]
        );
        const refreshedById = Object.fromEntries(refreshedLines.map((line) => [line.id, line]));
        for (const line of this.get_order()?.lines || []) {
            const saleOrderLine = line.sale_order_line_id;
            const refreshedLine = refreshedById[relationId(saleOrderLine)];
            if (saleOrderLine && refreshedLine) {
                saleOrderLine.update?.(refreshedLine);
                Object.assign(saleOrderLine, refreshedLine);
            }
        }
        return refreshedLines;
    },

    async _refreshTintingFlagsForSaleOrder(saleOrder) {
        const lineIds = (saleOrder?.order_line || []).map(relationId).filter(Boolean);
        const refreshedLines = await this._refreshSaleOrderLines(lineIds);
        if (refreshedLines.length) {
            const refreshedById = Object.fromEntries(refreshedLines.map((line) => [line.id, line]));
            saleOrder.order_line = saleOrder.order_line.map((line) => ({
                ...line,
                ...(refreshedById[relationId(line)] || {}),
            }));
        }
        return saleOrder;
    },

    async _getUnconfirmedTintingSaleOrders() {
        const order = this.get_order();
        if (!order) {
            return [];
        }

        const saleOrderIds = [
            ...new Set(order.lines.map((line) => relationId(line.sale_order_origin_id)).filter(Boolean)),
        ];
        const saleOrderLineIds = [
            ...new Set(order.lines.map((line) => relationId(line.sale_order_line_id)).filter(Boolean)),
        ];
        if (!saleOrderIds.length || !saleOrderLineIds.length) {
            return [];
        }

        const [saleOrders, saleOrderLines] = await Promise.all([
            this.data.read("sale.order", saleOrderIds, ["name", "state"]),
            this._refreshSaleOrderLines(saleOrderLineIds),
        ]);
        const saleOrderById = Object.fromEntries(saleOrders.map((saleOrder) => [saleOrder.id, saleOrder]));
        const tintedLineIds = new Set(
            saleOrderLines.filter((line) => line.is_tinted_product_line).map((line) => line.id)
        );
        const blockedOrderIds = new Set();
        for (const line of order.lines) {
            const saleOrderId = relationId(line.sale_order_origin_id);
            const saleOrderLineId = relationId(line.sale_order_line_id);
            const saleOrder = saleOrderById[saleOrderId];
            if (
                saleOrder &&
                tintedLineIds.has(saleOrderLineId) &&
                !this._isConfirmedSaleOrder(saleOrder)
            ) {
                blockedOrderIds.add(saleOrderId);
            }
        }
        return [...blockedOrderIds].map((id) => saleOrderById[id]).filter(Boolean);
    },

    async _getPendingTintedSaleOrderLines() {
        const order = this.get_order();
        if (!order) {
            return [];
        }

        const saleOrderLines = [];
        const lineIdsToRefresh = new Set();
        for (const line of order.lines) {
            const saleOrderLine = line.sale_order_line_id;
            if (!saleOrderLine) {
                continue;
            }
            saleOrderLines.push(saleOrderLine);
            if (
                saleOrderLine.is_tinted_product_line === undefined ||
                saleOrderLine.tinted_product_created === undefined
            ) {
                const solId = relationId(saleOrderLine);
                if (solId) {
                    lineIdsToRefresh.add(solId);
                }
            }
        }

        if (lineIdsToRefresh.size) {
            await this._refreshSaleOrderLines([...lineIdsToRefresh]);
        }

        return saleOrderLines.filter(
            (line) => line.is_tinted_product_line && !line.tinted_product_created
        );
    },

    async settleSO(sale_order, orderFiscalPos) {
        await this._refreshTintingFlagsForSaleOrder(sale_order);
        if (this._hasTintingSaleOrderLines(sale_order) && !this._isConfirmedSaleOrder(sale_order)) {
            this._showUnconfirmedTintingSaleOrderDialog(sale_order);
            return;
        }

        await super.settleSO(sale_order, orderFiscalPos);

        const order = this.get_order();
        if (!order) {
            return;
        }

        const asArray = (value) => {
            if (!value) {
                return [];
            }
            if (Array.isArray(value)) {
                return value;
            }
            if (typeof value === "object" && typeof value.length === "number") {
                return Array.from(value);
            }
            if (typeof value === "object" && Symbol.iterator in Object(value)) {
                return Array.from(value);
            }
            return [];
        };

        const hasLots = (line) =>
            asArray(line.pack_lot_ids).some((lot) => lot?.lot_name || lot?.name);

        const removeLine = (line) => {
            if (order.lines.includes(line)) {
                order.removeOrderline(line);
            } else {
                line.delete();
            }
        };

        const dedupeLines = (lines) => {
            if (lines.length <= 1) {
                return;
            }

            const lotLines = lines.filter(hasLots);
            if (lotLines.length) {
                for (const line of lines) {
                    if (!hasLots(line)) {
                        removeLine(line);
                    }
                }
                return;
            }

            // Same SO line imported more than once without lots: keep one.
            for (const line of lines.slice(1)) {
                removeLine(line);
            }
        };

        const bySaleOrderLine = {};
        for (const line of [...order.lines]) {
            const solId = relationId(line.sale_order_line_id);
            const soId = relationId(line.sale_order_origin_id);
            const productId = relationId(line.product_id);
            const key = solId
                ? `sol:${solId}`
                : soId && productId && line.product_id?.tracking === "lot"
                ? `so-product:${soId}:${productId}:${line.price_unit}:${line.qty}`
                : false;
            if (!key) {
                continue;
            }
            bySaleOrderLine[key] ||= [];
            bySaleOrderLine[key].push(line);
        }

        for (const lines of Object.values(bySaleOrderLine)) {
            dedupeLines(lines);
        }

        order.recomputeOrderData();
    },

    async downPaymentSO(sale_order) {
        await this._refreshTintingFlagsForSaleOrder(sale_order);
        if (this._hasTintingSaleOrderLines(sale_order) && !this._isConfirmedSaleOrder(sale_order)) {
            this._showUnconfirmedTintingSaleOrderDialog(sale_order);
            return;
        }
        return super.downPaymentSO(...arguments);
    },
});
