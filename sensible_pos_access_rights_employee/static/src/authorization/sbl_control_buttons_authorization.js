/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { OrderlineNoteButton } from "@point_of_sale/app/screens/product_screen/control_buttons/customer_note_button/customer_note_button";
import { patch } from "@web/core/utils/patch";

patch(ControlButtons.prototype, {
    async clickFiscalPosition() {
        return await this.pos.sblGuardedAction(
            "fiscal_position",
            () => super.clickFiscalPosition(),
            { label: "Fiscal Position" }
        );
    },

    async clickPricelist() {
        return await this.pos.sblGuardedAction("pricelist", () => super.clickPricelist(), {
            label: "Pricelist",
        });
    },

    async clickRefund() {
        return await this.pos.sblGuardedAction("refund", () => super.clickRefund(), {
            label: "Refund",
        });
    },

    async clickDiscount() {
        const allowed = await this.pos.sblAuthorizeAction("global_discount", {
            label: "Global Discount",
        });
        if (!allowed) {
            return false;
        }
        this.sblGlobalDiscountAuthorizedUntil = Date.now() + 120000;
        return await super.clickDiscount();
    },

    async apply_discount(pc) {
        if (!(await this.sblEnsureGlobalDiscountAuthorized())) {
            return false;
        }
        return await super.apply_discount(pc);
    },

    async apply_fixed_discount(amount) {
        if (!(await this.sblEnsureGlobalDiscountAuthorized())) {
            return false;
        }
        return await super.apply_fixed_discount(amount);
    },

    async sblEnsureGlobalDiscountAuthorized() {
        if (
            this.sblGlobalDiscountAuthorizedUntil &&
            this.sblGlobalDiscountAuthorizedUntil >= Date.now()
        ) {
            this.sblGlobalDiscountAuthorizedUntil = false;
            return true;
        }
        return await this.pos.sblAuthorizeAction("global_discount", {
            label: "Global Discount",
        });
    },
});

patch(OrderlineNoteButton.prototype, {
    async onClick() {
        const actionKey = this.props.label === _t("General Note") ? "general_note" : "customer_note";
        return await this.pos.sblGuardedAction(actionKey, () => super.onClick(), {
            label: this.props.label || _t("Customer Note"),
        });
    },
});
