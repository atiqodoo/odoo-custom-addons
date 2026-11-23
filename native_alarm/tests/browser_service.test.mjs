// Executes the actual Odoo service with isolated browser/ORM adapters; no browser installation needed.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

async function harness(alarms = []) {
    const now = Date.parse('2026-11-18T07:30:00Z');
    const timers = new Map();
    const notices = [];
    const calls = [];
    const storage = new Map();
    let timerId = 0;
    let tones = 0;
    let failResponse = false;
    let failAudio = false;
    let failSong = false;
    const songs = [];
    const actions = [];
    const sourceAction = { type: 'ir.actions.act_window', res_model: 'sale.order', res_id: 42 };
    const schedule = { alarms, server_time: '2026-11-18 07:30:00', poll_seconds: 15, missed_minutes: 60 };
    class TestDate extends Date { static now() { return now; } }
    class Audio {
        constructor() { if (failAudio) { throw new Error('Audio unavailable'); } }
        state = 'suspended'; currentTime = 0;
        async resume() { this.state = 'running'; }
        createOscillator() { return { frequency: {}, connect() { return { connect() {} }; }, start() { tones++; }, stop() {} }; }
        createGain() { return { gain: {} }; }
    }
    class Song {
        constructor(src) { this.src = src; this.paused = true; songs.push(this); }
        async play() { if (failSong) { throw new Error('Unsupported codec'); } this.paused = false; }
        pause() { this.paused = true; }
    }
    const context = vm.createContext({
        console, Date: TestDate, AudioContext: Audio, Audio: Song,
        localStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v) },
        setInterval: (callback, delay) => { const id = ++timerId; timers.set(id, { callback, delay, interval: true }); return id; },
        setTimeout: (callback, delay) => { const id = ++timerId; timers.set(id, { callback, delay }); return id; },
        clearInterval: id => timers.delete(id), clearTimeout: id => timers.delete(id),
    });
    const registry = { category: () => ({ add() {} }) };
    const mocks = {
        '@odoo/owl': { Component: class {}, xml: () => '' },
        '@web/core/registry': { registry }, '@web/core/utils/hooks': { useService() {} },
        '@web/core/l10n/translation': { _t: value => value },
        '@web/session': { session: { db: 'isolated', uid: 7 } },
        '@web/views/fields/standard_field_props': { standardFieldProps: {} },
    };
    const module = new vm.SourceTextModule(await readFile(new URL('../static/src/alarm_service.js', import.meta.url), 'utf8'), { context });
    await module.link(async name => {
        const values = mocks[name];
        assert.ok(values, `Unexpected dependency: ${name}`);
        return new vm.SyntheticModule(Object.keys(values), function () {
            for (const [key, value] of Object.entries(values)) { this.setExport(key, value); }
        }, { context });
    });
    await module.evaluate();
    const service = module.namespace.alarmService.start({}, {
        orm: { async call(model, method, args) {
            calls.push({ model, method, args });
            if (method === 'browser_schedule') { return schedule; }
            if (failResponse) { throw new Error('Offline'); }
            if (method === 'action_open_record') { return sourceAction; }
            schedule.alarms = [];
            return true;
        } },
        notification: { add(name, options) {
            const notice = { name, options, removed: false }; notices.push(notice);
            return () => { notice.removed = true; options.onClose?.(); };
        } },
        action: { async doAction(value) { actions.push(value); } },
    });
    const flush = () => new Promise(resolve => setImmediate(resolve));
    await flush();
    return { service, timers, notices, calls, storage, schedule, songs, actions, sourceAction, flush, tones: () => tones,
        setFailure: () => { failResponse = true; },
        setAudioFailure: () => { failAudio = true; },
        setSongFailure: () => { failSong = true; },
        async refresh() { const poll = [...timers.values()].find(t => !t.interval && t.delay === 15000); await poll.callback(); await flush(); },
    };
}

const due = { id: 7, revision: 2, name: 'Draft quotation', alarm_at: '2026-11-18 07:30:00', ring_seconds: 0, snooze_minutes: 5 };

test('Open Source uses the authorized Odoo action without stopping the alarm', async () => {
    const h = await harness([due]);
    await h.notices[0].options.buttons.find(b => b.name === 'Open Source').onClick();
    assert.deepEqual(h.actions, [h.sourceAction]);
    assert.ok(h.calls.some(c => c.method === 'action_open_record'));
    assert.ok(!h.calls.some(c => c.method === 'browser_respond'));
    assert.equal(h.notices[0].removed, false);
});

test('Open Source access failure warns without stopping the alarm', async () => {
    const h = await harness([due]);
    h.setFailure();
    await h.notices[0].options.buttons.find(b => b.name === 'Open Source').onClick();
    assert.equal(h.actions.length, 0);
    assert.ok(h.notices.some(n => n.name.includes('source record is unavailable')));
    assert.equal(h.notices[0].removed, false);
});

test('due notification appears; audio starts only after user activation', async () => {
    const h = await harness([due]);
    assert.equal(h.notices.length, 1);
    assert.equal(h.tones(), 0);
    await h.service.enableSound();
    assert.ok(h.tones() > 0);
    assert.ok([...h.timers.values()].some(t => t.interval && t.delay === 1500));
    assert.ok(![...h.timers.values()].some(t => !t.interval && t.delay === 0));
});

test('future alarm stays silent and has no popup', async () => {
    const h = await harness([{ ...due, alarm_at: '2026-11-18 08:00:00' }]);
    assert.equal(h.notices.length, 0);
});

test('popup sound button enables audio for an already due alarm without acknowledging it', async () => {
    const h = await harness([due]);
    const button = h.notices[0].options.buttons.find(b => b.name === 'Enable / test sound');
    assert.ok(button);
    await button.onClick();
    assert.ok(h.tones() > 0);
    assert.ok(!h.calls.some(c => c.method === 'browser_respond'));
});

test('audio initialization failure produces visible feedback instead of an unhandled promise', async () => {
    const h = await harness([due]);
    h.setAudioFailure();
    await h.service.enableSound();
    assert.equal(h.tones(), 0);
    assert.equal(h.notices.length, 2);
    assert.ok(h.notices[1].name.includes('blocked alarm sound'));
});

test('missed tolerance prevents a new ring for an old alarm', async () => {
    const h = await harness([{ ...due, alarm_at: '2026-11-18 05:00:00' }]);
    assert.equal(h.notices.length, 0);
});

test('snooze sends expected revision and stops ringing after server acknowledgement', async () => {
    const h = await harness([due]);
    await h.service.enableSound();
    await h.notices[0].options.buttons[1].onClick();
    const response = h.calls.find(c => c.method === 'browser_respond');
    assert.equal(response.args[1], 'snooze');
    assert.equal(response.args[2], due.revision);
    assert.ok(h.notices[0].removed);
    assert.ok(![...h.timers.values()].some(t => t.interval && t.delay === 1500));
});

test('server cancellation removes ringing popup on refresh', async () => {
    const h = await harness([due]);
    await h.service.enableSound();
    h.schedule.alarms = [];
    await h.refresh();
    assert.ok(h.notices[0].removed);
    assert.ok(![...h.timers.values()].some(t => t.interval && t.delay === 1500));
});

test('failed acknowledgement preserves alarm and offers retry feedback', async () => {
    const h = await harness([due]);
    h.setFailure();
    await h.notices[0].options.buttons[0].onClick();
    assert.equal(h.notices[0].removed, false);
    assert.equal(h.notices.length, 2);
});

test('configured ring duration silences audio without completing the source or alarm', async () => {
    const h = await harness([{ ...due, ring_seconds: 20 }]);
    await h.service.enableSound();
    const timeout = [...h.timers.values()].find(t => !t.interval && t.delay === 20000);
    assert.ok(timeout);
    timeout.callback();
    assert.ok(![...h.timers.values()].some(t => t.interval && t.delay === 1500));
    assert.ok(!h.calls.some(c => c.method === 'browser_respond'));
    assert.equal(h.notices[0].removed, false);
});

test('uploaded song loops and stops on acknowledgement', async () => {
    const h = await harness([{ ...due, sound: { checksum: 'first', url: '/web/content/private-song' } }]);
    await h.service.enableSound();
    assert.equal(h.songs.length, 1);
    assert.equal(h.songs[0].loop, true);
    assert.equal(h.songs[0].paused, false);
    await h.notices[0].options.buttons[0].onClick();
    assert.equal(h.songs[0].paused, true);
    assert.equal(h.songs[0].src, '');
});

test('unsupported song falls back to a tone and warns visibly', async () => {
    const h = await harness([{ ...due, sound: { checksum: 'bad', url: '/web/content/song' } }]);
    h.setSongFailure();
    await h.service.enableSound();
    await h.flush();
    assert.ok(h.notices.some(n => n.name.includes('built-in tone')));
    assert.ok([...h.timers.values()].some(t => t.interval && t.delay === 1500));
});

test('changed default song replaces an already ringing file on refresh', async () => {
    const h = await harness([{ ...due, sound: { checksum: 'one', url: '/first' } }]);
    await h.service.enableSound();
    h.schedule.alarms = [{ ...due, sound: { checksum: 'two', url: '/second' } }];
    await h.refresh();
    assert.equal(h.songs[0].paused, true);
    assert.equal(h.songs.at(-1).src, '/second');
});
