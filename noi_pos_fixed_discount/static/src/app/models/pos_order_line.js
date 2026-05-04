/** @odoo-module */

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";
import { roundPrecision } from "@web/core/utils/numbers";
import { formatCurrency } from "@point_of_sale/app/models/utils/currency";

patch(PosOrderline.prototype, {
    setup(vals) {
        super.setup(vals);
        this.discount_fixed = vals.discount_fixed || 0;
    },

    set_fixed_discount(discount) {
        const parsed_discount =
            typeof discount === "number"
                ? discount
                : isNaN(parseFloat(discount))
                ? 0
                : parseFloat("" + discount);
        
        this.discount_fixed = Math.max(parsed_discount || 0, 0);
        this.order_id.recomputeOrderData();
        this.setDirty();
    },

    get_fixed_discount() {
        return this.discount_fixed || 0;
    },

    getFixedDiscountPerUnit() {
        const qty = this.get_quantity();
        if (qty && this.discount_fixed) {
            return this.discount_fixed / Math.abs(qty);
        }
        return 0;
    },

    get_base_price() {
        const rounding = this.currency.rounding;
        let unitPrice = this.get_unit_price() * (1 - this.get_discount() / 100);
        let totalPrice = unitPrice * this.get_quantity();
        
        if (this.discount_fixed) {
            totalPrice = totalPrice - this.discount_fixed;
        }

        return roundPrecision(totalPrice, rounding);
    },

    getDisplayData() {
        const result = super.getDisplayData();
        result.discount_fixed = this.get_fixed_discount();
        if (this.discount_fixed) {
            result.fixed_discount_str = formatCurrency(this.discount_fixed, this.currency);
        } else {
            result.fixed_discount_str = "";
        }
        return result;
    },

    prepareBaseLineForTaxesComputationExtraValues(extraValues = {}) {
        const result = super.prepareBaseLineForTaxesComputationExtraValues(extraValues);
        
        if (this.discount_fixed && !('discount_fixed' in extraValues)) {
            const fixedDiscountPerUnit = this.getFixedDiscountPerUnit();
            let currentPrice = result.price_unit || this.get_unit_price();
            currentPrice = currentPrice * (1 - (result.discount || this.get_discount()) / 100);
            currentPrice = currentPrice - fixedDiscountPerUnit;
            result.price_unit = currentPrice;
            result.discount = 0;
        }
        
        return result;
    },
});
