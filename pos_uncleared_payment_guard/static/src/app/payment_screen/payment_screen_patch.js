/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { UnclearedPaymentCapturePopup } from "@pos_uncleared_payment_guard/app/dialogs/uncleared_payment_capture_popup";
import { UnclearedPaymentNoticePopup } from "@pos_uncleared_payment_guard/app/dialogs/uncleared_payment_notice_popup";
import { upgLogger } from "@pos_uncleared_payment_guard/app/logger";
import {
    upgApplyCaptureToPaymentLine,
    upgGetDepositBankJournals,
    upgPaymentLineHasCapture,
} from "@pos_uncleared_payment_guard/app/services/uncleared_payment_capture_service";
import {
    upgGuardedPaymentLines,
    upgIsDepositOrSettleOrder,
    upgIsGuardedPaymentMethod,
} from "@pos_uncleared_payment_guard/app/services/uncleared_payment_service";

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        const guarded = upgIsGuardedPaymentMethod(this.pos, paymentMethod);
        const settlementOrder = upgIsDepositOrSettleOrder(this.currentOrder);
        upgLogger.warn(this.pos, "addNewPaymentLine", {
            method: paymentMethod?.name,
            methodId: paymentMethod?.id,
            guarded,
            settlementOrder,
            order: this.currentOrder?.name || this.currentOrder?.id,
        });

        const added = await super.addNewPaymentLine(...arguments);

        if (added && guarded && settlementOrder) {
            const paymentLine = this.currentOrder.get_selected_paymentline?.() || this.paymentLines.at(-1);
            const captured = await this._upgCaptureMappedPaymentDetails(paymentMethod, paymentLine);
            if (!captured) {
                if (paymentLine) {
                    this.currentOrder.remove_paymentline(paymentLine);
                }
                upgLogger.warn(this.pos, "mapped payment line removed because capture was cancelled", {
                    method: paymentMethod?.name,
                    paymentLineUuid: paymentLine?.uuid,
                });
                return false;
            }
            await this._upgShowUnclearedNotice(paymentMethod);
            this.currentOrder.upg_uncleared_notice_shown = true;
        }
        return added;
    },

    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        const settlementOrder = upgIsDepositOrSettleOrder(order);
        const guardedLines = upgGuardedPaymentLines(this.pos, order);
        upgLogger.warn(this.pos, "validateOrder", {
            order: order?.name || order?.id,
            settlementOrder,
            guardedLineCount: guardedLines.length,
            guardedLines: guardedLines.map((line) => ({
                method: line.payment_method_id?.name,
                amount: line.amount,
            })),
        });
        if (settlementOrder && guardedLines.length && !order.upg_uncleared_notice_shown) {
            const method = guardedLines[0].payment_method_id;
            if (!upgPaymentLineHasCapture(guardedLines[0])) {
                const captured = await this._upgCaptureMappedPaymentDetails(method, guardedLines[0]);
                if (!captured) {
                    upgLogger.warn(this.pos, "validateOrder blocked: mapped payment capture missing/cancelled", {
                        order: order?.name || order?.id,
                        method: method?.name,
                    });
                    return false;
                }
            }
            await this._upgShowUnclearedNotice(method);
            order.upg_uncleared_notice_shown = true;
        }
        return await super.validateOrder(...arguments);
    },

    async _upgCaptureMappedPaymentDetails(paymentMethod, paymentLine) {
        if (upgPaymentLineHasCapture(paymentLine)) {
            upgLogger.warn(this.pos, "capture already present on mapped payment line", {
                method: paymentMethod?.name,
                paymentLineUuid: paymentLine?.uuid,
            });
            return true;
        }
        const bankJournals = upgGetDepositBankJournals(this.pos);
        if (!bankJournals.length) {
            await this._upgShowUnclearedNotice({
                name: "No deposit bank journals configured. Ask an administrator to configure bank journals.",
            });
            return false;
        }
        let confirmed = false;
        const amount = paymentLine?.get_amount?.() ?? paymentLine?.amount;
        const amountText = amount !== undefined && amount !== null
            ? `${this.pos.currency?.symbol || ""} ${Number(amount || 0).toFixed(2)}`
            : "";
        await new Promise((resolve) => {
            this.dialog.add(
                UnclearedPaymentCapturePopup,
                {
                    title: "Cheque Deposit Details",
                    methodName: paymentMethod?.name || "Mapped Payment Method",
                    amountText,
                    bankJournals,
                    onConfirm: (payload) => {
                        upgApplyCaptureToPaymentLine(this.pos, paymentLine, payload);
                        confirmed = true;
                    },
                },
                { onClose: resolve }
            );
        });
        upgLogger.warn(this.pos, "mapped payment capture closed", {
            method: paymentMethod?.name,
            paymentLineUuid: paymentLine?.uuid,
            confirmed,
            hasCapture: upgPaymentLineHasCapture(paymentLine),
        });
        return confirmed && upgPaymentLineHasCapture(paymentLine);
    },

    async _upgShowUnclearedNotice(paymentMethod) {
        const line = this.currentOrder?.get_selected_paymentline?.();
        const amount = line?.get_amount?.() ?? line?.amount;
        const amountText = amount !== undefined && amount !== null
            ? `${this.pos.currency?.symbol || ""} ${Number(amount || 0).toFixed(2)}`
            : "";
        await new Promise((resolve) => {
            this.dialog.add(
                UnclearedPaymentNoticePopup,
                {
                    title: "Uncleared Payment Hold",
                    methodName: paymentMethod?.name || "Mapped Payment Method",
                    amountText,
                    body:
                        "This deposit or due-settlement payment is accepted, but it will not be usable as customer deposit or due clearance in future POS checkout until accounting reconciliation or authorized backend clearance.",
                },
                { onClose: resolve }
            );
        });
    },
});
