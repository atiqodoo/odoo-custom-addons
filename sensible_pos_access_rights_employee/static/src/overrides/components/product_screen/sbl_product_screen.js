import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { sblDebug } from "@sensible_pos_access_rights_employee/authorization/sbl_authorization";


patch(ProductScreen.prototype, {
    async onNumpadClick(buttonValue) {
        const actionByButton = {
            quantity: "qty",
            discount: "discount",
            price: "change_price",
            "-": "numpad_plus_minus",
        };
        let actionKey = actionByButton[buttonValue];

        if (this.pos.get_cashier()?.sbl_hide_pos_numpad && !this.sblProductNumpadAuthorized) {
            actionKey = "numpad";
        }

        if (actionKey && !(await this.pos.sblAuthorizeAction(actionKey))) {
            sblDebug("product numpad action blocked", { actionKey, buttonValue });
            return;
        }
        if (actionKey === "numpad") {
            this.sblProductNumpadAuthorized = true;
        }
        return super.onNumpadClick(buttonValue);
    },

    async displayAllControlPopup() {
        if (await this.pos.sblAuthorizeAction("actions_menu", { label: "Actions" })) {
            return super.displayAllControlPopup();
        }
        sblDebug("actions popup blocked");
        return false;
    },

    async onProductInfoClick(product) {
        const cashier = this.pos.get_cashier();
        const actionKey = cashier?.sbl_hide_pos_action_product_info
            ? "product_info"
            : "product_info_financials";
        return await this.pos.sblGuardedAction(
            actionKey,
            () => super.onProductInfoClick(product),
            { label: "Product Info" }
        );
    },
})
