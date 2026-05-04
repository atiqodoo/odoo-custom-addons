/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";

const PREFIX = "[POS UI Layout Engine]";
const VALID_LAYOUTS = new Set(["default", "wide", "split"]);
const VALID_DENSITIES = new Set(["compact", "normal", "large"]);
const VALID_WEIGHTS = new Set(["normal", "bold"]);

function clampFlex(value, fallback) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
        return fallback;
    }
    return Math.min(Math.max(parsed, 0.5), 10);
}

function sanitizeConfig(config = {}) {
    const layout = VALID_LAYOUTS.has(config.ui_layout_mode) ? config.ui_layout_mode : "default";
    const density = VALID_DENSITIES.has(config.ui_density) ? config.ui_density : "normal";
    const weight = VALID_WEIGHTS.has(config.ui_font_weight) ? config.ui_font_weight : "normal";
    return {
        layout,
        density,
        weight,
        productFlex: clampFlex(config.product_flex, 3),
        orderFlex: clampFlex(config.order_flex, 2),
    };
}

patch(ProductScreen.prototype, {
    setup(...args) {
        super.setup(...args);
        console.info(`${PREFIX} ProductScreen patch active`, this.uiLayoutEngineDebugSnapshot);
    },

    get uiLayoutEngineConfig() {
        return sanitizeConfig(this.pos?.config || this.pos?.ui_config || {});
    },

    get uiLayoutEngineClasses() {
        const config = this.uiLayoutEngineConfig;
        const classes = [
            `ui-layout-${config.layout}`,
            `density-${config.density}`,
            `font-${config.weight}`,
        ].join(" ");
        console.debug(`${PREFIX} ProductScreen classes`, classes, config);
        return classes;
    },

    get uiLayoutEngineProductFlexStyle() {
        const config = this.uiLayoutEngineConfig;
        if (this.ui?.isSmall) {
            return "";
        }
        return [
            `flex: ${config.productFlex} 1 0% !important`,
            "width: auto !important",
            "max-width: none !important",
            "min-width: 0",
        ].join("; ");
    },

    get uiLayoutEngineOrderFlexStyle() {
        const config = this.uiLayoutEngineConfig;
        if (this.ui?.isSmall) {
            return "";
        }
        return [
            `flex: ${config.orderFlex} 1 0% !important`,
            "width: auto !important",
            "max-width: none !important",
            "min-width: 0",
        ].join("; ");
    },

    get uiLayoutEngineDebugSnapshot() {
        const config = this.uiLayoutEngineConfig;
        return {
            raw: {
                ui_layout_mode: this.pos?.config?.ui_layout_mode,
                ui_density: this.pos?.config?.ui_density,
                ui_font_weight: this.pos?.config?.ui_font_weight,
                product_flex: this.pos?.config?.product_flex,
                order_flex: this.pos?.config?.order_flex,
                ui_action_button_placement: this.pos?.config?.ui_action_button_placement,
            },
            sanitized: config,
            productStyle: this.uiLayoutEngineProductFlexStyle,
            orderStyle: this.uiLayoutEngineOrderFlexStyle,
        };
    },
});

patch(ControlButtons.prototype, {
    get uiActionButtonPlacement() {
        return this.pos?.config?.ui_action_button_placement || "popup";
    },

    get uiActionButtonsPromoted() {
        return ["core_bar", "all_bar"].includes(this.uiActionButtonPlacement);
    },

    get uiAllKnownActionButtonsPromoted() {
        return this.uiActionButtonPlacement === "all_bar";
    },

    get uiActionButtonClass() {
        return "btn btn-light btn-lg lh-lg pos-ui-action-bar-button";
    },

    uiCanUseMethod(methodName) {
        return typeof this[methodName] === "function";
    },

    uiLogPromotedAction(actionName) {
        console.debug(`${PREFIX} promoted action clicked`, {
            actionName,
            placement: this.uiActionButtonPlacement,
        });
    },
});
