/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { FileModel } from "@web/core/file_viewer/file_model";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/** Read-only source files; ownership remains on the source document. */
export class TallyAttachments extends Component {
    static template = "purchase_net_price_compute.TallyAttachments";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ isSelecting: false });
    }

    get files() {
        return this.props.record.data[this.props.name].records.map((record) =>
            Object.assign(new FileModel(), record.data, { id: record.resId })
        );
    }

    get selectedIndex() {
        const selectedId = this.props.record.data.attachment_id?.[0];
        return this.files.findIndex((file) => file.id === selectedId);
    }

    async select(file) {
        if (this.state.isSelecting || file.id === this.props.record.data.attachment_id?.[0]) {
            return;
        }
        this.state.isSelecting = true;
        try {
            // Use the form's onchange flow to update the inline preview and PDF mark defaults.
            await this.props.record.update({ attachment_id: [file.id, file.displayName] });
        } finally {
            this.state.isSelecting = false;
        }
    }

    navigate(direction) {
        const files = this.files;
        if (!files.length) {
            return;
        }
        const index = this.selectedIndex;
        return this.select(files[index < 0 ? 0 : (index + direction + files.length) % files.length]);
    }
}

registry.category("fields").add("pnpc_tally_attachments", {
    component: TallyAttachments,
    supportedTypes: ["many2many"],
    isEmpty: () => false,
    relatedFields: [
        { name: "name", type: "char" },
        { name: "mimetype", type: "char" },
        { name: "type", type: "selection" },
        { name: "url", type: "char" },
    ],
});
