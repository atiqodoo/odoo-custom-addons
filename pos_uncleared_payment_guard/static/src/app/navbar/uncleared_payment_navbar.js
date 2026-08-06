/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { usePos } from "@point_of_sale/app/store/pos_hook";

const LOG_PREFIX = "[UPG][Navbar]";

patch(PosStore.prototype, {
    async setup(...args) {
        await super.setup(...args);
        this.upg_uncleared_holds = [];
        this.upg_uncleared_loading = false;
        this.upg_uncleared_error = null;
        await this.upgFetchUnclearedHolds();
    },

    get upg_uncleared_hold_count() {
        return (this.upg_uncleared_holds || []).length;
    },

    async upgFetchUnclearedHolds() {
        const companyId = this.config?.company_id?.id || false;
        this.upg_uncleared_loading = true;
        this.upg_uncleared_error = null;
        console.warn(`${LOG_PREFIX} fetching pending uncleared holds`, { companyId });
        try {
            this.upg_uncleared_holds = await this.data.call(
                "pos.uncleared.payment.hold",
                "upg_pos_pending_holds",
                [companyId, 100],
            );
            console.warn(`${LOG_PREFIX} loaded pending uncleared holds`, this.upg_uncleared_holds);
        } catch (err) {
            this.upg_uncleared_holds = [];
            this.upg_uncleared_error = err?.message || "Failed to load uncleared payments.";
            console.error(`${LOG_PREFIX} failed to load pending uncleared holds`, err);
        } finally {
            this.upg_uncleared_loading = false;
        }
    },
});

export class UnclearedPaymentCardsDialog extends Component {
    static template = "pos_uncleared_payment_guard.UnclearedPaymentCardsDialog";
    static components = { Dialog };
    static props = {
        initialHolds: { type: Array, optional: true },
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.state = useState({
            holds: this.props.initialHolds || [],
            loading: false,
            error: null,
        });
    }

    async refresh() {
        this.state.loading = true;
        this.state.error = null;
        await this.pos.upgFetchUnclearedHolds();
        this.state.holds = this.pos.upg_uncleared_holds || [];
        this.state.error = this.pos.upg_uncleared_error;
        this.state.loading = false;
    }

    formatAmount(hold) {
        const amount = Number(hold.amount || 0).toFixed(2);
        const symbol = hold.currency_symbol || "";
        return hold.currency_position === "after" ? `${amount} ${symbol}` : `${symbol}${amount}`;
    }

    onClose() {
        this.props.close();
    }
}

export class UnclearedPaymentBanner extends Component {
    static template = "pos_uncleared_payment_guard.UnclearedPaymentBanner";
    static props = {};

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
    }

    get pendingCount() {
        return this.pos.upg_uncleared_hold_count || 0;
    }

    get isVisible() {
        return true;
    }

    get label() {
        const n = this.pendingCount;
        return `${n} uncleared payment${n !== 1 ? "s" : ""}`;
    }

    async onClick() {
        console.warn(`${LOG_PREFIX} banner clicked`);
        await this.pos.upgFetchUnclearedHolds();
        this.dialog.add(UnclearedPaymentCardsDialog, {
            initialHolds: this.pos.upg_uncleared_holds || [],
        });
    }
}

Navbar.components = { ...Navbar.components, UnclearedPaymentBanner };
