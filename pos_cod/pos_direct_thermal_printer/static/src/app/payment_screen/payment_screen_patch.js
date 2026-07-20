/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { dtrpLogger } from "@pos_direct_thermal_printer/app/logger";
import {
    dtrpPrintOrder,
    dtrpReprintOrder,
} from "@pos_direct_thermal_printer/app/services/direct_printer_service";

function enabled(pos) {
    return Boolean(pos?.config?.dtrp_enabled && pos?.config?.dtrp_auto_print_on_validate);
}

function directPrinterEnabled(pos) {
    return Boolean(pos?.config?.dtrp_enabled);
}

patch(PaymentScreen.prototype, {
    async afterOrderValidation() {
        if (!enabled(this.pos)) {
            return await super.afterOrderValidation(...arguments);
        }
        const order = this.currentOrder;
        let printFailed = false;
        let printError = null;
        dtrpLogger.info(this.pos, "afterOrderValidation direct printer hook entered", {
            order: order?.name || order?.pos_reference || order?.uuid,
            skipReceiptScreen: this.pos.config.dtrp_skip_receipt_screen,
            fallbackToReceiptScreen: this.pos.config.dtrp_fallback_to_receipt_screen,
        }, order);
        try {
            await dtrpPrintOrder(this.pos, order);
        } catch (error) {
            printFailed = true;
            printError = error;
            dtrpLogger.error(this.pos, "direct receipt print failed after validation", {
                message: error?.message || String(error),
                stack: error?.stack || "",
            }, order);
            if (this.pos.config.dtrp_show_error_popup) {
                this.dialog.add(AlertDialog, {
                    title: _t("Direct Printer Error"),
                    body: _t(
                        "The receipt was validated, but direct thermal printing failed:\n%s",
                        error?.message || String(error)
                    ),
                });
            }
        }
        if (printFailed && this.pos.config.dtrp_fallback_to_receipt_screen) {
            dtrpLogger.warn(this.pos, "falling back to standard receipt flow", {
                message: printError?.message || String(printError),
            }, order);
            return await super.afterOrderValidation(...arguments);
        }
        let nextScreen = this.pos.config.dtrp_skip_receipt_screen ? "ProductScreen" : "ReceiptScreen";
        if (nextScreen === "ProductScreen") {
            order.set_screen_data({ name: "" });
            this.selectNextOrder();
        }
        this.pos.showScreen(nextScreen);
        if (!this.pos.config.module_pos_restaurant) {
            this.pos.checkPreparationStateAndSentOrderInPreparation(order);
        }
        dtrpLogger.info(this.pos, "afterOrderValidation direct printer hook completed", {
            nextScreen,
            printFailed,
        }, order);
    },
});

patch(TicketScreen.prototype, {
    async print(order) {
        if (!directPrinterEnabled(this.pos)) {
            return await super.print(...arguments);
        }

        dtrpLogger.info(this.pos, "TicketScreen custom thermal reprint started", {
            order: order?.name || order?.pos_reference || order?.uuid || order?.id,
            mode: this.pos.config.dtrp_connection_mode,
            bridgeUrl: this.pos.config.dtrp_bridge_url,
        }, order);

        try {
            const result = await dtrpReprintOrder(this.pos, order);
            if (typeof order?.id === "number" && result?.ok) {
                await this.pos.data.write("pos.order", [order.id], { nb_print: order.nb_print });
            }
            dtrpLogger.info(this.pos, "TicketScreen custom thermal reprint completed", {
                order: order?.name || order?.pos_reference || order?.uuid || order?.id,
                copies: result?.copies || 0,
                nbPrint: order?.nb_print,
            }, order);
            return true;
        } catch (error) {
            dtrpLogger.error(this.pos, "TicketScreen custom thermal reprint failed", {
                order: order?.name || order?.pos_reference || order?.uuid || order?.id,
                message: error?.message || String(error),
                stack: error?.stack || "",
            }, order);

            if (this.pos.config.dtrp_fallback_to_receipt_screen) {
                dtrpLogger.warn(this.pos, "TicketScreen falling back to standard receipt print", {
                    message: error?.message || String(error),
                }, order);
                return await super.print(...arguments);
            }

            if (this.pos.config.dtrp_show_error_popup) {
                this.dialog.add(AlertDialog, {
                    title: _t("Direct Printer Error"),
                    body: _t(
                        "The custom thermal receipt could not be printed. Check that the local print bridge is running on this POS till PC.\n\n%s",
                        error?.message || String(error)
                    ),
                });
            }
            return false;
        }
    },
});
