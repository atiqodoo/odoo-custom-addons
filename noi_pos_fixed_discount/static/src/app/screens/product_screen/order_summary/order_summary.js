/** @odoo-module */

import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";

patch(OrderSummary.prototype, {
    async onClickDiscount(line) {
        const selectionList = [
            { id: 1, label: _t("Percentage Discount (%)"), item: "percent", isSelected: true },
            { id: 2, label: _t("Fixed Discount (Amount)"), item: "fixed", isSelected: false },
        ];

        const selectedType = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Select Discount Type"),
            list: selectionList,
        });

        if (!selectedType) {
            return;
        }

        if (selectedType === "percent") {
            this.numberBuffer.reset();
            const inputNumber = await makeAwaitable(this.dialog, NumberPopup, {
                startingValue: line.get_discount() || 0,
                title: _t("Set Percentage Discount (%)"),
            });
            if (inputNumber !== false && inputNumber !== null) {
                await this.pos.setDiscountFromUI(line, inputNumber);
            }
        } else if (selectedType === "fixed") {
            this.numberBuffer.reset();
            const inputNumber = await makeAwaitable(this.dialog, NumberPopup, {
                startingValue: line.get_fixed_discount() || 0,
                title: _t("Set Fixed Discount Amount"),
            });
            if (inputNumber !== false && inputNumber !== null) {
                line.set_fixed_discount(inputNumber);
            }
        }
    },
});
