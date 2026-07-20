/**
 * @module pos_cod/app/components/cod_button/CodButton
 *
 * Patches the ProductScreen to inject a COD button into the control pad.
 *
 * On click:
 *   1. Validates the current order has at least one product line
 *   2. Opens CodWizard dialog (customer, employee, address, notes)
 *   3. On wizard confirm: attaches COD metadata to the order and dispatches
 *      to the backend via pos.cod_create_order()
 *   4. On success: resets current order
 *
 * The button is hidden when:
 *   - pos.config.cod_enabled is false
 *   - There are no lines on the current order
 */

import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { useService } from "@web/core/utils/hooks";
import { CodWizard } from "@pos_cod/app/components/cod_wizard/CodWizard";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { codWarn, codError, codLog } from "@pos_cod/app/utils/cod_logger";
import {
    formatInvalidCodQuantityLines,
    validateNewCodOrderQuantities,
} from "@pos_cod/app/utils/cod_quantity_guard";

const COMPONENT = "CodButton";
const COD_DISPATCH_PRINT_EVENT = "pos-cod:dispatch-print";

async function notifyCodDispatchPrint({ pos, order, serialized, backendResult, codPayload }) {
    const detail = {
        pos,
        order,
        serialized,
        backendResult,
        codPayload,
        promises: [],
    };
    codWarn(COMPONENT, "notifyCodDispatchPrint", "Emitting COD dispatch print event.", {
        order_name: order?.name,
        order_uid: order?.uuid || order?.uid || order?.id,
        amount_total: serialized?.amount_total,
    });
    window.dispatchEvent(new CustomEvent(COD_DISPATCH_PRINT_EVENT, { detail }));
    codLog(COMPONENT, "notifyCodDispatchPrint", "COD dispatch print listeners:", {
        promise_count: detail.promises.length,
    });
    if (detail.promises.length) {
        const results = await Promise.allSettled(detail.promises);
        const failures = results.filter((entry) => entry.status === "rejected");
        if (failures.length) {
            codError(COMPONENT, "notifyCodDispatchPrint", "One or more COD dispatch print listeners failed.", {
                failures: failures.map((entry) => entry.reason?.message || String(entry.reason)),
            });
        }
    }
}

patch(ProductScreen.prototype, {

    setup(...args) {
        super.setup(...args);
        this._codDialog = useService("dialog");
        codLog(COMPONENT, "setup", "ProductScreen patched for COD button.");
    },

    get codEnabled() {
        return !!this.pos.config?.cod_enabled;
    },

    get codButtonVisible() {
        if (!this.codEnabled) return false;
        const lines = this.currentOrder?.orderlines || this.currentOrder?.lines || [];
        return lines.length > 0;
    },

    async onCodButtonClick() {
        codWarn(COMPONENT, "onCodButtonClick", "COD button clicked.");

        const order = this.currentOrder;
        if (!order) {
            codError(COMPONENT, "onCodButtonClick", "No current order.");
            return;
        }

        const lines = order.orderlines || order.lines || [];
        if (!lines.length) {
            codError(COMPONENT, "onCodButtonClick", "Order has no product lines.");
            return;
        }

        const quantityValidation = validateNewCodOrderQuantities(lines, {
            order_name: order.name,
            order_uid: order.uuid || order.uid || order.id,
        });
        if (!quantityValidation.valid) {
            const invalidLineSummary = formatInvalidCodQuantityLines(
                quantityValidation.invalidLines
            );
            codError(
                COMPONENT,
                "onCodButtonClick",
                "COD dispatch blocked before opening the wizard.",
                { invalid_lines: quantityValidation.invalidLines }
            );
            this._codDialog.add(AlertDialog, {
                title: "COD Order Blocked",
                body:
                    "Every COD item must have a quantity greater than zero. " +
                    `Correct or remove:\n${invalidLineSummary}`,
            });
            return;
        }

        const existingPartnerId = order.partner_id?.id || order.partner_id || null;

        codWarn(COMPONENT, "onCodButtonClick", "Opening CodWizard.", {
            order_name:       order.name,
            existing_partner: existingPartnerId,
            lines:            lines.length,
        });

        const result = await makeAwaitable(this._codDialog, CodWizard, {
            partner_id: existingPartnerId,
        });

        codLog(COMPONENT, "onCodButtonClick", "Wizard result:", result);

        if (!result?.confirmed || !result.payload) {
            codWarn(COMPONENT, "onCodButtonClick", "Wizard cancelled — no action taken.");
            return;
        }

        const { partner_id, employee_id, delivery_address, delivery_notes } = result.payload;

        codWarn(COMPONENT, "onCodButtonClick", "Wizard confirmed. Building COD order payload.", {
            partner_id,
            employee_id,
            delivery_address,
        });

        try {
            for (const line of lines) {
                line.setLinePrice?.();
                line.setDirty?.();
            }
            order.recomputeOrderData?.();

            const serialized = order.serialize({ orm: true });

            serialized.is_cod               = true;
            serialized.cod_state            = "pending";
            serialized.partner_id           = partner_id;
            serialized.delivery_employee_id = employee_id;
            serialized.delivery_address     = delivery_address || "";
            serialized.delivery_notes       = delivery_notes  || "";

            codWarn(COMPONENT, "onCodButtonClick", "Sending COD order to backend...");
            const backendResult = await this.pos.cod_create_order(serialized);
            codWarn(COMPONENT, "onCodButtonClick", "COD order dispatched successfully.");
            await notifyCodDispatchPrint({
                pos: this.pos,
                order,
                serialized,
                backendResult,
                codPayload: result.payload,
            });

            this.pos.removePendingOrder?.(order);
            order.clearCommands?.();
            this.pos.removeOrder?.(order, false);
            this.pos.add_new_order();

        } catch (err) {
            const errMsg = err?.data?.message || err?.message || "An unexpected error occurred. Please try again.";
            codError(COMPONENT, "onCodButtonClick", "Failed to dispatch COD order:", errMsg);
            this._codDialog.add(AlertDialog, {
                title: "COD Dispatch Failed",
                body:  errMsg,
            });
        }
    },

});
