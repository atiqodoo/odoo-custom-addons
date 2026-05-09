/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { sblDebug } from "@sensible_pos_access_rights_employee/authorization/sbl_authorization";

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        return await this.pos.sblGuardedAction(
            "payment_method",
            () => super.addNewPaymentLine(paymentMethod),
            { label: paymentMethod?.name || "Payment Method", paymentMethod }
        );
    },

    async toggleIsToInvoice() {
        return await this.pos.sblGuardedAction("payment_invoice", () => super.toggleIsToInvoice(), {
            label: "Invoice",
        });
    },

    async sblSelectPaymentCustomer() {
        return await this.pos.sblGuardedAction(
            "payment_customer",
            async () => {
                this.pos.sblBypassCustomerSelectionAuthorization = true;
                try {
                    return await this.pos.selectPartner();
                } finally {
                    this.pos.sblBypassCustomerSelectionAuthorization = false;
                }
            },
            { label: "Payment Customer" }
        );
    },

    async openCashbox() {
        return await this.pos.sblGuardedAction("open_cashbox", () => super.openCashbox(), {
            label: "Open Cashbox",
        });
    },

    async addTip() {
        return await this.pos.sblGuardedAction("payment_tip", () => super.addTip(), {
            label: "Tip",
        });
    },

    async toggleShippingDatePicker() {
        return await this.pos.sblGuardedAction(
            "payment_ship_later",
            () => super.toggleShippingDatePicker(),
            { label: "Ship Later" }
        );
    },

    async validateOrder(isForceValidate) {
        return await this.pos.sblGuardedAction(
            "payment_validate",
            () => super.validateOrder(isForceValidate),
            { label: "Validate Payment" }
        );
    },

    async updateSelectedPaymentline(amount = false) {
        if (this.sblPaymentAmountAuthorized) {
            return super.updateSelectedPaymentline(amount);
        }
        const allowed = await this.pos.sblAuthorizeAction("numpad", { label: "Payment Amount" });
        if (!allowed) {
            sblDebug("payment amount update blocked");
            return false;
        }
        this.sblPaymentAmountAuthorized = true;
        return super.updateSelectedPaymentline(amount);
    },
});
