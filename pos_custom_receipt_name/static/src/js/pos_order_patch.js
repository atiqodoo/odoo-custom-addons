/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { Orderline } from "@point_of_sale/app/generic_components/orderline/orderline";
import { patch } from "@web/core/utils/patch";

/**
 * Owl validates props strictly against the declared shape on Orderline.props.line.
 * Since we inject x_custom_pos_name into the receipt line data, we must register
 * it as an optional key on that shape, otherwise Owl throws and destroys the
 * receipt component before it renders.
 */
Orderline.props.line.shape.x_custom_pos_name = { type: String, optional: true };

/**
 * Injects x_custom_pos_name into each orderline's receipt data only.
 *
 * Why patch export_for_printing() and not getDisplayData():
 *   - getDisplayData() feeds BOTH the cart (OrderWidget) and the receipt.
 *   - export_for_printing() feeds ONLY the receipt (OrderReceipt via props.data).
 *   - Patching here means cart line data never gets x_custom_pos_name, so the
 *     QWeb template conditional falls back to productName in the cart while
 *     showing the custom name in the receipt.
 */
patch(PosOrder.prototype, {
    export_for_printing(baseUrl, headerData) {
        const result = super.export_for_printing(baseUrl, headerData);
        const sortedLines = this.getSortedOrderlines();

        result.orderlines = result.orderlines.map((lineData, index) => {
            const customName = sortedLines[index]?.product_id?.x_custom_pos_name;
            if (customName) {
                return { ...lineData, x_custom_pos_name: customName };
            }
            return lineData;
        });

        return result;
    },
});
