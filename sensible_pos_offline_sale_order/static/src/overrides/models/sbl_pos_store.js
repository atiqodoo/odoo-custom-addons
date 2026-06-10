import { PosStore } from "@point_of_sale/app/store/pos_store";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";


patch(PosOrder.prototype, {
    serialize() {
        const data = super.serialize(...arguments);
        if (this.sbl_create_sale_order) {
            data.sbl_create_sale_order = true;
        }
        return data;
    },
});

patch(PosStore.prototype, {
    async createSaleOrder() {
        const currentOrder = this.get_order();
        const currentPartner = currentOrder.get_partner();
        if(!currentPartner) {
            return this.dialog.add(AlertDialog, {
                title: _t("Customer is Required"),
                body: _t("Please select a customer before creating a sale order."),
            });
        }
        if(!currentOrder.lines.length)  {
            return this.dialog.add(AlertDialog, {
                title: _t("No Products in Order"),
                body: _t("Please add products to the order before creating a sale order."),
            });
        }
        currentOrder.sbl_create_sale_order = true;
        this.addPendingOrder([currentOrder.id]);
        currentOrder.state = "paid";
        await this.syncAllOrders({ throw: true });
        return true;
    },
})
