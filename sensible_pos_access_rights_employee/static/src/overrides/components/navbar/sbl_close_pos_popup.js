/** @odoo-module */

import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";
import { sblGuardedAction } from "@sensible_pos_access_rights_employee/authorization/sbl_authorization";

patch(ClosePosPopup.prototype, {
    async downloadSalesReport() {
        return await sblGuardedAction(
            this.pos,
            this.dialog,
            this.pos.notification,
            "daily_sale",
            () => super.downloadSalesReport(),
            { label: "Daily Sale" }
        );
    },
});
