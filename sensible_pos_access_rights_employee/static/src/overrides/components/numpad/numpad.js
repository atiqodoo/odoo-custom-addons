import { usePos } from "@point_of_sale/app/store/pos_hook";
import { Numpad } from "@point_of_sale/app/generic_components/numpad/numpad";
import { patch } from "@web/core/utils/patch";

patch(Numpad.prototype, {
    setup() {
        this.pos = usePos();
        super.setup();
    }
});
