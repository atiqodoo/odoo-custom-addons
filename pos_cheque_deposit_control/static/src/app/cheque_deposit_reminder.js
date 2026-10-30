/** @odoo-module */

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { BarcodeReader } from "@point_of_sale/app/barcode/barcode_reader_service";

// A browser event avoids retaining component callbacks on the long-lived store.
const REFRESH_EVENT = "pcd:payments-synced";

// Scanners also dispatch directly to POS handlers, outside the modal's focus trap.
patch(BarcodeReader.prototype, {
    pcdPauseForBankingReminder() {
        this.pcdReminderBlocks = (this.pcdReminderBlocks || 0) + 1;
        let released = false;
        return () => {
            if (!released) {
                released = true;
                this.pcdReminderBlocks--;
            }
        };
    },
    async _scan(...args) {
        if (!this.pcdReminderBlocks) {
            return super._scan(...args);
        }
    },
});

patch(PosStore.prototype, {
    postSyncAllOrders(...args) {
        const result = super.postSyncAllOrders(...args);
        window.dispatchEvent(new Event(REFRESH_EVENT));
        return result;
    },
});

// Only this reminder ignores Escape. Other Odoo dialogs keep their normal behavior.
export class BankingReminderModal extends Dialog {
    onEscape() {}
}

export class ChequeDepositDialog extends Component {
    static template = "pos_cheque_deposit_control.ReminderDialog";
    static components = { Dialog: BankingReminderModal };
    static props = { close: Function };

    setup() {
        this.pos = usePos();
        this.state = useState({ rows: [], count: 0, offset: 0, limit: 40, loading: false, error: false });
        onMounted(() => this.load(0));
    }

    async load(offset) {
        if (this.state.loading) {
            return;
        }
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.pos.data.call("pos.uncleared.payment.hold", "pcd_pos_reminders",
                [this.pos.config.id, offset, this.state.limit]);
            Object.assign(this.state, data);
        } catch {
            this.state.error = true;
        } finally {
            this.state.loading = false;
        }
    }
}

export class ChequeDepositBanner extends Component {
    static template = "pos_cheque_deposit_control.ReminderBanner";
    static props = {};

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.barcodeReader = useService("barcode_reader");
        this.state = useState({ count: null, stale: false, checkedAt: null });
        this.popupReady = true;
        this.refresh = this.refresh.bind(this);
        onMounted(() => {
            if (!this.pos.config.pcd_enabled) {
                return;
            }
            this.refresh();
            this.timer = window.setInterval(this.refresh, this.pos.config.pcd_refresh_seconds * 1000);
            window.addEventListener("online", this.refresh);
            window.addEventListener(REFRESH_EVENT, this.refresh);
        });
        onWillUnmount(() => {
            this.destroyed = true;
            window.clearInterval(this.timer);
            window.clearTimeout(this.popupTimer);
            window.removeEventListener("online", this.refresh);
            window.removeEventListener(REFRESH_EVENT, this.refresh);
            this.closeDialog?.();
            this.releaseBarcode?.();
        });
    }

    get label() {
        if (this.state.count === null) {
            return this.state.stale ? _t("Cheque status unavailable") : _t("Checking cheques…");
        }
        return _t("%s cheque(s) due for banking", this.state.count);
    }

    async refresh() {
        if (this.loading || this.destroyed) {
            return;
        }
        this.loading = true;
        try {
            const data = await this.pos.data.call("pos.uncleared.payment.hold", "pcd_pos_reminders",
                [this.pos.config.id, 0, 1]);
            if (!this.destroyed) {
                Object.assign(this.state, { count: data.count, checkedAt: data.checked_at, stale: false });
                if (data.count > 0 && this.popupReady && !this.popupOpen) {
                    this.open(false);
                }
            }
        } catch {
            if (!this.destroyed) {
                // Keep the last known count. Failed checks must never show a false zero.
                this.state.stale = true;
            }
        } finally {
            this.loading = false;
        }
    }

    open(refresh = true) {
        if (this.destroyed || this.popupOpen || !this.pos.config.pcd_enabled) {
            return;
        }
        this.popupOpen = true;
        this.popupReady = false;
        window.clearTimeout(this.popupTimer);
        this.releaseBarcode = this.barcodeReader?.pcdPauseForBankingReminder();
        this.closeDialog = this.dialog.add(ChequeDepositDialog, {}, {
            onClose: () => {
                this.releaseBarcode?.();
                this.releaseBarcode = null;
                this.popupOpen = false;
                this.closeDialog = null;
                if (!this.destroyed) {
                    this.popupTimer = window.setTimeout(() => {
                        this.popupReady = true;
                        this.refresh();
                    }, this.pos.config.pcd_popup_interval_seconds * 1000);
                }
            },
        });
        if (refresh) {
            this.refresh();
        }
    }
}

Navbar.components = { ...Navbar.components, ChequeDepositBanner };
