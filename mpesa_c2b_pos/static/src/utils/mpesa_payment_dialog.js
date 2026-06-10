/** @odoo-module */

import { MpesaPaymentScreen } from "../components/MpesaPaymentScreen/MpesaPaymentScreen";

export function isMpesaPaymentMethod(paymentMethod) {
    return Boolean(paymentMethod?.is_mpesa);
}

export async function openMpesaPaymentDialog(dialog, { orderAmount, posSessionId, context = "" }) {
    console.warn("[M-Pesa POS][dialog] opening validation", {
        context,
        orderAmount,
        posSessionId,
    });
    const result = await new Promise((resolve) => {
        let closeDialog;
        let resolved = false;
        const finish = (value) => {
            if (resolved) {
                return;
            }
            resolved = true;
            resolve(value);
        };

        closeDialog = dialog.add(
            MpesaPaymentScreen,
            {
                orderAmount: Number(orderAmount || 0),
                posSessionId,
                onPaymentDone: (mpesaRef, amount) => {
                    finish({ mpesaRef, amount });
                    closeDialog();
                },
                onPaymentCancel: () => {
                    finish(false);
                    closeDialog();
                },
            },
            { onClose: () => finish(false) }
        );
    });
    console.warn("[M-Pesa POS][dialog] validation closed", {
        context,
        result,
    });
    return result;
}
