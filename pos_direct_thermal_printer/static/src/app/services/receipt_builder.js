/** @odoo-module */

import { parseUTCString } from "@point_of_sale/utils";

function clean(value) {
    if (value === undefined || value === null || value === false) {
        return "";
    }
    const text = String(value).replace(/\s+/g, " ").trim();
    return /^(false|null|undefined)$/i.test(text) ? "" : text;
}

function cleanLine(value) {
    if (value === undefined || value === null || value === false) {
        return "";
    }
    return String(value).replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
}

function isMeaningful(value) {
    return Boolean(clean(value));
}

function money(pos, value) {
    try {
        return pos.env.utils.formatCurrency(value || 0);
    } catch {
        const symbol = pos.currency?.symbol || "";
        return `${symbol} ${Number(value || 0).toFixed(2)}`.trim();
    }
}

function points(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) {
        return "";
    }
    return Number.isInteger(number) ? String(number) : number.toFixed(2);
}

function partnerName(order) {
    const partner = order.get_partner?.();
    return clean(partner?.name);
}

function kenyanDateTime(value) {
    if (!value) {
        return "";
    }
    try {
        return parseUTCString(value).setZone("default").toFormat("dd/MM/yyyy HH:mm:ss");
    } catch {
        return clean(value);
    }
}

function productId(product) {
    if (!product) {
        return false;
    }
    return product.id || product.raw?.id || product.product_tmpl_id?.id || false;
}

function lineProduct(line) {
    return line?.get_product?.() || line?.product_id || line?.product || null;
}

function lineNumericTotal(line, printableLine) {
    const directAmount = Number(line?.get_display_price?.());
    if (Number.isFinite(directAmount)) {
        return directAmount;
    }
    const allPricesAmount = Number(line?.get_all_prices?.(1)?.priceWithTax);
    if (Number.isFinite(allPricesAmount)) {
        return allPricesAmount;
    }
    const qty = Number(line?.get_quantity?.() ?? line?.qty ?? printableLine?.qty ?? 1);
    const priceUnit = Number(line?.get_unit_price?.() ?? line?.price_unit);
    if (Number.isFinite(qty) && Number.isFinite(priceUnit)) {
        return qty * priceUnit;
    }
    const printableAmount = Number(String(printableLine?.price || "").replace(/[^\d.-]/g, ""));
    return Number.isFinite(printableAmount) ? printableAmount : 0;
}

function discountProductId(config) {
    return productId(config?.discount_product_id);
}

function isConfiguredDiscountLine(line, config) {
    const configuredId = discountProductId(config);
    return Boolean(configuredId && productId(lineProduct(line)) === configuredId);
}

function hasAdjustmentKeyword(text) {
    return /\b(discount|loyalty|reward|redeem|gift\s*card|voucher|coupon|ewallet|e-wallet)\b/i.test(
        clean(text)
    );
}

function isNegativeAdjustmentLine(line, printableLine, config) {
    const amount = lineNumericTotal(line, printableLine);
    if (!(amount < 0)) {
        return false;
    }
    if (line?.is_reward_line || line?.reward_id || line?.coupon_id) {
        return true;
    }
    if (line?.isGiftCardOrEWalletReward?.()) {
        return true;
    }
    if (isConfiguredDiscountLine(line, config)) {
        return true;
    }
    const product = lineProduct(line);
    return hasAdjustmentKeyword(product?.display_name || product?.name || printableLine?.productName);
}

function adjustmentLabel(line, printableLine, config) {
    if (line?.isGiftCardOrEWalletReward?.()) {
        return "Gift Card";
    }
    if (line?.is_reward_line || line?.reward_id || line?.coupon_id) {
        const points = Number(line?.points_cost || 0);
        return points > 0 ? `Loyalty Points Redeemed (${points} pts)` : "Loyalty Points Redeemed";
    }
    if (isConfiguredDiscountLine(line, config)) {
        return "Global Discount";
    }
    const product = lineProduct(line);
    return clean(product?.display_name || product?.name || printableLine?.productName) || "Discount";
}

function normalizeLabel(label) {
    return clean(label);
}

function metadataContext(pos, order, printable, company) {
    return {
        company_name: clean(company.name),
        street: clean(company.street),
        street2: clean(company.street2),
        city: clean(company.city),
        phone: clean(company.phone),
        email: clean(company.email),
        website: clean(company.website),
        vat: clean(company.vat),
        pos_name: clean(pos.config?.name),
        order_name: clean(printable.name || order.name || order.pos_reference),
        date: kenyanDateTime(order?.date_order) || clean(printable.date),
        cashier: clean(printable.cashier || order.getCashierName?.()),
        customer: partnerName(order),
    };
}

function renderTemplate(template, context) {
    const source = cleanLine(template);
    if (!source) {
        return [];
    }
    return source
        .split("\n")
        .map((rawLine) => {
            const values = [];
            const rendered = rawLine.replace(/\{([a-zA-Z0-9_]+)\}/g, (_match, key) => {
                const value = clean(context[key]);
                values.push(value);
                return value;
            });
            return values.length && values.every((value) => !value) ? "" : rendered;
        })
        .map((line) => clean(line))
        .filter(isMeaningful);
}

function defaultMetadataLines(context) {
    return [
        context.company_name,
        context.street,
        context.street2,
        context.city,
        context.phone,
        context.email,
        context.website,
        context.vat ? `VAT: ${context.vat}` : "",
    ].filter(isMeaningful);
}

function loyaltyCard(pos, couponId) {
    if (!couponId) {
        return null;
    }
    try {
        return pos.models?.["loyalty.card"]?.get?.(couponId) || null;
    } catch {
        return null;
    }
}

function loyaltyProgram(pos, programId) {
    if (!programId) {
        return null;
    }
    try {
        return pos.models?.["loyalty.program"]?.get?.(programId) || null;
    } catch {
        return null;
    }
}

function sumRedeemedPoints(sourceLines) {
    return sourceLines.reduce((total, line) => {
        if (line?.is_reward_line && Number(line?.points_cost || 0) > 0) {
            return total + Number(line.points_cost || 0);
        }
        return total;
    }, 0);
}

function earnedPoints(order) {
    const direct = Number(order.getNetLoyaltyPoints?.());
    if (Number.isFinite(direct) && direct > 0) {
        return direct;
    }
    const summaries = order.getLoyaltyPoints?.() || [];
    return summaries.reduce((total, entry) => {
        const won = Number(entry?.points?.won ?? entry?.won ?? 0);
        return Number.isFinite(won) && won > 0 ? total + won : total;
    }, 0);
}

function couponChanges(order) {
    return Object.values(order.uiState?.couponPointChanges || {});
}

function firstCouponChange(order) {
    return couponChanges(order).find((entry) => entry?.coupon_id || entry?.program_id) || null;
}

function buildLoyaltyLines(pos, order, sourceLines) {
    if (!pos.config?.dtrp_print_loyalty_transaction) {
        return [];
    }
    const redeemed = sumRedeemedPoints(sourceLines);
    const earned = earnedPoints(order);
    const change = firstCouponChange(order);
    const couponId =
        change?.coupon_id ||
        sourceLines.find((line) => line?.coupon_id)?.coupon_id?.id ||
        sourceLines.find((line) => line?.coupon_id)?.coupon_id;
    const card = loyaltyCard(pos, couponId);
    const program = loyaltyProgram(pos, change?.program_id || card?.program_id?.id || card?.program_id);
    const balance = Number(card?.points);
    const projectedBalance = Number.isFinite(balance) ? Math.max(0, balance + earned - redeemed) : null;

    if (!earned && !redeemed && !card) {
        return [];
    }

    const lines = ["LOYALTY TRANSACTION"];
    if (program?.name) {
        lines.push(`Program: ${clean(program.name)}`);
    }
    if (card?.code || card?.barcode || couponId) {
        lines.push(`Card: ${clean(card?.code || card?.barcode || couponId)}`);
    }
    if (earned) {
        lines.push(`Points Earned: ${points(earned)}`);
    }
    if (redeemed) {
        lines.push(`Points Redeemed: ${points(redeemed)}`);
    }
    if (projectedBalance !== null) {
        lines.push(`Balance: ${points(projectedBalance)}`);
    }

    console.log("[DTRP][receipt_builder] loyalty footer", {
        order: order.name || order.uid,
        couponId,
        earned,
        redeemed,
        balance,
        projectedBalance,
        lines,
    });
    return lines.filter(isMeaningful);
}

export function dtrpBuildReceipt(pos, order) {
    const printable = pos.orderExportForPrinting(order);
    const config = pos.config || {};
    const company = printable.headerData?.company || pos.company || {};
    const sourceLines = order.getSortedOrderlines?.() || order.get_orderlines?.() || [];
    const lines = [];
    const adjustmentLines = [];
    const metadata = metadataContext(pos, order, printable, company);

    for (const [index, line] of (printable.orderlines || []).entries()) {
        const sourceLine = sourceLines[index];
        const amount = lineNumericTotal(sourceLine, line);
        const shouldMoveAdjustment =
            config.dtrp_move_negative_adjustments_to_payments &&
            isNegativeAdjustmentLine(sourceLine, line, config);
        const payload = {
            name: clean(line.x_custom_pos_name || line.productName),
            qty: clean(line.qty),
            unit: clean(line.unit),
            unitPrice: clean(line.unitPrice),
            discount: clean(line.discount),
            price: clean(line.price),
            customerNote: clean(line.customerNote),
            taxGroupLabels: clean(line.taxGroupLabels),
            rawAmount: amount,
        };

        if (shouldMoveAdjustment) {
            const adjustment = {
                name: normalizeLabel(adjustmentLabel(sourceLine, line, config)),
                amount: money(pos, amount),
                rawAmount: amount,
            };
            adjustmentLines.push(adjustment);
            console.log("[DTRP][receipt_builder] moved negative adjustment to payment display", {
                order: metadata.order_name,
                index,
                adjustment,
                source: {
                    is_reward_line: Boolean(sourceLine?.is_reward_line),
                    reward_id: sourceLine?.reward_id?.id,
                    coupon_id: sourceLine?.coupon_id?.id,
                    product: lineProduct(sourceLine)?.display_name || lineProduct(sourceLine)?.name,
                },
            });
        } else {
            lines.push(payload);
        }
    }
    const paymentLines = (printable.paymentlines || []).map((line) => ({
        name: clean(line.name),
        amount: clean(line.amount),
    }));
    const renderedMetadata = renderTemplate(config.dtrp_receipt_metadata_template, metadata);
    const metadataLines = config.dtrp_receipt_metadata_template
        ? renderedMetadata
        : defaultMetadataLines(metadata);
    const totalDiscountRaw = Number(printable.total_discount || 0);
    const bottomFeedLines = Math.max(0, Math.min(12, Number(config.dtrp_bottom_feed_lines ?? 6)));
    return {
        orderUid: order.uuid || order.uid || order.id || printable.name,
        orderName: metadata.order_name,
        date: metadata.date,
        cashier: metadata.cashier,
        customer: config.dtrp_print_customer ? partnerName(order) : "",
        header: clean(printable.headerData?.header),
        footer: clean(printable.footer),
        metadataLines,
        company: {
            name: clean(company.name),
            phone: clean(company.phone),
            email: clean(company.email),
            website: clean(company.website),
            vat: clean(company.vat),
            street: clean(company.street),
            street2: clean(company.street2),
            city: clean(company.city),
        },
        lines,
        adjustmentLines,
        paymentLines,
        paymentDisplayLines: [...adjustmentLines, ...paymentLines],
        loyaltyLines: buildLoyaltyLines(pos, order, sourceLines),
        termsConditions: clean(config.dtrp_terms_conditions),
        bottomFeedLines,
        total: money(pos, printable.amount_total),
        totalWithoutTax: money(pos, printable.total_without_tax),
        tax: money(pos, printable.amount_tax),
        discount: money(pos, printable.total_discount),
        showDiscountTotal: Math.abs(totalDiscountRaw) > 0.0001,
        change: money(pos, printable.order_change || printable.change || 0),
        showChange: Boolean(printable.show_change),
        raw: {
            amountTotal: printable.amount_total,
            amountTax: printable.amount_tax,
            totalPaid: printable.total_paid,
            change: printable.order_change || printable.change || 0,
        },
    };
}
