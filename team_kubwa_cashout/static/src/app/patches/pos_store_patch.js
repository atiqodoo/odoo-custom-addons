/** @odoo-module **/
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { tkLog, tkWarn, tkError } from "@team_kubwa_cashout/app/utils/team_kubwa_logger";
const AREA = "PosStore";
patch(PosStore.prototype, {
    async setup(...args) {
        await super.setup(...args);
        this.team_kubwa_cashouts = [];
        this.team_kubwa_config = { enabled: false, dealer_line: "", journals: [], receivable_configured: false, require_transaction_ref: false };
        await this.team_kubwa_fetch_config();
        await this.team_kubwa_fetch_cashouts();
    },
    async team_kubwa_fetch_config() {
        try {
            this.team_kubwa_config = await this.data.call("team.kubwa.cashout", "pos_get_config", [this.session?.id || false]);
            tkWarn(AREA, "Config loaded", this.team_kubwa_config);
        } catch (err) {
            tkError(AREA, "Failed to load config", err?.message || err);
        }
    },
    async team_kubwa_fetch_cashouts() {
        try {
            this.team_kubwa_cashouts = await this.data.call("team.kubwa.cashout", "pos_list_cashouts", [40]);
            tkLog(AREA, "Cashouts loaded", { count: this.team_kubwa_cashouts.length });
        } catch (err) {
            tkError(AREA, "Failed to load cashouts", err?.message || err);
            this.team_kubwa_cashouts = [];
        }
    },
    async team_kubwa_check_eligibility(payload) {
        tkWarn(AREA, "Checking eligibility", payload);
        return await this.data.call("team.kubwa.cashout", "pos_check_eligibility", [payload]);
    },
    async team_kubwa_pay_cashout(payload) {
        const result = await this.data.call("team.kubwa.cashout", "pos_create_paid_cashout", [payload]);
        await this.team_kubwa_fetch_cashouts();
        return result;
    },
    async team_kubwa_save_draft(payload) {
        const result = await this.data.call("team.kubwa.cashout", "pos_save_draft_cashout", [payload]);
        await this.team_kubwa_fetch_cashouts();
        return result;
    },
    async team_kubwa_resume_draft(draftId, payload = {}) {
        const result = await this.data.call("team.kubwa.cashout", "pos_resume_draft_cashout", [draftId, payload]);
        await this.team_kubwa_fetch_cashouts();
        return result;
    },
});

