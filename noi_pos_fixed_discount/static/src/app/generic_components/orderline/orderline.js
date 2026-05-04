/** @odoo-module */

import { Orderline } from "@point_of_sale/app/generic_components/orderline/orderline";
import { patch } from "@web/core/utils/patch";

patch(Orderline, {
    props: {
        ...Orderline.props,
        line: {
            type: Object,
            shape: {
                ...Orderline.props.line.shape,
                discount_fixed: { type: Number, optional: true },
                fixed_discount_str: { type: String, optional: true },
            },
        },
    },
});
