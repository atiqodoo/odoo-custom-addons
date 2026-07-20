/** @odoo-module **/

import { TEMPORARY_POS_LOT_PREFIX } from "./constants";

export function normalizeLotName(value) {
    return String(value || "").trim();
}

export function isTemporaryPosLotName(value) {
    return normalizeLotName(value).toUpperCase().startsWith(TEMPORARY_POS_LOT_PREFIX);
}

export function isTintedProduct(product) {
    return Boolean(product?.is_tinted_product ?? product?.raw?.is_tinted_product);
}

export function partitionExistingLots(lots = []) {
    const sellableLots = [];
    const temporaryLots = [];
    for (const lot of lots || []) {
        (isTemporaryPosLotName(lot?.name) ? temporaryLots : sellableLots).push(lot);
    }
    return { sellableLots, temporaryLots };
}

export function partitionPackLotLines(lines = []) {
    const sellableLines = [];
    const temporaryLines = [];
    for (const line of lines || []) {
        const name = line?.text ?? line?.lot_name ?? line?.name;
        (isTemporaryPosLotName(name) ? temporaryLines : sellableLines).push(line);
    }
    return { sellableLines, temporaryLines };
}

/**
 * Allocate the standard net warehouse quantity across normal positive lots in
 * deterministic lot-id order. This prevents positive lot rows from overstating
 * sellable stock when Odoo also carries a separate lotless negative quant.
 */
export function capLotsByNetAvailability(lots = [], netAvailableQuantity = 0) {
    let remaining = Math.max(Number(netAvailableQuantity) || 0, 0);
    const selectableLots = [];
    const deferredLots = [];
    const orderedLots = [...(lots || [])].sort((left, right) => (left.id || 0) - (right.id || 0));

    for (const lot of orderedLots) {
        const lotQuantity = Math.max(Number(lot?.product_qty) || 0, 0);
        const allocatedQuantity = Math.min(lotQuantity, remaining);
        if (allocatedQuantity > 0) {
            selectableLots.push({ ...lot, product_qty: allocatedQuantity });
            remaining -= allocatedQuantity;
        }
        if (allocatedQuantity < lotQuantity) {
            deferredLots.push({
                ...lot,
                product_qty: lotQuantity - allocatedQuantity,
            });
        }
    }
    return { selectableLots, deferredLots };
}

export function temporaryNamesFromEditResult(result) {
    if (!result) {
        return [];
    }
    const names = [
        ...(result.newPackLotLines || []).map((line) => line?.lot_name),
        ...Object.values(result.modifiedPackLotLines || {}),
    ];
    return [...new Set(names.filter(isTemporaryPosLotName).map(normalizeLotName))];
}

export function temporaryNamesOnPositiveOrderLines(order) {
    const violations = [];
    for (const line of order?.lines || order?.get_orderlines?.() || []) {
        const quantity = Number(line?.qty ?? line?.get_quantity?.() ?? 0);
        if (quantity <= 0) {
            continue;
        }
        const lotNames = (line?.pack_lot_ids || [])
            .map((lot) => lot?.lot_name ?? lot?.text ?? lot?.name)
            .filter(isTemporaryPosLotName)
            .map(normalizeLotName);
        if (lotNames.length) {
            violations.push({
                line,
                productName:
                    line?.product_id?.display_name ||
                    line?.product_id?.name ||
                    line?.full_product_name ||
                    "Product",
                lotNames: [...new Set(lotNames)],
                quantity,
            });
        }
    }
    return violations;
}
