/** @odoo-module */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { upgLogger } from "@pos_uncleared_payment_guard/app/logger";

patch(PosStore.prototype, {
    async fetchPartnerCreditInfo(partner) {
        const result = await super.fetchPartnerCreditInfo(...arguments);
        if (!result) {
            return result;
        }
        upgLogger.table(this, "Partner balance adjustment", [{
            partner: result.partner_name || partner?.name,
            backend_total_due_after_hold: result.total_due,
            deposit_balance_after_hold: result.deposit_balance,
            session_incoming_usable: result.session_incoming_payments,
            uncleared_pending_total: result.upg_uncleared_pending_amount || 0,
            uncleared_pending_open_session: result.upg_uncleared_pending_open_session || 0,
            uncleared_pending_accounting_effect: result.upg_uncleared_pending_accounting_effect || 0,
            uncleared_hold_count: result.upg_uncleared_hold_count || 0,
        }]);
        return result;
    },
});
