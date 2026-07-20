/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { EditListPopup } from "@point_of_sale/app/store/select_lot_popup/select_lot_popup";
import { ask, makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";

import { showNoSellableManufacturedLotDialog, showTemporaryLotBlockedDialog } from "./dialogs";
import { temporaryLotGuardLogger as log } from "./logger";
import {
    capLotsByNetAvailability,
    isTemporaryPosLotName,
    isTintedProduct,
    partitionExistingLots,
    partitionPackLotLines,
    temporaryNamesFromEditResult,
    temporaryNamesOnPositiveOrderLines,
} from "./policy";

patch(PosStore.prototype, {
    async addLineToCurrentOrder(vals, opts = {}, configure = true) {
        const scannedLot = opts?.code?.type === "lot" ? opts.code.code : false;
        if (scannedLot && isTemporaryPosLotName(scannedLot)) {
            const productName = vals?.product_id?.display_name || vals?.product_id?.name;
            log.warn("barcode_blocked", {
                productId: vals?.product_id?.id,
                productName,
                lotName: scannedLot,
            });
            showTemporaryLotBlockedDialog(this.dialog, {
                productName,
                lotNames: [scannedLot],
                source: _t("lot barcode scan"),
            });
            return;
        }
        const requestedQuantity = Number(vals?.qty ?? 1) || 1;
        const line = await super.addLineToCurrentOrder(...arguments);
        const allowance = this._temporaryLotGuardMissingLotAllowance;
        if (
            line &&
            allowance &&
            allowance.productId === line.product_id?.id &&
            !line.pack_lot_ids?.length
        ) {
            line.set_quantity(requestedQuantity);
            line.setDirty();
            log.warn("fresh_oversell_line_restored_without_lot", {
                productId: allowance.productId,
                productName: allowance.productName,
                quantity: requestedQuantity,
                settingEnabled: false,
                reason: "no_normal_lot_available",
            });
        }
        this._temporaryLotGuardMissingLotAllowance = null;
        return line;
    },

    async editLots(product, packLotLinesToEdit) {
        const productDetails = {
            productId: product.id,
            productName: product.display_name,
        };
        log.info("lot_selection_started", {
            ...productDetails,
            currentLineCount: packLotLinesToEdit?.length || 0,
        });

        const isAllowOnlyOneLot = product.isAllowOnlyOneLot();
        let canCreateLots = this.pickingType.use_create_lots || !this.pickingType.use_existing_lots;
        let existingLots = [];

        let stockSnapshot = { net_available_quantity: 0 };
        try {
            [existingLots, stockSnapshot] = await Promise.all([
                this.data.call(
                    "pos.order.line",
                    "get_existing_lots",
                    [this.company.id, product.id],
                    { context: { config_id: this.config.id } }
                ),
                this.data.call(
                    "pos.order.line",
                    "get_temporary_lot_guard_stock_snapshot",
                    [this.company.id, product.id],
                    { context: { config_id: this.config.id } }
                ),
            ]);
        } catch (error) {
            log.error("existing_lot_rpc_failed", {
                ...productDetails,
                error: error?.message || String(error),
            });
            const confirmed = await ask(this.dialog, {
                title: _t("Server communication problem"),
                body: _t(
                    "The existing serial/lot numbers could not be retrieved.\n" +
                        "Continue without checking the validity of serial/lot numbers?"
                ),
                confirmLabel: _t("Yes"),
                cancelLabel: _t("No"),
            });
            if (!confirmed) {
                return null;
            }
            canCreateLots = true;
        }

        const { sellableLots: positiveNormalLots, temporaryLots } = partitionExistingLots(
            existingLots
        );
        const { selectableLots: sellableLots, deferredLots } = capLotsByNetAvailability(
            positiveNormalLots,
            stockSnapshot.net_available_quantity
        );
        const { sellableLines, temporaryLines } = partitionPackLotLines(packLotLinesToEdit);
        const temporaryLotNames = temporaryLots.map((lot) => lot.name);

        if (temporaryLots.length || temporaryLines.length) {
            log.warn("temporary_lots_filtered", {
                ...productDetails,
                hiddenExistingLots: temporaryLotNames,
                removedDraftLots: temporaryLines.map((line) => line.text || line.lot_name),
                netAvailableQuantity: stockSnapshot.net_available_quantity,
                sellableLots: sellableLots.map((lot) => ({
                    name: lot.name,
                    quantity: lot.product_qty,
                })),
                debtDeferredNormalLots: deferredLots.map((lot) => ({
                    name: lot.name,
                    quantity: lot.product_qty,
                })),
            });
        }

        if (deferredLots.length) {
            log.warn("normal_lots_capped_by_net_stock", {
                ...productDetails,
                warehouseId: stockSnapshot.warehouse_id,
                warehouseName: stockSnapshot.warehouse_name,
                netAvailableQuantity: stockSnapshot.net_available_quantity,
                positiveNormalLotQuantity: positiveNormalLots.reduce(
                    (total, lot) => total + (Number(lot.product_qty) || 0),
                    0
                ),
                selectableLots: sellableLots.map((lot) => ({
                    id: lot.id,
                    name: lot.name,
                    quantity: lot.product_qty,
                })),
                deferredLots: deferredLots.map((lot) => ({
                    id: lot.id,
                    name: lot.name,
                    quantity: lot.product_qty,
                })),
            });
        }

        existingLots = sellableLots;
        packLotLinesToEdit = sellableLines;

        const tintedProduct = isTintedProduct(product);
        const blockWithoutNormalLot = Boolean(
            this.config?.block_tinted_oversell_without_normal_lot
        );
        const strictExistingSelection =
            tintedProduct && blockWithoutNormalLot && temporaryLots.length > 0;
        log.info("policy_resolved", {
            ...productDetails,
            tintedProduct,
            blockWithoutNormalLot,
            temporaryLotCount: temporaryLots.length,
            positiveNormalLotCount: positiveNormalLots.length,
            selectableNormalLotCount: sellableLots.length,
            netAvailableQuantity: stockSnapshot.net_available_quantity,
            strictExistingSelection,
        });
        if (strictExistingSelection) {
            canCreateLots = false;
        }

        const usedLotsQty = this.models["pos.pack.operation.lot"]
            .filter(
                (lot) =>
                    lot.pos_order_line_id?.product_id?.id === product.id &&
                    lot.pos_order_line_id?.order_id?.state === "draft"
            )
            .reduce((acc, lot) => {
                acc[lot.lot_name] ||= { total: 0, currentOrderCount: 0 };
                acc[lot.lot_name].total += lot.pos_order_line_id?.qty || 0;
                if (lot.pos_order_line_id?.order_id?.id === this.selectedOrder.id) {
                    acc[lot.lot_name].currentOrderCount += lot.pos_order_line_id?.qty || 0;
                }
                return acc;
            }, {});

        existingLots = existingLots.filter(
            (lot) => lot.product_qty > (usedLotsQty[lot.name]?.total || 0)
        );

        if (tintedProduct && temporaryLots.length && !existingLots.length) {
            if (blockWithoutNormalLot) {
                log.warn("tinted_oversell_blocked_by_setting", {
                    ...productDetails,
                    hiddenLots: temporaryLotNames,
                    settingEnabled: true,
                });
                showNoSellableManufacturedLotDialog(this.dialog, {
                    productName: product.display_name,
                    hiddenLots: temporaryLotNames,
                });
                return null;
            }

            this._temporaryLotGuardMissingLotAllowance = {
                productId: product.id,
                productName: product.display_name,
            };
            log.warn("fresh_oversell_allowed_by_setting", {
                ...productDetails,
                hiddenLots: temporaryLotNames,
                settingEnabled: false,
                action: "continue_without_lot_for_backend_preassignment",
            });
            return { modifiedPackLotLines: {}, newPackLotLines: [] };
        }

        if (!canCreateLots && !existingLots.length) {
            log.warn("no_existing_lot", productDetails);
            this.dialog.add(AlertDialog, {
                title: _t("No existing serial/lot number"),
                body: _t(
                    "There is no serial/lot number for the selected product, and lot creation " +
                        "is not allowed from the Point of Sale app."
                ),
            });
            return null;
        }

        const isLotNameUsed = (itemValue) => {
            const totalQty = existingLots.find((lot) => lot.name === itemValue)?.product_qty || 0;
            const usedQty = usedLotsQty[itemValue]
                ? usedLotsQty[itemValue].total - usedLotsQty[itemValue].currentOrderCount
                : 0;
            return usedQty ? usedQty >= totalQty : false;
        };

        const existingLotsName = existingLots.map((lot) => lot.name);
        if (!packLotLinesToEdit.length && existingLotsName.length === 1) {
            log.info("single_sellable_lot_auto_selected", {
                ...productDetails,
                lotName: existingLotsName[0],
            });
            return { newPackLotLines: [{ lot_name: existingLotsName[0] }] };
        }

        const payload = await makeAwaitable(this.dialog, EditListPopup, {
            title: _t("Lot/Serial Number(s) Required"),
            name: product.display_name,
            isSingleItem: isAllowOnlyOneLot,
            array: packLotLinesToEdit,
            options: existingLotsName,
            customInput: canCreateLots,
            uniqueValues: product.tracking === "serial",
            isLotNameUsed,
        });
        if (!payload) {
            log.info("lot_selection_cancelled", productDetails);
            return null;
        }

        const result = {
            modifiedPackLotLines: Object.fromEntries(
                payload.filter((item) => item.id).map((item) => [item.id, item.text])
            ),
            newPackLotLines: payload
                .filter((item) => !item.id)
                .map((item) => ({ lot_name: item.text })),
        };
        const blockedNames = temporaryNamesFromEditResult(result);
        if (blockedNames.length) {
            log.warn("typed_temporary_lot_blocked", {
                ...productDetails,
                lotNames: blockedNames,
            });
            showTemporaryLotBlockedDialog(this.dialog, {
                productName: product.display_name,
                lotNames: blockedNames,
                source: _t("manual lot entry"),
            });
            return null;
        }

        log.info("lot_selection_accepted", {
            ...productDetails,
            selectedLots: [
                ...result.newPackLotLines.map((line) => line.lot_name),
                ...Object.values(result.modifiedPackLotLines),
            ],
            strictExistingSelection,
        });
        return result;
    },

    async pay() {
        const order = this.get_order();
        const violations = temporaryNamesOnPositiveOrderLines(order);
        if (violations.length) {
            const lotNames = [...new Set(violations.flatMap((item) => item.lotNames))];
            log.warn("payment_blocked", {
                orderUuid: order?.uuid,
                orderName: order?.name,
                violations: violations.map((item) => ({
                    productName: item.productName,
                    quantity: item.quantity,
                    lotNames: item.lotNames,
                })),
            });
            showTemporaryLotBlockedDialog(this.dialog, {
                productName: violations.map((item) => item.productName).join(", "),
                lotNames,
                source: _t("final payment validation"),
            });
            return;
        }
        log.debug("payment_guard_passed", {
            orderUuid: order?.uuid,
            orderName: order?.name,
        });
        return super.pay(...arguments);
    },
});
