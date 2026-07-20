/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

function formattedLotNames(lotNames = []) {
    return [...new Set(lotNames)].join(", ");
}

export function showTemporaryLotBlockedDialog(dialog, { productName, lotNames, source }) {
    dialog.add(AlertDialog, {
        title: _t("Temporary Oversell Lot Blocked"),
        body: _t(
            "The temporary lot %(lots)s cannot be used for another customer sale of %(product)s. " +
                "It belongs to an earlier POS oversell and is reserved for replenishment tracking.\n\n" +
                "Select a normal lot produced by a completed duplicated Manufacturing Order.\n\n" +
                "Detected from: %(source)s",
            {
                lots: formattedLotNames(lotNames),
                product: productName || _t("this product"),
                source: source || _t("POS lot selection"),
            }
        ),
    });
}

export function showNoSellableManufacturedLotDialog(dialog, { productName, hiddenLots }) {
    dialog.add(AlertDialog, {
        title: _t("No Sellable Manufactured Lot"),
        body: _t(
            "%(product)s currently has only temporary oversell lot(s): %(lots)s.\n\n" +
                "Complete an additional duplicated Manufacturing Order with a normal lot number, " +
                "then select that real-time lot in POS.",
            {
                product: productName || _t("This product"),
                lots: formattedLotNames(hiddenLots),
            }
        ),
    });
}

