/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class DocumentSourceLinks extends Component {
    static template = "document_source_links.SourceLinks";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ opening: false });
    }

    get links() {
        return this.props.record.data[this.props.name] || [];
    }

    async openSource(link) {
        const record = this.props.record;
        if (!record.resId || this.state.opening) {
            return;
        }
        this.state.opening = true;
        try {
            const action = await this.orm.call(record.resModel, "action_open_source_link",
                [[record.resId], link.model, link.id]);
            await this.action.doAction(action);
        } finally {
            this.state.opening = false;
        }
    }
}

registry.category("fields").add("document_source_links", {
    component: DocumentSourceLinks,
    supportedTypes: ["json"],
});
