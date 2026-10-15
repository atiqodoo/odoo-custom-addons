/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PurchaseOrderLineProductField } from "@purchase_product_matrix/js/purchase_product_field";
import { vendorPriorityDebug, vendorPriorityLog } from "./vendor_priority_logger";


patch(PurchaseOrderLineProductField.prototype, {
    async _onProductTemplateUpdate() {
        const record = this.props.record;
        const root = record.model.root;
        const template = record.data.product_template_id;
        if (!template) {
            return await super._onProductTemplateUpdate(...arguments);
        }
        vendorPriorityLog("RFQ template selected", {
            orderId: root.resId || null,
            vendorId: root.data.partner_id?.[0] || null,
            templateId: template?.[0] || null,
            templateName: template?.[1] || null,
            priorityContext: record.context?.vendor_priority_search || false,
        });
        const result = await this.orm.call(
            "product.template",
            "get_single_product_variant",
            [template[0]],
        );
        if (result && result.product_id) {
            if (record.data.product_id?.[0] !== result.product_id) {
                await record.update({
                    product_id: [result.product_id, result.product_name],
                });
            }
            return;
        }
        return await super._onProductTemplateUpdate(...arguments);
    },

    _openMatrixConfigurator(jsonInfo, productTemplateId, editedCellAttributes) {
        const root = this.props.record.model.root;
        let matrixSummary = {};
        try {
            const parsed = JSON.parse(jsonInfo);
            matrixSummary = {
                headerCount: parsed.header?.length || 0,
                rowCount: parsed.matrix?.length || 0,
            };
        } catch (error) {
            matrixSummary = { parseError: error.message };
        }
        vendorPriorityDebug("RFQ variant matrix opened", {
            orderId: root.resId || null,
            vendorId: root.data.partner_id?.[0] || null,
            productTemplateId,
            editedCellAttributes,
            ...matrixSummary,
        });
        return super._openMatrixConfigurator(...arguments);
    },
});
