/**
 * MpesaPaymentScreen
 * Main OWL component for M-Pesa C2B payment in POS.
 *
 * State machine:
 *   idle → searching → found | not_found | error
 *   found → (cashier selects txn) → locked → confirmed | cancelled
 *
 * ALL business logic decisions live in the backend controller.
 * This component is responsible only for UI state and user interaction.
 */

import { Component, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { MpesaTransactionCard } from "../MpesaTransactionCard/MpesaTransactionCard";
import { MpesaManagerPin } from "../MpesaManagerPin/MpesaManagerPin";

export class MpesaPaymentScreen extends Component {
    static template   = "mpesa_c2b_pos.MpesaPaymentScreen";
    static components = { MpesaTransactionCard, MpesaManagerPin };
    static props = {
        orderAmount:  Number,
        posSessionId: Number,
        onPaymentDone:   Function,  // (mpesaRef, amount) → void
        onPaymentCancel: Function,  // () → void
        close: { type: Function, optional: true },
    };

    setup() {
        this.mpesaSvc   = useService("mpesa_validation");
        this.phoneInput = useRef("phoneInput");
        this.state = useState({
            // Phase control
            searching:  false,
            confirming: false,

            // Phone validation
            phoneValid: false,
            phoneError: "",

            // Search result
            status:       "idle",  // idle | not_found | found | already_used | error
            transactions: [],

            // Selection
            selectedTxnId: null,
            selectedTxn:   null,
            lockToken:     null,

            // Manager PIN dialog
            showPinDialog: false,
            pinReason:     "",
            pinApproved:   false,
        });
    }

    // ------------------------------------------------------------------
    // Computed
    // ------------------------------------------------------------------

    get formattedOrderAmount() {
        return `Ksh ${Number(this.props.orderAmount).toLocaleString("en-KE", {
            minimumFractionDigits: 2,
        })}`;
    }

    get canConfirm() {
        if (this.state.confirming || !this.state.selectedTxn) return false;
        return Boolean(this.state.lockToken);
    }

    get selectedApplyAmount() {
        if (!this.state.selectedTxn) return 0;
        return Math.min(
            Number(this.state.selectedTxn.amount || 0),
            Number(this.props.orderAmount || 0)
        );
    }

    get selectedRemainingDue() {
        return Math.max(Number(this.props.orderAmount || 0) - this.selectedApplyAmount, 0);
    }

    // ------------------------------------------------------------------
    // Phone input handlers
    // ------------------------------------------------------------------

    onPhoneInput(ev) {
        const val = ev.target.value.replace(/[^\d\s+]/g, "");
        const digits = val.replace(/\D/g, "");
        this.state.phoneValid  = digits.length >= 9 && digits.length <= 12;
        this.state.phoneError  = "";
        // Reset results when phone changes
        this.state.status       = "idle";
        this.state.transactions = [];
        this.state.selectedTxn  = null;
        this.state.selectedTxnId = null;
    }

    onPhoneKeyUp(ev) {
        if (ev.key === "Enter" && this.state.phoneValid) this.onSearch();
    }

    // ------------------------------------------------------------------
    // Search
    // ------------------------------------------------------------------

    async onSearch() {
        const phone = this.phoneInput.el?.value?.trim();
        if (!phone) return;

        this.state.searching    = true;
        this.state.status       = "idle";
        this.state.transactions = [];
        this.state.selectedTxn  = null;
        this.state.lockToken    = null;
        this.state.pinApproved  = false;

        const result = await this.mpesaSvc.validate(
            phone,
            this.props.orderAmount,
            this.props.posSessionId,
        );

        this.state.searching = false;

        if (result.status === "not_found") {
            this.state.status = "not_found";
        } else if (result.status === "found") {
            this.state.status       = "found";
            this.state.transactions = result.transactions;
            // Auto-select if only one result
            if (result.transactions.length === 1) {
                await this.onSelectTransaction(result.transactions[0]);
            }
        } else {
            this.state.status = "error";
        }
    }

    // ------------------------------------------------------------------
    // Transaction selection → lock
    // ------------------------------------------------------------------

    async onSelectTransaction(txn) {
        // Release previous lock if re-selecting
        if (this.state.selectedTxnId && this.state.selectedTxnId !== txn.id) {
            await this.mpesaSvc.release(this.state.selectedTxnId, this.props.posSessionId);
        }

        this.state.selectedTxnId = txn.id;
        this.state.selectedTxn   = txn;
        this.state.pinApproved   = false;
        this.state.status        = "found";

        // Lock the transaction
        const lockResult = await this.mpesaSvc.lock(txn.id, this.props.posSessionId);
        if (!lockResult.success) {
            this.state.status       = "already_used";
            this.state.selectedTxn  = null;
            this.state.selectedTxnId = null;
            return;
        }
        this.state.lockToken = lockResult.lock_token;
        this.state.status    = "found";

        this.state.pinReason = "";
    }

    // ------------------------------------------------------------------
    // Confirm payment
    // ------------------------------------------------------------------

    async onConfirm() {
        if (!this.canConfirm) return;

        const txn = this.state.selectedTxn;
        this.state.confirming = true;
        const result = await this.mpesaSvc.confirm(
            txn.id,
            this.state.lockToken,
            0, // pos_order_id: will be linked after Odoo creates the order
            this.selectedApplyAmount,
        );
        this.state.confirming = false;

        if (result.success) {
            this.props.onPaymentDone(result.mpesa_ref, result.applied_amount || this.selectedApplyAmount);
        } else {
            this.state.status = "error";
            console.error("[MpesaPaymentScreen] confirm failed:", result.error);
        }
    }

    // ------------------------------------------------------------------
    // Manager PIN callbacks
    // ------------------------------------------------------------------

    onManagerApproved() {
        this.state.showPinDialog = false;
        this.state.pinApproved   = true;
        // Proceed to confirm automatically
        this.onConfirm();
    }

    onPinCancelled() {
        this.state.showPinDialog = false;
    }

    // ------------------------------------------------------------------
    // Cancel
    // ------------------------------------------------------------------

    async onCancel() {
        if (this.state.selectedTxnId) {
            await this.mpesaSvc.release(this.state.selectedTxnId, this.props.posSessionId);
        }
        this.props.onPaymentCancel();
    }
}
