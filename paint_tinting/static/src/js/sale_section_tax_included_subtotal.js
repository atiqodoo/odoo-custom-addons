/** @odoo-module **/

import { onMounted, onPatched } from "@odoo/owl";
import { formatMonetary } from "@web/views/fields/formatters";
import { patch } from "@web/core/utils/patch";
import { SaleOrderLineListRenderer } from "@sale/js/sale_order_line_field/sale_order_line_field";

function escapeSelector(value) {
    if (window.CSS?.escape) {
        return CSS.escape(value);
    }
    return String(value).replaceAll('"', '\\"');
}

function getLineAmount(record) {
    return Number(record.data.price_total ?? record.data.price_subtotal ?? 0) || 0;
}

function formatAmount(record, amount) {
    return formatMonetary(amount, {
        data: record.data,
        field: record.fields?.price_total || record.fields?.price_subtotal,
    });
}

patch(SaleOrderLineListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => this.updateSaleSectionTaxIncludedSubtotals());
        onPatched(() => this.updateSaleSectionTaxIncludedSubtotals());
    },

    updateSaleSectionTaxIncludedSubtotals() {
        if (this.props.list?.resModel !== "sale.order.line" || !this.tableRef?.el) {
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
                row.querySelector(`td[name="${this.titleField}"]`) ||
                row.querySelector("td.o_data_cell:not(.o_handle_cell)");
            if (!titleCell) {
                continue;
            }

            let subtotal = titleCell.querySelector(".o_sale_section_tax_included_subtotal");
            if (!subtotal) {
                subtotal = document.createElement("span");
                subtotal.className = "o_sale_section_tax_included_subtotal fw-bold float-end";
                subtotal.title = "Section subtotal including taxes";
                titleCell.appendChild(subtotal);
            }
            subtotal.textContent = total ? `Subtotal ${formatAmount(section, total)}` : "";
        }
    },
});
