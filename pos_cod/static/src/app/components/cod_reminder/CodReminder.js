import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { BarcodeReader } from "@point_of_sale/app/barcode/barcode_reader_service";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { formatPromise } from "@pos_cod/app/utils/cod_promise";
import { formatMonetary } from "@web/views/fields/formatters";

export const COD_REFRESH_EVENT = "pos-cod:collection-status-changed";

patch(BarcodeReader.prototype, {
    async _scan(...args) {
        if (!this.codPromiseReminderBlocked) return super._scan(...args);
    },
});

export class CodReminderModal extends Dialog {
    onEscape() {}
}

export class CodOverdueDialog extends Component {
    static template = "pos_cod.CodOverdueDialog";
    static components = { Dialog: CodReminderModal };
    static props = { close: Function, status: Object, load: Function };

    formatDate(value) {
        return formatPromise(value, this.props.status.timezone);
    }

    formatAmount(row) {
        return formatMonetary(row.open_amount, { currencyId: row.currency_id });
    }
}

// Mounted on every POS screen and device size; independent of the header badge.
export class CodReminder extends Component {
    static template = "pos_cod.CodReminder";
    static props = {};

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.barcode = useService("barcode_reader");
        this.status = useState({ rows: [], count: 0, offset: 0, limit: 40,
            loading: false, stale: false, checked_at: null,
            timezone: this.pos.config.cod_collection_timezone });
        this.refresh = this.refresh.bind(this);
        this.onWake = () => this.refresh();
        this.blockKeyboard = (event) => {
            if (!this.popupOpen) return;
            const inside = event.target.closest?.(".cod-overdue-reminder");
            const navigation = ["Tab", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"];
            const buttonActivation = ["Enter", " "].includes(event.key) && event.target.closest?.("button");
            if (!inside || (!navigation.includes(event.key) && !buttonActivation)) {
                event.preventDefault();
                event.stopImmediatePropagation();
            }
        };
        onMounted(() => {
            if (!this.pos.config.cod_enabled || !this.pos.config.cod_collection_promises_enabled) return;
            this.refresh();
            this.interval = window.setInterval(this.onWake, this.pos.config.cod_reminder_refresh_seconds * 1000);
            window.addEventListener("online", this.onWake);
            window.addEventListener("focus", this.onWake);
            window.addEventListener(COD_REFRESH_EVENT, this.onWake);
            window.addEventListener("keydown", this.blockKeyboard, true);
            window.addEventListener("keyup", this.blockKeyboard, true);
        });
        onWillUnmount(() => {
            this.destroyed = true;
            window.clearInterval(this.interval);
            window.clearTimeout(this.repeatTimer);
            window.clearTimeout(this.deadlineTimer);
            window.removeEventListener("online", this.onWake);
            window.removeEventListener("focus", this.onWake);
            window.removeEventListener(COD_REFRESH_EVENT, this.onWake);
            window.removeEventListener("keydown", this.blockKeyboard, true);
            window.removeEventListener("keyup", this.blockKeyboard, true);
            this.closeDialog?.();
            this.releaseBarcode();
        });
    }

    releaseBarcode() {
        if (this.barcodeHeld) {
            this.barcode.codPromiseReminderBlocked--;
            this.barcodeHeld = false;
        }
    }

    async refresh(offset = this.status.offset) {
        if (this.destroyed || this.status.loading) return;
        this.status.loading = true;
        try {
            const data = await this.pos.data.call("pos.order", "cod_overdue_reminders",
                [this.pos.config.id, offset, this.status.limit]);
            if (this.destroyed) return;
            Object.assign(this.status, data, { stale: false });
            // A payment on another terminal can remove the last page.
            if (data.count > 0 && data.offset >= data.count) {
                this.status.offset = 0;
            }
            window.clearTimeout(this.deadlineTimer);
            if (data.next_due_in_seconds !== null && data.next_due_in_seconds !== undefined) {
                // Browser timers accept a signed 32-bit millisecond delay.
                this.deadlineTimer = window.setTimeout(this.onWake,
                    Math.min(Math.max(data.next_due_in_seconds * 1000, 1), 2147483647));
            }
            if (data.count && !this.popupOpen && performance.now() >= (this.nextPopupAt || 0)) {
                // Avoid stacking above a payment terminal prompt or another modal.
                if (!document.querySelector(".o_dialog")) this.open();
            }
        } catch {
            if (!this.destroyed) this.status.stale = true;
        } finally {
            this.status.loading = false;
        }
    }

    open() {
        if (this.popupOpen || this.destroyed) return;
        this.popupOpen = true;
        this.barcode.codPromiseReminderBlocked = (this.barcode.codPromiseReminderBlocked || 0) + 1;
        this.barcodeHeld = true;
        try {
            this.closeDialog = this.dialog.add(CodOverdueDialog, {
                status: this.status, load: this.refresh,
            }, { onClose: () => {
                this.releaseBarcode();
                this.popupOpen = false;
                this.closeDialog = null;
                if (this.destroyed) return;
                const delay = this.pos.config.cod_reminder_interval_minutes * 60000;
                this.nextPopupAt = performance.now() + delay;
                window.clearTimeout(this.repeatTimer);
                this.repeatTimer = window.setTimeout(this.onWake, Math.min(delay, 2147483647));
            } });
        } catch (error) {
            this.popupOpen = false;
            this.releaseBarcode();
            throw error;
        }
    }
}

Navbar.components = { ...Navbar.components, CodReminder };
