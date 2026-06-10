/** @odoo-module */

import "@sensible_pos_access_rights_employee/authorization/sbl_cod_payment_method_registry";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";

function getCodPaymentMethod(pos, paymentMethodId) {
    const methodId = Number(paymentMethodId || 0);
    return (pos.models["pos.payment.method"]?.getAll?.() || []).find(
        (method) => Number(method.id) === methodId
    );
}

patch(PosStore.prototype, {
    async cod_collect_payment(orderId, paymentMethodId, amount, ...args) {
        const paymentMethod = getCodPaymentMethod(this, paymentMethodId);
        const allowed = await this.sblGuardedAction(
            "cod_payment_method",
            () => true,
            {
                label: _t("COD Payment Method: %s", paymentMethod?.name || _t("Payment Method")),
                paymentMethod,
            }
        );
        if (!allowed) {
            return {
                success: false,
                message: _t(
                    "%s requires supervisor authorization.",
                    paymentMethod?.name || _t("This COD payment method")
                ),
            };
        }
        return await super.cod_collect_payment(orderId, paymentMethodId, amount, ...args);
    },
});
