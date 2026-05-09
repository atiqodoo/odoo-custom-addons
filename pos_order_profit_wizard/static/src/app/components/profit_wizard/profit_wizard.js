/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

function parseNumber(value, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function getOrderlines(order) {
    return order?.getOrderlines?.() || order?.get_orderlines?.() || order?.orderlines || order?.lines || [];
}

function getProduct(line) {
    return line?.get_product?.() || line?.product_id || line?.product || null;
}

function getQuantity(line) {
    return parseNumber(line?.get_quantity?.() ?? line?.qty ?? line?.quantity, 0);
}

function getUnitPrice(line) {
    return parseNumber(line?.get_unit_price?.() ?? line?.price_unit, 0);
}

function getTaxRecords(product) {
    const taxes = product?.taxes_id || product?.tax_ids || [];
    if (Array.isArray(taxes)) {
        return taxes;
    }
    if (typeof taxes === "object") {
        return Object.values(taxes);
    }
    return [];
}

function getVatRate(product) {
    return getTaxRecords(product).reduce((total, tax) => {
        const amountType = tax?.amount_type || tax?.type_tax_use;
        const amount = parseNumber(tax?.amount, 0);
        if (amountType && amountType !== "percent") {
            return total;
        }
        return total + amount;
    }, 0);
}

function getCostInclVat(product) {
    const landedCost = parseNumber(product?.standard_price, 0);
    const vatRate = getVatRate(product);
    return landedCost * (1 + vatRate / 100);
}

function makeRow(line, index) {
    const product = getProduct(line);
    const qty = getQuantity(line);
    const sellingPrice = getUnitPrice(line);
    const costPrice = getCostInclVat(product);
    return {
        id: line?.uuid || line?.cid || line?.id || `line-${index}`,
        line,
        productName: product?.display_name || product?.name || _t("Product"),
        qty: qty.toString(),
        sellingPrice: sellingPrice.toString(),
        costPrice,
    };
}

export class PosOrderProfitWizard extends Component {
    static template = "pos_order_profit_wizard.PosOrderProfitWizard";
    static components = { Dialog };
    static props = {
        order: Object,
        close: Function,
    };

    setup() {
        this.state = useState({
            rows: getOrderlines(this.props.order)
                .filter((line) => getProduct(line))
                .map((line, index) => makeRow(line, index)),
        });
    }

    formatCurrency(value) {
        const amount = parseNumber(value, 0);
        return this.env.utils?.formatCurrency
            ? this.env.utils.formatCurrency(amount)
            : amount.toFixed(2);
    }

    profitPerQty(row) {
        return parseNumber(row.sellingPrice, 0) - parseNumber(row.costPrice, 0);
    }

    totalProfit(row) {
        return this.profitPerQty(row) * parseNumber(row.qty, 0);
    }

    get grandTotalProfit() {
        return this.state.rows.reduce((total, row) => total + this.totalProfit(row), 0);
    }

    updateQty(row, value) {
        row.qty = value;
    }

    updateSellingPrice(row, value) {
        row.sellingPrice = value;
    }

    save() {
        for (const row of this.state.rows) {
            const qty = parseNumber(row.qty, 0);
            const sellingPrice = parseNumber(row.sellingPrice, 0);
            if (row.line?.set_quantity) {
                row.line.set_quantity(qty);
            } else {
                row.line.qty = qty;
                row.line.quantity = qty;
            }
            if (row.line?.set_unit_price) {
                row.line.set_unit_price(sellingPrice);
            } else {
                row.line.price_unit = sellingPrice;
            }
        }
        this.props.order?.recomputeOrderData?.();
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
