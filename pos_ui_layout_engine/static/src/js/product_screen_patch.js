/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";
import { parseUTCString } from "@point_of_sale/utils";
import { dtrpReprintOrder } from "@pos_direct_thermal_printer/app/services/direct_printer_service";
import { dtrpLogger } from "@pos_direct_thermal_printer/app/logger";

const PREFIX = "[POS UI Layout Engine]";
const VALID_LAYOUTS = new Set(["default", "wide", "split"]);
const VALID_DENSITIES = new Set(["compact", "normal", "large"]);
const VALID_WEIGHTS = new Set(["normal", "bold"]);
const DEFAULT_BACKGROUND_COLOR = "#e9ecef";

function clampFlex(value, fallback) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
        return fallback;
    }
    return Math.min(Math.max(parsed, 0.5), 10);
}

function sanitizeBackgroundColor(value) {
    const color = String(value || "").trim();
    if (!color) {
        return DEFAULT_BACKGROUND_COLOR;
    }
    const lowered = color.toLowerCase();
    if (/[;{}<>]/.test(color) || lowered.includes("url(") || lowered.includes("var(")) {
        return DEFAULT_BACKGROUND_COLOR;
    }
    if (window.CSS?.supports?.("background-color", color)) {
        return color;
    }
    return DEFAULT_BACKGROUND_COLOR;
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
        backgroundColor: sanitizeBackgroundColor(config.ui_background_color),
    };
}

function newestOrder(orders = []) {
    return orders.reduce((latest, current) => {
        if (!latest) {
            return current;
        }
        const latestDate = Date.parse(latest.write_date || latest.date_order || latest.create_date || 0);
        const currentDate = Date.parse(current.write_date || current.date_order || current.create_date || 0);
        if (Number.isFinite(currentDate) && currentDate !== latestDate) {
            return currentDate > latestDate ? current : latest;
        }
        return (current.id || 0) > (latest.id || 0) ? current : latest;
    }, null);
}

function kenyanDateTime(value) {
    if (!value) {
        return "";
    }
    try {
        return parseUTCString(value).setZone("default").toFormat("dd/MM/yyyy HH:mm:ss");
    } catch {
        return String(value || "");
    }
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

    get uiLayoutEngineScreenStyle() {
        const config = this.uiLayoutEngineConfig;
        return `--pos-ui-background-color: ${config.backgroundColor}`;
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
                ui_background_color: this.pos?.config?.ui_background_color,
            },
            sanitized: config,
            screenStyle: this.uiLayoutEngineScreenStyle,
            productStyle: this.uiLayoutEngineProductFlexStyle,
            orderStyle: this.uiLayoutEngineOrderFlexStyle,
        };
    },
});

patch(TicketScreen.prototype, {
    getDate(order) {
        return kenyanDateTime(order?.date_order);
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

    async clickPrint() {
        const allOrders = this.pos.models?.["pos.order"]?.getAll?.() || [];
        const completedOrders = allOrders.filter((order) => order.state && !["draft", "cancel"].includes(order.state));
        let latestOrder = newestOrder(completedOrders);

        if (!latestOrder) {
            dtrpLogger.warn(this.pos, `${PREFIX} no completed orders in local cache; loading latest synced order`, {
                configId: this.pos.config.id,
            });
            const response = await this.pos.data.call(
                "pos.order",
                "search_paid_order_ids",
                [],
                {
                    config_id: this.pos.config.id,
                    domain: [],
                    limit: 1,
                    offset: 0,
                }
            );
            const latestOrderId = response?.ordersInfo?.[0]?.[0];
            if (latestOrderId) {
                await this.pos.data.read("pos.order", [latestOrderId]);
                latestOrder = this.pos.models?.["pos.order"]?.get?.(latestOrderId) || null;
            }
        }

        if (!latestOrder) {
            dtrpLogger.warn(this.pos, `${PREFIX} could not determine latest order to print`);
            return;
        }

        dtrpLogger.info(this.pos, `${PREFIX} reprintReceipt triggered for latest order`, {
            orderId: latestOrder.id,
            orderName: latestOrder.name,
            state: latestOrder.state,
        });

        try {
            const result = await dtrpReprintOrder(this.pos, latestOrder);
            if (typeof latestOrder.id === "number" && result?.ok) {
                await this.pos.data.write("pos.order", [latestOrder.id], { nb_print: latestOrder.nb_print });
            }
            dtrpLogger.info(this.pos, `${PREFIX} reprint completed successfully`, {
                orderId: latestOrder.id,
                orderName: latestOrder.name,
                nbPrint: latestOrder.nb_print,
            });
        } catch (error) {
            dtrpLogger.error(this.pos, `${PREFIX} reprint failed`, {
                message: error?.message || String(error),
                stack: error?.stack || "",
            });
        }
    },
});
