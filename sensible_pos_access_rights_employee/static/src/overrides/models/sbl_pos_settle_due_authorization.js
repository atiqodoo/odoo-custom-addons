/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { sblGuardedAction } from "@sensible_pos_access_rights_employee/authorization/sbl_authorization";

patch(PosStore.prototype, {
    async settleCustomerDue(partner) {
        const updatedDue = await this.refreshTotalDueOfPartner(partner);
        const totalDue = updatedDue ? updatedDue[0].total_due : partner.total_due;
        const paymentMethods = this.config.payment_method_ids.filter(
            (method) => method.type != "pay_later"
        );
        const selectionList = paymentMethods.map((paymentMethod) => ({
            id: paymentMethod.id,
            label: paymentMethod.name,
            item: paymentMethod,
        }));
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
                    return;
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
                payment.set_amount(totalDue);
                newOrder.set_partner(partner);
                this.showScreen("PaymentScreen", { orderUuid: this.selectedOrderUuid });
            },
        });
    },
});
