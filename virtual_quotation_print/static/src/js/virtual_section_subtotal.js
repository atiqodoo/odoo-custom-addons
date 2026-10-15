/** @odoo-module **/

import { onMounted, onPatched } from "@odoo/owl";
import { formatMonetary } from "@web/views/fields/formatters";
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

function escapeSelector(value) {
    if (window.CSS?.escape) {
        return CSS.escape(value);
    }
    return String(value).replaceAll('"', '\\"');
}

function getLineAmount(record) {
    return Number(record.data.price_total ?? 0) || 0;
}

function formatAmount(record, amount) {
    return formatMonetary(amount, {
        data: record.data,
        field: record.fields?.price_total || record.fields?.section_subtotal,
    });
}

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => this.updateVirtualSectionSubtotals());
        onPatched(() => this.updateVirtualSectionSubtotals());
    },

    updateVirtualSectionSubtotals() {
        if (this.props.list?.resModel !== "virtual.quotation.line" || !this.tableRef?.el) {
            return;
        }

        const sectionTotals = new Map();
        let currentSection = null;
        for (const record of this.props.list.records) {
            if (record.data.display_type === "line_section") {
                currentSection = record;
                sectionTotals.set(record, 0);
            } else if (!record.data.display_type && currentSection) {
                sectionTotals.set(currentSection, sectionTotals.get(currentSection) + getLineAmount(record));
            }
        }

        for (const [section, total] of sectionTotals.entries()) {
            const row = this.tableRef.el.querySelector(
                `tbody tr.o_data_row[data-id="${escapeSelector(section.id)}"]`
            );
            if (!row) {
                continue;
            }

            const titleCell =
                row.querySelector("td.o_section_and_note_text_cell") ||
                row.querySelector('td[name="name"]') ||
                row.querySelector("td.o_data_cell:not(.o_handle_cell)");
            if (!titleCell) {
                continue;
            }

            let subtotal = titleCell.querySelector(".o_virtual_section_subtotal");
            if (!subtotal) {
                subtotal = document.createElement("span");
                subtotal.className = "o_virtual_section_subtotal fw-bold float-end";
                subtotal.title = "Section subtotal including taxes";
                titleCell.appendChild(subtotal);
            }
            subtotal.textContent = total ? `Subtotal ${formatAmount(section, total)}` : "";
        }
    },
});
