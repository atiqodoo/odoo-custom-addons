// Run: node --test custom_addon/pos_cod/tests/promise_client.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const root = new URL("../", import.meta.url);
const luxonContext = vm.createContext({});
vm.runInContext(readFileSync(new URL("../../server/odoo/addons/web/static/lib/luxon/luxon.js", root), "utf8"), luxonContext);
const luxon = luxonContext.luxon;
const read = (path) => readFileSync(new URL(path, root), "utf8")
    .replace(/^import .*;\r?\n/gm, "").replaceAll("export class ", "class ")
    .replaceAll("export function ", "function ").replaceAll("export const ", "const ");
const { promiseDateTime, formatPromise } = new Function("luxon", read("static/src/app/utils/cod_promise.js") +
    "\nreturn {promiseDateTime, formatPromise};")(luxon);

test("AM/PM, next-day earlier clock times, exact display and invalid dates", () => {
    assert.equal(promiseDateTime("2026-11-06", 12, 0, "AM", "Africa/Nairobi").hour, 0);
    assert.equal(promiseDateTime("2026-11-06", 12, 0, "PM", "Africa/Nairobi").hour, 12);
    assert.equal(promiseDateTime("2026-11-07", 9, 30, "AM", "Africa/Nairobi").toUTC().hour, 6);
    assert.equal(formatPromise("2026-11-07 06:30:00", "Africa/Nairobi"), "07/11/2026 09:30 AM");
    assert.equal(formatPromise(false, "Africa/Nairobi"), "Promise not set");
    for (const args of [["2026-02-30", 1, 0, "PM"], ["2026-11-06", 0, 0, "AM"],
        ["2026-11-06", 13, 0, "AM"], ["2026-11-06", 1, 60, "AM"],
        ["2026-11-06", 1, "", "AM"], ["", 1, 0, "AM"]]) {
        assert.equal(promiseDateTime(...args, "Africa/Nairobi"), null);
    }
});

test("nonexistent and ambiguous DST promises require correction", () => {
    assert.equal(promiseDateTime("2026-03-08", 2, 30, "AM", "America/New_York"), null);
    assert.equal(promiseDateTime("2026-11-01", 1, 30, "AM", "America/New_York"), null);
});

function harness({ call, enabled = true } = {}) {
    const mounted = [], unmounted = [], intervals = new Map(), timeouts = new Map(), dialogs = [];
    const browser = new EventTarget();
    let timerId = 0, now = 100, calls = 0, otherDialog = false;
    Object.assign(browser, {
        setInterval: (fn, ms) => { intervals.set(++timerId, { fn, ms }); return timerId; },
        clearInterval: (id) => intervals.delete(id),
        setTimeout: (fn, ms) => { timeouts.set(++timerId, { fn, ms }); return timerId; },
        clearTimeout: (id) => timeouts.delete(id),
    });
    const row = { id: 1, name: "COD/1", promised_at: "2026-11-06 12:00:00", open_amount: 100 };
    const pos = { config: { id: 7, cod_enabled: true, cod_collection_promises_enabled: enabled,
        cod_collection_timezone: "Africa/Nairobi", cod_reminder_refresh_seconds: 60,
        cod_reminder_interval_minutes: 10 }, data: {
        call: async (...args) => { calls++; return call ? call(...args) : {
            rows: [row], count: 1, offset: 0, limit: 40, timezone: "Africa/Nairobi", next_due_in_seconds: null,
        }; },
    } };
    class Component {}
    class Dialog {}
    class Navbar {}
    class BarcodeReader { async _scan(code) { return code; } }
    const barcode = new BarcodeReader();
    const dialog = { add(component, props, options) {
        const entry = { component, props };
        let closed = false;
        entry.close = () => { if (!closed) { closed = true; options.onClose(); } };
        dialogs.push(entry);
        return entry.close;
    } };
    const patch = (prototype, extension) => {
        Object.setPrototypeOf(extension, Object.fromEntries(Reflect.ownKeys(extension).map((name) => [name, prototype[name]])));
        Object.defineProperties(prototype, Object.getOwnPropertyDescriptors(extension));
    };
    const classes = new Function("Component", "onMounted", "onWillUnmount", "useState", "Dialog", "useService",
        "usePos", "BarcodeReader", "Navbar", "patch", "formatPromise", "formatMonetary", "window", "document", "performance",
        read("static/src/app/components/cod_reminder/CodReminder.js") + "\nreturn {CodReminder, CodReminderModal};")(
        Component, (cb) => mounted.push(cb), (cb) => unmounted.push(cb), (state) => state, Dialog,
        (name) => name === "barcode_reader" ? barcode : dialog, () => pos, BarcodeReader, Navbar, patch,
        formatPromise, (value) => String(value), browser, { querySelector: () => otherDialog }, { now: () => now });
    const reminder = new classes.CodReminder();
    reminder.setup();
    return { ...classes, reminder, mounted, unmounted, intervals, timeouts, dialogs, browser, barcode, pos,
        calls: () => calls, setNow: (value) => { now = value; }, other: (value) => { otherDialog = value; } };
}
const settle = () => new Promise(setImmediate);

test("startup opens one blocking reminder, pauses barcode, X starts cooldown", async () => {
    const h = harness();
    h.mounted[0](); await settle();
    assert.equal(h.dialogs.length, 1);
    assert.equal(await h.barcode._scan("product"), undefined);
    await h.reminder.refresh();
    assert.equal(h.dialogs.length, 1);
    h.dialogs[0].close();
    assert.equal(await h.barcode._scan("product"), "product");
    assert.equal([...h.timeouts.values()].at(-1).ms, 600000);
    await h.reminder.refresh();
    assert.equal(h.dialogs.length, 1);
    h.setNow(600101); await h.reminder.refresh();
    assert.equal(h.dialogs.length, 2);
    h.unmounted[0]();
    assert.equal(h.barcode.codPromiseReminderBlocked, 0);
    assert.equal(h.intervals.size, 0);
    assert.equal(h.timeouts.size, 0);
});

test("fully settled orders do not reopen; failed checks retain stale information", async () => {
    let fail = false, count = 1;
    const h = harness({ call: async () => {
        if (fail) throw new Error("offline");
        return { count, rows: count ? [{ id: 1 }] : [], offset: 0, limit: 40 };
    } });
    await h.reminder.refresh(); h.dialogs[0].close();
    fail = true; await h.reminder.refresh();
    assert.equal(h.reminder.status.count, 1);
    assert.equal(h.reminder.status.stale, true);
    fail = false; count = 0; h.setNow(700000); await h.reminder.refresh();
    assert.equal(h.dialogs.length, 1);
    assert.equal(h.reminder.status.stale, false);
});

test("disabled reminders make no startup calls; another dialog delays popup", async () => {
    const disabled = harness({ enabled: false }); disabled.mounted[0](); await settle();
    assert.equal(disabled.calls(), 0);
    const h = harness(); h.other(true); await h.reminder.refresh();
    assert.equal(h.dialogs.length, 0);
    h.other(false); await h.reminder.refresh(); assert.equal(h.dialogs.length, 1);
});

test("Escape and POS input are blocked, X and list navigation remain usable", async () => {
    const h = harness(); await h.reminder.refresh();
    const event = (key, inside = false, button = false) => ({ key,
        target: { closest: (selector) => selector === "button" ? button : inside },
        preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; } });
    for (const e of [event("Escape", true), event("1", true), event("Enter", false), event("a", false)]) {
        h.reminder.blockKeyboard(e); assert.equal(e.prevented, true);
    }
    for (const e of [event("Tab", true), event("Enter", true, true), event(" ", true, true)]) {
        h.reminder.blockKeyboard(e); assert.equal(e.prevented, undefined);
    }
    assert.equal(new h.CodReminderModal().onEscape(), undefined);
});

test("requests do not overlap and a late response cannot open a destroyed reminder", async () => {
    let resolve;
    const h = harness({ call: () => new Promise((done) => { resolve = done; }) });
    const pending = h.reminder.refresh(); await h.reminder.refresh();
    assert.equal(h.calls(), 1); h.unmounted[0](); resolve({ count: 1, rows: [] }); await pending;
    assert.equal(h.dialogs.length, 0);
});

test("focus and reconnect refresh; earliest deadline gets its own timer", async () => {
    const h = harness({ call: async () => ({ count: 0, rows: [], next_due_in_seconds: 25 }) });
    h.mounted[0](); await settle();
    assert.ok([...h.timeouts.values()].some((timer) => timer.ms === 25000));
    const before = h.calls();
    h.browser.dispatchEvent(new Event("focus")); await settle();
    h.browser.dispatchEvent(new Event("online")); await settle();
    assert.equal(h.calls(), before + 2);
    h.unmounted[0](); h.browser.dispatchEvent(new Event("focus")); await settle();
    assert.equal(h.calls(), before + 2);
});

function wizardHarness({ fail = false } = {}) {
    const starts = [], payloads = [];
    const pos = { config: { id: 7, cod_collection_promises_enabled: true }, models: {}, data: {
        call: async () => {
            if (fail) throw new Error("offline");
            return { enabled: true, date: "2026-11-07", hour: 18, minute: 30,
                timezone: "Africa/Nairobi", server_now: "2026-11-06 12:00:00" };
        },
    } };
    class Component {}
    class Dialog {}
    class DateTimeInput {}
    const Wizard = new Function("Component", "onWillStart", "useState", "luxon", "DateTimeInput", "promiseDateTime",
        "Dialog", "usePos", "makeAwaitable", "PartnerList", "useService", "codWarn", "codError", "performance",
        read("static/src/app/components/cod_wizard/CodWizard.js") + "\nreturn CodWizard;")(
        Component, (cb) => starts.push(cb), (state) => state, luxon, DateTimeInput, promiseDateTime,
        Dialog, () => pos, null, null, () => ({}), () => {}, () => {}, { now: () => 100 });
    const wizard = new Wizard(); wizard.props = { getPayload: (data) => payloads.push(data), close() {} };
    wizard.setup(); wizard.state.partner_id = 1; wizard.state.employee_id = 2;
    return { wizard, starts, payloads };
}

test("wizard auto-fills, preserves edits, serializes UTC and rejects a passed cutoff", async () => {
    const h = wizardHarness(); await h.starts[0]();
    assert.equal(h.wizard.state.promiseDate, "2026-11-07");
    assert.equal(h.wizard.state.promiseHour, 6);
    h.wizard.state.promiseDate = "2026-11-08";
    h.wizard.state.promiseHour = 9; h.wizard.state.promisePeriod = "AM";
    h.wizard.confirm();
    assert.equal(h.payloads[0].payload.cod_promised_payment_at, "2026-11-08 06:30:00");
    h.wizard.state.promiseDate = "2026-11-06";
    h.wizard.confirm(); assert.equal(h.payloads.length, 1);
    assert.match(h.wizard.state.error, /later than dispatch/);
});

test("wizard cannot dispatch when server defaults are unavailable", async () => {
    const h = wizardHarness({ fail: true }); await h.starts[0](); h.wizard.confirm();
    assert.equal(h.payloads.length, 0); assert.equal(h.wizard.isValid, false);
});
