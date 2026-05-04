/**
 * @module pos_cod/app/patches/payment_screen_patch
 *
 * Payment screen guard for COD orders.
 *
 * When a COD order is loaded into the payment screen for collection:
 *   - Blocks all credit payment methods (Customer Account).
 *     A cashier must never settle a COD order via credit — this would shift
 *     the receivable from the COD pool (COD AR account) to the credit pool
 *     (Trade AR) without proper accounting re-routing.
 *   - Logs the COD collection event for the Odoo console trail.
 *
 * Detection: order.is_cod === true && order.cod_state === "pending"
 * For normal (non-COD) orders: no change to payment screen behaviour.
 */

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { codWarn, codLog } from "@pos_cod/app/utils/cod_logger";

const COMPONENT = "PaymentScreen[COD]";

patch(PaymentScreen.prototype, {

    async addNewPaymentLine(paymentMethod) {
        const order = this.currentOrder;
        const isCodCollection = order?.is_cod && order?.cod_state === "pending";

        if (!isCodCollection) {
            return await super.addNewPaymentLine(...arguments);
        }

        codWarn(
            COMPONENT,
            "addNewPaymentLine",
            `COD collection order detected (${order.name}). Method: "${paymentMethod.name}".`,
        );

        if (paymentMethod.pcl_is_credit_method) {
            // BLOCK: COD AR and Trade AR are separate pools; clearing COD AR via a
            // credit-method payment would not produce the correct DR Cash / CR COD AR entry.
            codWarn(
                COMPONENT,
                "addNewPaymentLine",
                "BLOCKED — credit payment method not allowed for COD collection.",
                { method: paymentMethod.name, order: order.name },
            );

            this.dialog.add(AlertDialog, {
                title: "Not Allowed for COD",
                body:  (
                    `"${paymentMethod.name}" (Customer Account) cannot be used to `
                    + `settle a COD order. Please use cash, card, or bank transfer.`
                ),
            });

            return;
        }

        codLog(
            COMPONENT,
            "addNewPaymentLine",
            `COD collection — allowing non-credit method "${paymentMethod.name}".`,
        );

        return await super.addNewPaymentLine(...arguments);
    },

    onMounted() {
        if (typeof super.onMounted === "function") super.onMounted();

        const order = this.currentOrder;
        if (order?.is_cod && order?.cod_state === "pending") {
            codWarn(
                COMPONENT,
                "onMounted",
                `Payment screen opened in COD collection mode for order "${order.name}".`,
                {
                    amount_total: order.amount_total,
                    partner:      order.partner_id?.name || order.partner_id,
                },
            );
        }
    },

});
