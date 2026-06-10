/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { onPatched } from "@odoo/owl";

const COLORANT_MODEL = "tint.wizard.colorant.line";

function sortFn(a, b) {
    const shotsA = a.data?.shots ?? 0;
    const shotsB = b.data?.shots ?? 0;
    if (shotsB !== shotsA) return shotsB - shotsA;
    const codeA = a.data?.colorant_code ?? "";
    const codeB = b.data?.colorant_code ?? "";
    return codeA < codeB ? -1 : codeA > codeB ? 1 : 0;
}

patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        onPatched(() => {
            const list = this.props.list;
            if (list?.resModel !== COLORANT_MODEL) return;
            const records = list.records;
            if (!records?.length) return;
            // Check if already sorted — if so, skip to avoid infinite re-render loop
            for (let i = 1; i < records.length; i++) {
                if (sortFn(records[i - 1], records[i]) > 0) {
                    records.sort(sortFn);
                    return;
                }
            }
        });
    },
});
