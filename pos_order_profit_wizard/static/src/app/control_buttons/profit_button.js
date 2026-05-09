/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";
import { PosOrderProfitWizard } from "@pos_order_profit_wizard/app/components/profit_wizard/profit_wizard";

function getOrderlines(order) {
    return order?.getOrderlines?.() || order?.get_orderlines?.() || order?.orderlines || order?.lines || [];
}

patch(ControlButtons.prototype, {
    openProfitWizard() {
        const order = this.pos.get_order();
        const lines = getOrderlines(order).filter((line) => line?.get_product?.() || line?.product_id);
        if (!lines.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Order Profit"),
                body: _t("Add products to the order before opening the profit wizard."),
            });
            return;
        }
        this.dialog.add(PosOrderProfitWizard, { order });
    },
});
