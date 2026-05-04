/** @odoo-module */

/**
 * payment_screen.js
 *
 * Disables the automatic invoice-PDF download in POS when
 * pos.config.allow_pdf_download is False.
 *
 * Approach: override the single hook `shouldDownloadInvoice()` that the base
 * PaymentScreen._finalizeValidation() already calls.  This avoids duplicating
 * the entire _finalizeValidation method (which caused a missing-import bug
 * where RPCError / handleRPCError were referenced without being imported,
 * crashing payment finalization as "ReferenceError: WHCError is not defined").
 */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";

console.log("[pos_disable_invoice_download] payment_screen.js v2 loaded (shouldDownloadInvoice override)");

patch(PaymentScreen.prototype, {
    /**
     * Block invoice PDF download when the POS config flag is off.
     * Falls through to the base implementation (returns true) when allowed.
     *
     * Called by _finalizeValidation() immediately before attempting the
     * invoiceService.downloadPdf() call, so returning false here cleanly
     * skips the download without any duplicated error-handling logic.
     */
    shouldDownloadInvoice() {
        console.log("[pos_disable_invoice_download] shouldDownloadInvoice() — allow_pdf_download:", this.pos.config.allow_pdf_download);
        if (this.pos.config.allow_pdf_download === false) {
            return false;
        }
        return super.shouldDownloadInvoice(...arguments);
    },
});
