// Run with: node --test custom_addon/pos_cheque_deposit_control/tests/reminder_client.test.mjs
// Execute the actual client methods with small service/lifecycle stubs; no browser required.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../static/src/app/cheque_deposit_reminder.js", import.meta.url), "utf8")
    .replace(/^import .*;\r?\n/gm, "")
    .replaceAll("export class ", "class ");

function harness({ enabled = true, call = async () => ({ count: 2, checked_at: "2026-10-28 09:00:00" }) } = {}) {
    const mounted = [], unmounted = [], intervals = new Map(), timeouts = new Map(), dialogs = [];
    const events = new EventTarget();
    let calls = 0;
    const pos = { config: { id: 7, pcd_enabled: enabled, pcd_refresh_seconds: 90, pcd_popup_interval_seconds: 180 }, data: {
        call: (...args) => { calls++; return call(...args); },
    } };
    const browser = Object.assign(events, {
        setInterval: (callback, ms) => { intervals.set(1, { callback, ms }); return 1; },
        clearInterval: (id) => intervals.delete(id),
        setTimeout: (callback, ms) => { timeouts.set(1, { callback, ms }); return 1; },
        clearTimeout: (id) => timeouts.delete(id),
    });
    const dialogService = {
        add: (component, props, options) => {
            const dialog = { component, props, closed: false };
            dialog.close = () => {
                if (!dialog.closed) {
                    dialog.closed = true;
                    options.onClose();
                }
            };
            dialogs.push(dialog);
            return dialog.close;
        },
    };
    class PosStore { postSyncAllOrders() { return "original-result"; } }
    class Navbar {}
    class Component {}
    class Dialog {}
    class BarcodeReader { async _scan(code) { return code; } }
    const barcodeReader = new BarcodeReader();
    const patch = (prototype, extension) => {
        Object.setPrototypeOf(extension, Object.fromEntries(Reflect.ownKeys(extension).map((name) => [name, prototype[name]])));
        Object.defineProperties(prototype, Object.getOwnPropertyDescriptors(extension));
    };
    const factory = new Function("Component", "onMounted", "onWillUnmount", "useState", "_t", "Dialog",
        "useService", "patch", "Navbar", "PosStore", "usePos", "window", "BarcodeReader",
        source + "\nreturn { ChequeDepositBanner, ChequeDepositDialog, BankingReminderModal };\n");
    const classes = factory(Component, (callback) => mounted.push(callback), (callback) => unmounted.push(callback),
        (state) => state, (text, value) => text.replace("%s", value), Dialog, (name) => name === "barcode_reader" ? barcodeReader : dialogService,
        patch, Navbar, PosStore, () => pos, browser, BarcodeReader);
    return { ...classes, mounted, unmounted, intervals, timeouts, dialogs, browser, barcodeReader, PosStore, calls: () => calls };
}

test("startup, interval and reconnect refresh; listeners clean up on unmount", async () => {
    const h = harness();
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    h.mounted[0]();
    await banner.refresh();
    assert.equal(banner.state.count, 2);
    assert.equal(h.intervals.get(1).ms, 90000);
    h.browser.dispatchEvent(new Event("online"));
    await new Promise(setImmediate);
    assert.equal(h.calls(), 2);
    h.intervals.get(1).callback();
    await new Promise(setImmediate);
    assert.equal(h.calls(), 3);
    h.unmounted[0]();
    assert.equal(h.intervals.size, 0);
    h.browser.dispatchEvent(new Event("online"));
    await new Promise(setImmediate);
    assert.equal(h.calls(), 3);
});

test("failed refresh preserves the previous count and marks it stale", async () => {
    let fail = false;
    const h = harness({ call: async () => {
        if (fail) throw new Error("offline");
        return { count: 150, checked_at: "2026-10-28 09:00:00" };
    } });
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    await banner.refresh();
    fail = true;
    await banner.refresh();
    assert.equal(banner.state.count, 150);
    assert.equal(banner.state.stale, true);
    fail = false;
    await banner.refresh();
    assert.equal(banner.state.stale, false);
});

test("an initial failed check reports unavailable rather than zero", async () => {
    const h = harness({ call: async () => { throw new Error("offline"); } });
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    await banner.refresh();
    assert.equal(banner.state.count, null);
    assert.equal(banner.label, "Cheque status unavailable");
});

test("POS payment synchronization refreshes the mounted banner", async () => {
    const h = harness();
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    h.mounted[0]();
    await new Promise(setImmediate);
    assert.equal(new h.PosStore().postSyncAllOrders([]), "original-result");
    await new Promise(setImmediate);
    assert.equal(h.calls(), 2);
    h.unmounted[0]();
});

test("disabled POS does not start checks or timers", () => {
    const h = harness({ enabled: false });
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    h.mounted[0]();
    assert.equal(h.calls(), 0);
    assert.equal(h.intervals.size, 0);
});

test("dialog requests the selected page and keeps full count", async () => {
    const h = harness({ call: async (model, method, args) => {
        assert.equal(model, "pos.uncleared.payment.hold");
        assert.equal(method, "pcd_pos_reminders");
        assert.deepEqual(args, [7, 40, 40]);
        return { rows: [{ id: 41 }], count: 150, offset: 40, limit: 40 };
    } });
    const dialog = new h.ChequeDepositDialog();
    dialog.setup();
    await dialog.load(40);
    assert.equal(dialog.state.count, 150);
    assert.equal(dialog.state.offset, 40);
    assert.equal(dialog.state.rows[0].id, 41);
});

test("a pending response cannot update an unmounted banner", async () => {
    let finish;
    const h = harness({ call: () => new Promise((resolve) => { finish = resolve; }) });
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    const request = banner.refresh();
    h.unmounted[0]();
    finish({ count: 9 });
    await request;
    assert.equal(banner.state.count, null);
});

test("due cheques automatically open a single blocking dialog on the first check", async () => {
    const h = harness();
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    await banner.refresh();
    assert.equal(h.dialogs.length, 1);
    assert.equal(h.dialogs[0].component, h.ChequeDepositDialog);
    assert.equal(banner.popupOpen, true);
    await banner.refresh();
    banner.open();
    assert.equal(h.dialogs.length, 1);
});

test("dismissal delays repeated popups independently of background checks", async () => {
    const h = harness();
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    await banner.refresh();
    h.dialogs[0].close();
    assert.equal(h.timeouts.get(1).ms, 180000);
    assert.equal(banner.popupOpen, false);
    await banner.refresh();
    await banner.refresh();
    assert.equal(h.dialogs.length, 1);
    h.timeouts.get(1).callback();
    await new Promise(setImmediate);
    assert.equal(h.dialogs.length, 2);
});

test("cleared cheques do not trigger another popup when the repeat interval expires", async () => {
    let count = 2;
    const h = harness({ call: async () => ({ count }) });
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    await banner.refresh();
    h.dialogs[0].close();
    count = 0;
    h.timeouts.get(1).callback();
    await new Promise(setImmediate);
    assert.equal(h.dialogs.length, 1);
    assert.equal(banner.state.count, 0);
});

test("failed first check does not block POS with an unverified reminder", async () => {
    const h = harness({ call: async () => { throw new Error("offline"); } });
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    await banner.refresh();
    assert.equal(h.dialogs.length, 0);
});

test("manual opening replaces the existing repeat timer and unmount cancels it", async () => {
    const h = harness();
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    await banner.refresh();
    h.dialogs[0].close();
    assert.equal(h.timeouts.size, 1);
    banner.open(false);
    assert.equal(h.timeouts.size, 0);
    assert.equal(h.dialogs.length, 2);
    h.unmounted[0]();
    assert.equal(h.dialogs[1].closed, true);
    assert.equal(h.timeouts.size, 0);
});

test("the reminder's local dialog ignores Escape", () => {
    const h = harness();
    const modal = new h.BankingReminderModal();
    modal.dismiss = () => { throw new Error("Escape must not dismiss the reminder"); };
    modal.onEscape();
    assert.equal(h.ChequeDepositDialog.components.Dialog, h.BankingReminderModal);
});

test("barcode operations pause while the reminder is open and resume after X", async () => {
    const h = harness();
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    assert.equal(await h.barcodeReader._scan("product"), "product");
    await banner.refresh();
    assert.equal(await h.barcodeReader._scan("product"), undefined);
    h.dialogs[0].close();
    assert.equal(await h.barcodeReader._scan("product"), "product");
});

test("unmount releases the barcode block exactly once", async () => {
    const h = harness();
    const banner = new h.ChequeDepositBanner();
    banner.setup();
    await banner.refresh();
    h.unmounted[0]();
    assert.equal(h.barcodeReader.pcdReminderBlocks, 0);
    assert.equal(await h.barcodeReader._scan("product"), "product");
});
