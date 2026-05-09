/** @odoo-module */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { sblGuardedAction, sblAuthorizeAction, sblDebug } from "@sensible_pos_access_rights_employee/authorization/sbl_authorization";

patch(PosStore.prototype, {
    async sblAuthorizeAction(actionKey, options = {}) {
        return await sblAuthorizeAction(this, this.dialog, this.notification, actionKey, options);
    },

    async sblGuardedAction(actionKey, callback, options = {}) {
        return await sblGuardedAction(this, this.dialog, this.notification, actionKey, callback, options);
    },

    async pay() {
        return await this.sblGuardedAction("payment", () => super.pay(), { label: "Payment" });
    },

    async selectPartner() {
        if (this.sblBypassCustomerSelectionAuthorization) {
            return await super.selectPartner();
        }
        return await this.sblGuardedAction("select_customer", () => super.selectPartner(), {
            label: "Select Customer",
        });
    },

    async editPartner(partner) {
        return await this.sblGuardedAction(
            partner ? "edit_customer" : "create_customer",
            () => super.editPartner(partner),
            { label: partner ? "Edit Customer" : "Create Customer" }
        );
    },

    async onDeleteOrder(order) {
        return await this.sblGuardedAction("delete_order", () => super.onDeleteOrder(order), {
            label: "Delete Order",
        });
    },

    async cashMove() {
        return await this.sblGuardedAction("cash_in_out", () => super.cashMove(), {
            label: "Cash In / Out",
        });
    },

    async closeSession() {
        return await this.sblGuardedAction("close_register", () => super.closeSession(), {
            label: "Close Register",
        });
    },

    async closePos() {
        return await this.sblGuardedAction("backend_menu", () => super.closePos(), {
            label: "Backend",
        });
    },

    async selectPricelist(pricelist) {
        return await this.sblGuardedAction("pricelist", () => super.selectPricelist(pricelist), {
            label: "Pricelist",
        });
    },

    sblLogGuardState(actionKey) {
        sblDebug("guard state", {
            actionKey,
            cashierId: this.get_cashier?.()?.id,
            cashierName: this.get_cashier?.()?.name,
        });
    },
});
