import { _t } from "@web/core/l10n/translation";
import { useBus, useService } from "@web/core/utils/hooks";
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { Numpad } from "@point_of_sale/app/generic_components/numpad/numpad";

// Named "NumberPopup" internally so number_buffer_service.js recognises it
// as a valid dialog overlay for keyboard input (overlay.props.subComponent.name check).
const DiscountTypePopup = class NumberPopup extends Component {
    static template = "pos_fixed_discount.DiscountTypePopup";
    static components = { Numpad, Dialog };
    static props = {
        title: { type: String, optional: true },
        startingValue: { type: [Number, String], optional: true },
        defaultType: String,
        getPayload: Function,
        close: Function,
    };
    static defaultProps = {
        title: _t("Discount"),
        startingValue: "",
    };

    setup() {
        this.numberBuffer = useService("number_buffer");
        this.numberBuffer.use({
            triggerAtEnter: () => this.confirm(),
            triggerAtEscape: () => this.cancel(),
        });
        this.state = useState({
            buffer: (this.props.startingValue ?? "").toString(),
            discountType: this.props.defaultType,
        });
        useBus(this.numberBuffer, "buffer-update", ({ detail: value }) => {
            this.state.buffer = value;
        });
    }

    setType(type) {
        this.state.discountType = type;
        // Clear the buffer when switching modes — a "10" percentage and a "10"
        // fixed amount mean completely different things.
        this.numberBuffer.reset();
    }

    confirm() {
        this.props.getPayload({ value: this.state.buffer, type: this.state.discountType });
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
};

export { DiscountTypePopup };
