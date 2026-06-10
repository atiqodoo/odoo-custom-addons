/** @odoo-module **/

import { ListController } from "@web/views/list/list_controller";
import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";
import { onWillDestroy } from "@odoo/owl";

const MPESA_MODELS = new Set(["mpesa.transaction", "mpesa.sms.raw.log"]);
const REFRESH_MS = 5000;

patch(ListController.prototype, {
    setup() {
        super.setup();

        if (!MPESA_MODELS.has(this.props.resModel)) {
            return;
        }

        const timer = browser.setInterval(async () => {
            if (document.hidden || this.editedRecord) {
                return;
            }
            await this.model.load();
        }, REFRESH_MS);

        onWillDestroy(() => browser.clearInterval(timer));
    },
});
