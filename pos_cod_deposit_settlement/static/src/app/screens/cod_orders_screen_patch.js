/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CodOrdersScreen } from "@pos_cod/app/screens/cod_orders_screen/CodOrdersScreen";
import { CodDepositPopup } from "@pos_cod_deposit_settlement/app/dialogs/cod_deposit_popup";
import { cddsWarn, cddsError } from "@pos_cod_deposit_settlement/app/utils/cod_deposit_logger";

function operationUuid() {
    if (globalThis.crypto?.randomUUID) {
        return globalThis.crypto.randomUUID();
    }
    return `cdds-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

patch(CodOrdersScreen.prototype, {
    cddsReservedAmount(order) {
        return Number(order?.cdds_reserved_amount || 0);
    },

    async onApplyCustomerDeposit(order) {
        if (this.state.collecting) {
            return;
        }
        const orderId = this.orderServerId(order);
        this.state.collecting = true;
        this.state.message = "";
        cddsWarn(this.pos, "SCREEN", "apply deposit clicked", { order: order.name, orderId });
        try {
            const quote = await this.pos.cddsGetCodDepositQuote(orderId);
            if (!quote.success || !quote.maximum_amount) {
                this.state.message = quote.reason || "No cleared posted customer deposit is available.";
                this.state.messageType = "error";
                return;
            }
            let confirmedAmount = null;
            await new Promise((resolve) => {
                this.dialog.add(
                    CodDepositPopup,
                    {
                        title: `Apply Deposit - ${order.name}`,
                        quote,
                        onConfirm: (amount) => { confirmedAmount = amount; },
                    },
                    { onClose: resolve }
                );
            });
            if (!confirmedAmount) {
                cddsWarn(this.pos, "SCREEN", "cashier cancelled", { order: order.name });
                return;
            }
            const result = await this.pos.cddsApplyCodDeposit(orderId, confirmedAmount, operationUuid());
            if (result.reservation_pending) {
                this.state.message = `${result.order_name}: ${this.formatCurrency(result.amount)} same-session deposit reserved. ` +
                    `Reservation ${result.reservation_name} will finalize when session accounting closes. ` +
                    `The COD card remains visible until then.`;
            } else {
                this.state.message = `${result.order_name}: ${this.formatCurrency(result.amount)} deposit applied. ` +
                    (result.remaining > 0
                        ? `COD remaining ${this.formatCurrency(result.remaining)}.`
                        : `COD fully paid.`) +
                    ` Customer deposit remaining ${this.formatCurrency(result.deposit_remaining)}.`;
            }
            this.state.messageType = "success";
            if (!result.remaining && !result.reservation_pending) {
                this.state.selectedOrderId = null;
            }
        } catch (error) {
            const message = error?.data?.message || error?.message || "Deposit application failed.";
            this.state.message = `Deposit application failed: ${message}`;
            this.state.messageType = "error";
            cddsError("SCREEN", "application failed", { order: order.name, orderId, error: message });
        } finally {
            this.state.collecting = false;
        }
    },
});
