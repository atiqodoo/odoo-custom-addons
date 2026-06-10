/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { sblGuardedAction } from "@sensible_pos_access_rights_employee/authorization/sbl_authorization";
import {
    isMpesaPaymentMethod,
    openMpesaPaymentDialog,
} from "../utils/mpesa_payment_dialog";

patch(PosStore.prototype, {
    async settleCustomerDue(partner) {
        const updatedDue = await this.refreshTotalDueOfPartner(partner);
        const totalDue = Number(updatedDue ? updatedDue[0].total_due : partner.total_due || 0);
        const paymentMethods = this.config.payment_method_ids.filter(
            (method) => method.type !== "pay_later"
        );
        const selectionList = paymentMethods.map((paymentMethod) => ({
            id: paymentMethod.id,
            label: paymentMethod.name,
            item: paymentMethod,
        }));

        console.warn("[M-Pesa POS][settle-due] payment method popup", {
            partner: partner?.name,
            partnerId: partner?.id,
            totalDue,
            methods: paymentMethods.map((method) => ({
                id: method.id,
                name: method.name,
                is_mpesa: method.is_mpesa,
            })),
        });

        this.dialog.add(SelectionPopup, {
            title: _t("Select the payment method to settle the due"),
            list: selectionList,
            getPayload: async (selectedPaymentMethod) => {
                const allowed = await sblGuardedAction(
                    this,
                    this.dialog,
                    this.notification,
                    "deposit_settle_payment_method",
                    () => true,
                    {
                        label: _t("Deposit / Due Settlement: %s", selectedPaymentMethod.name),
                        paymentMethod: selectedPaymentMethod,
                    }
                );
                if (!allowed) {
                    console.warn("[M-Pesa POS][settle-due] authorization blocked", {
                        method: selectedPaymentMethod?.name,
                    });
                    return;
                }

                let amount = totalDue;
                let mpesaRef = "";
                if (isMpesaPaymentMethod(selectedPaymentMethod)) {
                    if (amount > 0) {
                        const mpesaResult = await openMpesaPaymentDialog(this.dialog, {
                            orderAmount: amount,
                            posSessionId: this.session.id,
                            context: "settle_due",
                        });
                        if (!mpesaResult) {
                            console.warn("[M-Pesa POS][settle-due] M-Pesa validation cancelled");
                            return;
                        }
                        amount = Number(mpesaResult.amount || amount);
                        mpesaRef = mpesaResult.mpesaRef;
                    } else {
                        amount = 0;
                        console.warn("[M-Pesa POS][deposit] M-Pesa deposit order prepared; validation waits for cashier amount", {
                            partner: partner?.name,
                            totalDue,
                        });
                    }
                }

                let newOrder;
                const emptyOrder = this.get_open_orders().find(
                    (order) =>
                        order.lines.length === 0 &&
                        order.payment_ids.length === 0 &&
                        (!order.partner || order.partner.id === partner.id)
                );
                if (emptyOrder) {
                    newOrder = emptyOrder;
                    this.set_order(newOrder);
                } else {
                    newOrder = this.add_new_order();
                }
                const payment = newOrder.add_paymentline(selectedPaymentMethod);
                newOrder.is_settling_account = true;
                payment.set_amount(amount);
                if (mpesaRef) {
                    payment.update({ mpesa_ref: mpesaRef });
                }
                newOrder.set_partner(partner);
                console.warn("[M-Pesa POS][settle-due] settlement payment line ready", {
                    order: newOrder.name || newOrder.uuid,
                    method: selectedPaymentMethod?.name,
                    amount,
                    mpesaRef,
                });
                this.showScreen("PaymentScreen", { orderUuid: this.selectedOrderUuid });
            },
        });
    },
});
