/** @odoo-module */

/**
 * payment_screen.js
 *
 * 1. Forces the POS invoice toggle on during payment validation whenever a
 *    customer is selected.
 * 2. Blocks validation if the toggle cannot be verified as enabled, so the
 *    cashier must manually tick Invoice before continuing.
 * 3. Keeps the existing behavior that disables automatic invoice-PDF download
 *    when pos.config.allow_pdf_download is False.
 */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";

const LOGGER = "[pos_disable_invoice_download]";

function getOrderDebugInfo(order) {
    const partner = order?.get_partner?.();
    return {
        orderName: order?.name,
        orderUuid: order?.uuid,
        orderId: order?.id,
        partnerId: partner?.id || order?.partner_id?.id || order?.partner_id || false,
        partnerName: partner?.name || order?.partner_id?.name || false,
        toInvoice: order?.is_to_invoice?.(),
        rawToInvoice: order?.to_invoice,
        orderlineCount: order?.get_orderlines?.()?.length ?? order?.lines?.length,
        paymentCount: order?.payment_ids?.length,
        totalWithTax: order?.get_total_with_tax?.(),
        totalPaid: order?.get_total_paid?.(),
    };
}

console.info(`${LOGGER} payment_screen.js v3 loaded (invoice auto-tick validation guard)`);

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        console.debug(`${LOGGER} validateOrder() entered`, {
            isForceValidate,
            order: getOrderDebugInfo(this.currentOrder),
        });

        if (!this._ensureInvoiceEnabledForCustomerOrder()) {
            console.error(`${LOGGER} validateOrder() blocked: invoice toggle is still off`, {
                isForceValidate,
                order: getOrderDebugInfo(this.currentOrder),
            });
            this.dialog.add(AlertDialog, {
                title: _t("Invoice Required"),
                body: _t(
                    "A customer is selected, so this order must be invoiced. The system could not automatically tick Invoice. Please tick Invoice manually, then validate again."
                ),
            });
            return false;
        }

        console.debug(`${LOGGER} validateOrder() continuing`, {
            isForceValidate,
            order: getOrderDebugInfo(this.currentOrder),
        });
        return await super.validateOrder(...arguments);
    },

    _ensureInvoiceEnabledForCustomerOrder() {
        const order = this.currentOrder;
        const partner = order?.get_partner?.();

        if (!order) {
            console.warn(`${LOGGER} invoice guard skipped: no current order`);
            return true;
        }
        if (!partner) {
            console.debug(`${LOGGER} invoice guard skipped: no customer selected`, {
                order: getOrderDebugInfo(order),
            });
            return true;
        }
        if ((order.get_orderlines?.()?.length ?? order.lines?.length ?? 0) === 0) {
            console.info(`${LOGGER} invoice guard skipped: empty order exception`, {
                order: getOrderDebugInfo(order),
            });
            return true;
        }
        if (order.is_to_invoice?.()) {
            console.debug(`${LOGGER} invoice already enabled for customer order`, {
                order: getOrderDebugInfo(order),
            });
            return true;
        }

        console.warn(`${LOGGER} customer selected while invoice is off; forcing invoice on`, {
            order: getOrderDebugInfo(order),
        });

        try {
            if (typeof order.set_to_invoice === "function") {
                order.set_to_invoice(true);
            } else {
                order.to_invoice = true;
                console.warn(`${LOGGER} used fallback direct to_invoice assignment`);
            }
        } catch (error) {
            console.error(`${LOGGER} failed while forcing invoice toggle`, {
                error,
                order: getOrderDebugInfo(order),
            });
            return false;
        }

        const enabled = Boolean(order.is_to_invoice?.() ?? order.to_invoice);
        if (!enabled) {
            console.error(`${LOGGER} invoice toggle verification failed after force attempt`, {
                order: getOrderDebugInfo(order),
            });
            return false;
        }

        console.info(`${LOGGER} invoice toggle force-enabled successfully`, {
            order: getOrderDebugInfo(order),
        });
        return true;
    },

    /**
     * Block invoice PDF download when the POS config flag is off.
     * Falls through to the base implementation when allowed.
     */
    shouldDownloadInvoice() {
        console.debug(`${LOGGER} shouldDownloadInvoice()`, {
            allowPdfDownload: this.pos.config.allow_pdf_download,
            order: getOrderDebugInfo(this.currentOrder),
        });
        if (this.pos.config.allow_pdf_download === false) {
            console.info(`${LOGGER} invoice PDF download skipped by POS config`, {
                order: getOrderDebugInfo(this.currentOrder),
            });
            return false;
        }
        return super.shouldDownloadInvoice(...arguments);
    },
});
