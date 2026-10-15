/** @odoo-module **/
import { Component, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { makeActionAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { tkWarn, tkError } from "@team_kubwa_cashout/app/utils/team_kubwa_logger";
const AREA = "TeamKubwaCashoutScreen";
export class TeamKubwaCashoutScreen extends Component {
    static template = "team_kubwa_cashout.TeamKubwaCashoutScreen";
    static props = { isShown: { type: Boolean, optional: true } };
    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.autosaveTimer = null;
        this.state = useState({
            tab: "new", step: "fundi", loading: false, message: "", messageType: "info",
            fundiName: "", phone: "", requestedAmount: "", approvedAmount: "", transactionRef: "",
            crownMemberName: "", crownPointsRedeemed: "", otpReference: "", otpReceived: false, payoutJournalId: this.pos.team_kubwa_config?.default_payout_journal_id || "",
            eligibility: null, managerOverride: false, overrideReason: "", overrideNote: "", query: "",
            customerNotFound: false, identifiedCustomerId: false, identifiedCustomerName: "",
            draftId: false, autosaving: false, lastDraftSignature: "", authorizations: {},
        });
        onWillUnmount(() => {
            if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
            this.saveDraft({ silent: true, autosave: true });
        });
    }
    get config() { return this.pos.team_kubwa_config || {}; }
    get cashouts() {
        const query = (this.state.query || "").trim().toLowerCase();
        const records = this.pos.team_kubwa_cashouts || [];
        if (!query) return records;
        return records.filter((record) => [record.name, record.fundi_name, record.fundi_phone, record.transaction_ref, record.state, record.recovery_status].some((value) => String(value || "").toLowerCase().includes(query)));
    }
    get visibleCashouts() {
        if (this.state.tab === "drafts") return this.cashouts.filter((r) => this.isOpenDraft(r));
        if (this.state.tab === "paid") return this.cashouts.filter((r) => r.state === "paid");
        if (this.state.tab === "pending") return this.cashouts.filter((r) => r.state === "paid" && r.recovery_status === "pending_recovery");
        if (this.state.tab === "blocked") return this.cashouts.filter((r) => ["blocked", "cancelled"].includes(r.state));
        return this.cashouts;
    }
    get draftCount() { return this.cashouts.filter((r) => this.isOpenDraft(r)).length; }
    get paidCount() { return this.cashouts.filter((r) => r.state === "paid").length; }
    get pendingRecoveryCount() { return this.cashouts.filter((r) => r.state === "paid" && r.recovery_status === "pending_recovery").length; }
    get draftTotal() { return this.sumRecords(this.cashouts.filter((r) => this.isOpenDraft(r)), "requested_amount"); }
    get paidTotal() { return this.sumRecords(this.cashouts.filter((r) => r.state === "paid"), "paid_amount"); }
    get pendingRecoveryTotal() { return this.sumRecords(this.cashouts.filter((r) => r.state === "paid" && r.recovery_status === "pending_recovery"), "balance_amount"); }
    get requestedAmountNumber() { return Number(this.state.requestedAmount || 0); }
    get approvedAmountNumber() { return Number(this.state.approvedAmount || this.state.requestedAmount || 0); }
    get crownPointsRedeemedNumber() { return Number(this.state.crownPointsRedeemed || 0); }
    get hasFundiIdentifier() { return Boolean(this.state.phone.trim() || this.state.fundiName.trim()); }
    get hasFullFundiIdentifier() { return Boolean(this.state.phone.trim() && this.state.fundiName.trim()); }
    get hasOtpReference() { return Boolean(this.state.otpReference.trim()); }
    get hasCrownSmsDetails() { return Boolean(this.state.crownMemberName.trim()) && this.crownPointsRedeemedNumber > 0; }
    get hasIdentifiedCustomer() { return Boolean(this.state.identifiedCustomerId); }
    get identifiedCustomerLabel() { return this.state.identifiedCustomerName || _t("Not identified yet"); }
    get selectedPayoutJournal() { return (this.config.journals || []).find((journal) => Number(journal.id) === Number(this.state.payoutJournalId)); }
    get requiresTransactionRef() { return Boolean(this.config.require_transaction_ref && this.selectedPayoutJournal?.type === "bank"); }
    get canCheckEligibility() { return this.hasFundiIdentifier && this.requestedAmountNumber > 0 && !this.state.loading; }
    get canSaveDraft() { return this.hasIdentifiedCustomer && this.requestedAmountNumber > 0 && !this.state.autosaving; }
    get canContinueOtp() {
        const e = this.state.eligibility;
        if (!this.hasIdentifiedCustomer) return false;
        if (!e) return false;
        if (e.allowed && !e.requires_manager) return true;
        return this.state.managerOverride && this.state.overrideReason && !this.isFirstTimeGoodwillInvalid;
    }
    get isFirstTimeGoodwillInvalid() {
        const e = this.state.eligibility;
        if (this.state.overrideReason !== "first_time_goodwill" || !e) return false;
        return e.reason === "first_time_limit_exceeded" || !e.is_first_time;
    }
    get canPay() {
        const hasTransactionRef = !this.requiresTransactionRef || Boolean(this.state.transactionRef.trim());
        return this.canContinueOtp && this.state.otpReceived && this.hasOtpReference && this.hasCrownSmsDetails && this.approvedAmountNumber > 0 && this.approvedAmountNumber <= this.requestedAmountNumber && hasTransactionRef && this.state.payoutJournalId && this.config.receivable_configured && !this.state.loading;
    }
    formatCurrency(amount) {
        const symbol = this.pos.currency?.symbol || "KES ";
        return `${symbol}${Number(amount || 0).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    formatDate(dateValue) {
        if (!dateValue) return "";
        try { return new Date(String(dateValue).replace(" ", "T") + "Z").toLocaleString("en-GB"); } catch { return dateValue; }
    }
    sumRecords(records, field) {
        return records.reduce((total, record) => total + Number(record[field] || 0), 0);
    }
    currentCashierId() { return this.pos.get_cashier?.()?.id || false; }
    async authorizeTeamKubwa(actionKey, label) {
        const result = await this.pos.sblAuthorizeAction(actionKey, { label });
        if (!result) return false;
        const authorization = result === true
            ? { action_key: actionKey, unrestricted: true }
            : {
                action_key: actionKey,
                approved: Boolean(result.approved),
                supervisor_id: result.supervisor_id || false,
                authorization_log_id: result.authorization_log_id || false,
            };
        this.state.authorizations = { ...this.state.authorizations, [actionKey]: authorization };
        return authorization;
    }
    isOpenDraft(record) { return record && !["paid", "blocked", "cancelled"].includes(record.state); }
    draftStage(record) {
        return {
            draft: _t("Fundi"),
            eligibility_checked: _t("Eligibility"),
            waiting_otp: _t("OTP"),
            otp_shared: _t("OTP"),
            crown_confirmed: _t("Pay"),
        }[record?.state] || record?.state || "";
    }
    async setTab(tab) {
        if (this.state.tab === "new" && tab !== "new") {
            await this.saveDraft({ silent: true, autosave: true });
        }
        this.state.tab = tab;
    }
    async setStep(step) {
        this.state.step = step;
        await this.saveDraft({ silent: true, autosave: true });
    }
    async onBack() {
        await this.saveDraft({ silent: true, autosave: true });
        this.pos.showScreen("ProductScreen");
    }
    async onRefresh() {
        this.state.loading = true;
        await this.pos.team_kubwa_fetch_config();
        await this.pos.team_kubwa_fetch_cashouts();
        this.state.loading = false;
    }
    async checkEligibility() {
        if (!this.canCheckEligibility) return;
        if (!(await this.authorizeTeamKubwa("team_kubwa_check_eligibility", _t("Team Kubwa Check Eligibility")))) return;
        this.state.loading = true; this.state.message = "";
        try {
            const result = await this.pos.team_kubwa_check_eligibility({
                fundi_name: this.state.fundiName,
                phone: this.state.phone,
                requested_amount: this.requestedAmountNumber,
                cashier_id: this.currentCashierId(),
                authorizations: this.state.authorizations,
            });
            if (result.reason === "customer_not_found" || !result.partner_id) {
                this.state.customerNotFound = Boolean(result.requires_customer_creation);
                this.state.eligibility = null;
                this.state.identifiedCustomerId = false;
                this.state.identifiedCustomerName = "";
                this.state.managerOverride = false;
                this.state.overrideReason = "";
                this.state.overrideNote = "";
                this.state.crownMemberName = "";
                this.state.crownPointsRedeemed = "";
                this.state.otpReference = "";
                this.state.otpReceived = false;
                this.state.step = "fundi";
                this.state.messageType = "warning";
                this.state.message = result.message || _t("Enter both fundi name and phone number to verify or create the customer.");
                return;
            }
            this.state.customerNotFound = false;
            this.state.eligibility = result;
            this.state.identifiedCustomerId = result.partner_id || false;
            this.state.identifiedCustomerName = result.partner_name || "";
            if (!this.state.fundiName && result.partner_name) {
                this.state.fundiName = result.partner_name;
            }
            this.state.approvedAmount = this.state.requestedAmount;
            this.state.crownMemberName = "";
            this.state.crownPointsRedeemed = "";
            this.state.otpReference = "";
            this.state.otpReceived = false;
            this.state.step = "eligibility";
            this.state.messageType = result.allowed && !result.requires_manager ? "success" : "warning";
            this.state.message = result.message || _t("Eligibility checked.");
            tkWarn(AREA, "Eligibility result", result);
            await this.saveDraft({ silent: true, autosave: true });
        } catch (err) {
            this.state.messageType = "error";
            this.state.message = err?.data?.message || err?.message || _t("Eligibility check failed.");
            tkError(AREA, "Eligibility failed", this.state.message);
        } finally { this.state.loading = false; }
    }
    async createCustomer() {
        if (!(await this.authorizeTeamKubwa("team_kubwa_create_customer", _t("Team Kubwa Create Customer")))) return;
        if (!this.state.fundiName.trim() || !this.state.phone.trim()) {
            this.state.messageType = "warning";
            this.state.message = _t("Enter both fundi name and phone number before creating a customer.");
            return;
        }
        this.state.loading = true;
        try {
            const record = await makeActionAwaitable(
                this.pos.action,
                "point_of_sale.res_partner_action_edit_pos",
                {
                    props: { resId: undefined },
                    additionalContext: {
                        default_name: this.state.fundiName.trim(),
                        default_phone: this.state.phone.trim(),
                        default_mobile: this.state.phone.trim(),
                        default_customer_rank: 1,
                    },
                }
            );
            if (!record) {
                this.state.messageType = "warning";
                this.state.message = _t("Customer creation was cancelled.");
                return;
            }
            const partners = await this.pos.data.read("res.partner", record.config.resIds);
            const partner = partners?.[0];
            if (partner) {
                this.state.fundiName = partner.name || partner.display_name || this.state.fundiName;
                this.state.phone = partner.phone || partner.mobile || this.state.phone;
                this.state.identifiedCustomerId = partner.id || false;
                this.state.identifiedCustomerName = partner.display_name || partner.name || "";
                this.state.customerNotFound = false;
                this.state.messageType = "success";
                this.state.message = _t("Customer created. Checking eligibility...");
                this.state.loading = false;
                await this.checkEligibility();
            }
        } catch (err) {
            const message = err?.data?.message || err?.message || _t("Customer creation failed.");
            this.state.messageType = "error";
            this.state.message = message;
            tkError(AREA, "Customer creation failed", message);
        } finally {
            this.state.loading = false;
        }
    }
    async continueToOtp() {
        if (!this.canContinueOtp) {
            this.requireIdentifiedCustomer();
            return;
        }
        if (this.state.managerOverride && !(await this.authorizeTeamKubwa("team_kubwa_manager_override", _t("Team Kubwa Manager Override")))) return;
        if (!(await this.authorizeTeamKubwa("team_kubwa_continue_otp", _t("Team Kubwa Continue to OTP")))) return;
        this.state.step = "otp";
        this.state.message = _t("Ask fundi to complete the Crown redemption, then mark OTP received/shared.");
        this.state.messageType = "info";
        await this.saveDraft({ silent: true, autosave: true });
    }
    async markOtpReceived() {
        if (!this.hasOtpReference || !this.hasCrownSmsDetails) {
            this.state.message = _t("Enter the Crown member name, points redeemed, and OTP before marking it received.");
            this.state.messageType = "warning";
            return;
        }
        if (!(await this.authorizeTeamKubwa("team_kubwa_mark_otp", _t("Team Kubwa Mark OTP")))) return;
        this.state.otpReceived = true;
        this.state.message = _t("OTP marked as received/shared.");
        this.state.messageType = "success";
        await this.saveDraft({ silent: true, autosave: true });
    }
    async continueToConfirm() {
        if (!this.hasIdentifiedCustomer) {
            this.requireIdentifiedCustomer();
            return;
        }
        if (this.state.otpReceived && this.hasOtpReference && this.hasCrownSmsDetails) {
            if (!(await this.authorizeTeamKubwa("team_kubwa_continue_pay", _t("Team Kubwa Continue to Pay")))) return;
            this.state.step = "confirm";
            await this.saveDraft({ silent: true, autosave: true });
        }
    }
    async payCashout() {
        if (!this.canPay) {
            this.requireIdentifiedCustomer();
            return;
        }
        this.state.loading = true;
        try {
            if (this.state.managerOverride && !(await this.authorizeTeamKubwa("team_kubwa_manager_override", _t("Team Kubwa Manager Override")))) return;
            if (!(await this.authorizeTeamKubwa("team_kubwa_pay_post", _t("Team Kubwa Pay & Post")))) return;
            const result = await this.pos.team_kubwa_pay_cashout({
                fundi_name: this.state.fundiName, phone: this.state.phone, requested_amount: this.requestedAmountNumber,
                approved_amount: this.approvedAmountNumber, paid_amount: this.approvedAmountNumber,
                transaction_ref: this.state.transactionRef,
                crown_member_name: this.state.crownMemberName.trim(),
                crown_points_redeemed: this.crownPointsRedeemedNumber,
                otp_reference: this.state.otpReference.trim(), otp_received: this.state.otpReceived,
                payout_journal_id: Number(this.state.payoutJournalId), pos_session_id: this.pos.session?.id || false,
                manager_override: this.state.managerOverride, override_reason: this.state.overrideReason, override_note: this.state.overrideNote,
                draft_id: this.state.draftId || false,
                cashier_id: this.currentCashierId(),
                authorizations: this.state.authorizations,
            });
            this.state.message = `${result.name}: ${this.formatCurrency(result.paid_amount)} paid. Recovery pending.`;
            this.state.messageType = "success";
            this.notification.add(this.state.message, { type: "success" });
            this.resetForm();
            this.state.tab = "paid";
        } catch (err) {
            const message = err?.data?.message || err?.message || _t("Cash-out posting failed.");
            this.state.message = message; this.state.messageType = "error";
            this.dialog.add(AlertDialog, { title: _t("Team Kubwa Cash-Out Failed"), body: message });
            tkError(AREA, "Payment failed", message);
        } finally { this.state.loading = false; }
    }
    buildDraftPayload() {
        return {
            draft_id: this.state.draftId || false,
            step: this.state.step,
            fundi_name: this.state.fundiName,
            phone: this.state.phone,
            partner_id: this.state.identifiedCustomerId || false,
            requested_amount: this.requestedAmountNumber,
            approved_amount: this.approvedAmountNumber,
            transaction_ref: this.state.transactionRef,
            crown_member_name: this.state.crownMemberName.trim(),
            crown_points_redeemed: this.crownPointsRedeemedNumber,
            otp_reference: this.state.otpReference.trim(),
            otp_received: this.state.otpReceived,
            payout_journal_id: Number(this.state.payoutJournalId || 0),
            pos_session_id: this.pos.session?.id || false,
            manager_override: this.state.managerOverride,
            override_reason: this.state.overrideReason,
            override_note: this.state.overrideNote,
            eligibility: this.state.eligibility,
            cashier_id: this.currentCashierId(),
            authorizations: this.state.authorizations,
        };
    }
    async saveDraft({ silent = false, autosave = false } = {}) {
        if (!this.canSaveDraft && autosave) return false;
        if (!this.canSaveDraft) {
            this.requireIdentifiedCustomer();
            return false;
        }
        if (!autosave && !(await this.authorizeTeamKubwa("team_kubwa_save_draft", _t("Team Kubwa Save Draft")))) return false;
        const payload = this.buildDraftPayload();
        payload.autosave = autosave;
        const signature = JSON.stringify(payload);
        if (autosave && signature === this.state.lastDraftSignature) return false;
        this.state.autosaving = true;
        try {
            const draft = await this.pos.team_kubwa_save_draft(payload);
            this.state.draftId = draft.id;
            this.state.lastDraftSignature = JSON.stringify(this.buildDraftPayload());
            if (!silent) {
                this.state.message = `${draft.name}: ${_t("draft saved.")}`;
                this.state.messageType = "success";
            }
            return draft;
        } catch (err) {
            const message = err?.data?.message || err?.message || _t("Draft save failed.");
            if (!silent) {
                this.state.message = message;
                this.state.messageType = "error";
            }
            tkError(AREA, "Draft save failed", message);
            return false;
        } finally {
            this.state.autosaving = false;
        }
    }
    scheduleDraftAutosave() {
        if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
        this.autosaveTimer = setTimeout(() => {
            this.autosaveTimer = null;
            this.saveDraft({ silent: true, autosave: true });
        }, 1200);
    }
    async openDraft(record) {
        if (!this.isOpenDraft(record)) return;
        if (!(await this.authorizeTeamKubwa("team_kubwa_open_draft", _t("Team Kubwa Open Draft")))) return;
        this.state.loading = true;
        try {
            const draft = await this.pos.team_kubwa_resume_draft(record.id, {
                cashier_id: this.currentCashierId(),
                authorizations: this.state.authorizations,
            });
            this.state.draftId = draft.id;
            this.state.fundiName = draft.fundi_name || "";
            this.state.phone = draft.fundi_phone || "";
            this.state.requestedAmount = draft.requested_amount || "";
            this.state.approvedAmount = draft.approved_amount || draft.requested_amount || "";
            this.state.transactionRef = draft.transaction_ref || draft.crown_reference || "";
            this.state.crownMemberName = draft.crown_member_name || "";
            this.state.crownPointsRedeemed = draft.crown_points_redeemed || "";
            this.state.otpReference = draft.otp_reference || "";
            this.state.otpReceived = Boolean(draft.otp_received);
            this.state.payoutJournalId = draft.payout_journal_id || this.config.default_payout_journal_id || "";
            this.state.eligibility = draft.eligibility || null;
            this.state.managerOverride = Boolean(draft.manager_override);
            this.state.overrideReason = draft.override_reason || "";
            this.state.overrideNote = draft.override_note || "";
            this.state.identifiedCustomerId = draft.fundi_partner_id || false;
            this.state.identifiedCustomerName = draft.fundi_partner_name || draft.fundi_name || "";
            this.state.customerNotFound = false;
            this.state.step = { draft: "fundi", eligibility_checked: "eligibility", waiting_otp: "otp", otp_shared: "otp", crown_confirmed: "confirm" }[draft.state] || "fundi";
            this.state.tab = "new";
            this.state.message = `${draft.name}: ${_t("draft loaded.")}`;
            this.state.messageType = "info";
            this.state.lastDraftSignature = JSON.stringify(this.buildDraftPayload());
        } catch (err) {
            const message = err?.data?.message || err?.message || _t("Draft load failed.");
            this.state.message = message;
            this.state.messageType = "error";
            tkError(AREA, "Draft load failed", message);
        } finally {
            this.state.loading = false;
        }
    }
    requireIdentifiedCustomer() {
        if (this.hasIdentifiedCustomer) return false;
        this.state.step = "fundi";
        this.state.customerNotFound = this.hasFullFundiIdentifier;
        this.state.eligibility = null;
        this.state.managerOverride = false;
        this.state.overrideReason = "";
        this.state.overrideNote = "";
        this.state.otpReceived = false;
        this.state.messageType = "warning";
        this.state.message = _t("Customer not identified. Enter both fundi name and phone number, then verify or create the customer before continuing.");
        return true;
    }
    resetForm() {
        this.state.step = "fundi"; this.state.fundiName = ""; this.state.phone = ""; this.state.requestedAmount = "";
        this.state.approvedAmount = ""; this.state.transactionRef = ""; this.state.crownMemberName = ""; this.state.crownPointsRedeemed = "";
        this.state.otpReference = ""; this.state.otpReceived = false;
        this.state.eligibility = null; this.state.managerOverride = false; this.state.overrideReason = ""; this.state.overrideNote = "";
        this.state.customerNotFound = false; this.state.identifiedCustomerId = false; this.state.identifiedCustomerName = "";
        this.state.draftId = false; this.state.lastDraftSignature = ""; this.state.authorizations = {};
        this.state.payoutJournalId = this.config.default_payout_journal_id || "";
    }
}
registry.category("pos_screens").add("TeamKubwaCashoutScreen", TeamKubwaCashoutScreen);

