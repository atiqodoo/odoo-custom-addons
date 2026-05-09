/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { CodOrdersScreen } from "@pos_cod/app/screens/cod_orders_screen/CodOrdersScreen";
import { patch } from "@web/core/utils/patch";
import { sblDebug } from "@sensible_pos_access_rights_employee/authorization/sbl_authorization";

patch(ProductScreen.prototype, {
    async onCodButtonClick() {
        return await this.pos.sblGuardedAction(
            "cod_dispatch",
            () => super.onCodButtonClick(),
            { label: "COD" }
        );
    },
});

patch(CodOrdersScreen.prototype, {
    async onReceivePayment(order) {
        return await this.sblGuardCodAction(
            "cod_pay_all",
            "COD Full Pay",
            () => super.onReceivePayment(order)
        );
    },

    async onReceivePartial(order) {
        return await this.sblGuardCodAction(
            "cod_pay_partial",
            "COD Partial Pay",
            () => super.onReceivePartial(order)
        );
    },

    async onReturn(order) {
        return await this.sblGuardCodAction(
            "cod_return_all",
            "COD Return All",
            () => super.onReturn(order)
        );
    },

    async onPartialReturn(order) {
        return await this.sblGuardCodAction(
            "cod_return_partial",
            "COD Partial Return",
            () => super.onPartialReturn(order)
        );
    },

    async sblGuardCodAction(actionKey, label, callback) {
        const allowed = await this.pos.sblAuthorizeAction(actionKey, { label });
        if (!allowed) {
            this.state.message = `${label} requires supervisor authorization.`;
            this.state.messageType = "error";
            sblDebug("COD action blocked", {
                actionKey,
                label,
                cashierId: this.pos.get_cashier?.()?.id,
            });
            return false;
        }
        return await callback();
    },
});
