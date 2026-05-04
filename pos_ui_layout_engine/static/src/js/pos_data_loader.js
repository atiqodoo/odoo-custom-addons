/** @odoo-module */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";

const PREFIX = "[POS UI Layout Engine]";

function layoutConfigSnapshot(config) {
    return {
        id: config?.id,
        name: config?.name,
        ui_layout_mode: config?.ui_layout_mode,
        ui_density: config?.ui_density,
        ui_font_weight: config?.ui_font_weight,
        product_flex: config?.product_flex,
        order_flex: config?.order_flex,
        ui_action_button_placement: config?.ui_action_button_placement,
        ui_sort_products_by_sales: config?.ui_sort_products_by_sales,
        ui_sales_ranking_days: config?.ui_sales_ranking_days,
        ui_sales_ranking_scope: config?.ui_sales_ranking_scope,
    };
}

patch(PosStore.prototype, {
    async processServerData(...args) {
        console.groupCollapsed(`${PREFIX} processServerData`);
        try {
            await super.processServerData(...args);
            this.ui_config = this.config;
            console.info(`${PREFIX} POS config loaded`, layoutConfigSnapshot(this.config));
            if (
                this.config?.ui_layout_mode === undefined ||
                this.config?.ui_density === undefined ||
                this.config?.ui_font_weight === undefined ||
                this.config?.ui_action_button_placement === undefined ||
                this.config?.ui_sort_products_by_sales === undefined
            ) {
                console.warn(
                    `${PREFIX} Layout fields are missing from pos.config. Upgrade the module and reload POS assets.`,
                    this.config
                );
            }
        } catch (error) {
            console.error(`${PREFIX} Failed during POS config debug hook`, error);
            throw error;
        } finally {
            console.groupEnd();
        }
    },
});
