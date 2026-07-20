/** @odoo-module **/

/**
 * Frontend-only validation for a new COD dispatch.
 *
 * Amount signs are intentionally ignored: fixed-discount product lines have a
 * positive quantity and a negative unit price, and must remain valid.
 */

import { codError, codLog } from "@pos_cod/app/utils/cod_logger";

const COMPONENT = "CodQuantityGuard";

function getProductName(line, lineNumber) {
    return (
        line?.get_full_product_name?.() ||
        line?.product_id?.display_name ||
        line?.product_id?.name ||
        `Line ${lineNumber}`
    );
}

function getQuantity(line) {
    return typeof line?.get_quantity === "function" ? line.get_quantity() : line?.qty;
}

export function validateNewCodOrderQuantities(lines, orderContext = {}) {
    const orderLines = Array.from(lines || []);
    const invalidLines = [];

    codLog(COMPONENT, "validate", "Checking new COD order quantities.", {
        ...orderContext,
        line_count: orderLines.length,
    });

    for (const [index, line] of orderLines.entries()) {
        const rawQuantity = getQuantity(line);
        const quantity = Number(rawQuantity);
        const productName = getProductName(line, index + 1);
        const valid = Number.isFinite(quantity) && quantity > 0;

        codLog(COMPONENT, "validateLine", "COD line quantity check.", {
            ...orderContext,
            line_number: index + 1,
            product_id: line?.product_id?.id || line?.product_id || null,
            product: productName,
            raw_quantity: rawQuantity,
            parsed_quantity: quantity,
            price_unit: line?.price_unit,
            discount: line?.discount,
            valid,
        });

        if (!valid) {
            invalidLines.push({
                lineNumber: index + 1,
                productName,
                rawQuantity,
                quantity,
            });
        }
    }

    if (invalidLines.length) {
        codError(COMPONENT, "validate", "Blocked new COD order with invalid quantities.", {
            ...orderContext,
            invalid_lines: invalidLines,
        });
        return { valid: false, invalidLines };
    }

    codLog(COMPONENT, "validate", "New COD order quantities passed.", {
        ...orderContext,
        line_count: orderLines.length,
    });
    return { valid: true, invalidLines: [] };
}

export function formatInvalidCodQuantityLines(invalidLines) {
    return invalidLines
        .map(({ productName, rawQuantity }) => `${productName} (Qty: ${String(rawQuantity)})`)
        .join("\n");
}
