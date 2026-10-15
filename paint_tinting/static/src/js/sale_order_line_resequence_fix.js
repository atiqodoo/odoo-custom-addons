/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { StaticList } from "@web/model/relational_model/static_list";
import { ListRenderer } from "@web/views/list/list_renderer";

function isSaleOrderLineSequenceList(list) {
    return list.resModel === "sale.order.line" && list.handleField === "sequence";
}

patch(StaticList.prototype, {
    setup(config, data, options = {}) {
        super.setup(config, data, options);
        if (isSaleOrderLineSequenceList(this) && !this.config.orderBy.length) {
            this.config.orderBy = [
                { name: "sequence", asc: true },
                { name: "id", asc: true },
            ];
        }
    },

    canResequence() {
        if (isSaleOrderLineSequenceList(this)) {
            return true;
        }
        return super.canResequence();
    },
});

function isSaleOrderLineRenderer(renderer) {
    const list = renderer.props.list;
    return list.resModel === "sale.order.line" && list.handleField === "sequence";
}

patch(ListRenderer.prototype, {
    get canResequenceRows() {
        if (isSaleOrderLineRenderer(this)) {
            return true;
        }
        return super.canResequenceRows;
    },

    getRowClass(record) {
        const rowClass = super.getRowClass(record);
        if (isSaleOrderLineRenderer(this) && !rowClass.includes("o_row_draggable")) {
            return `${rowClass} o_row_draggable`.trim();
        }
        return rowClass;
    },
});
