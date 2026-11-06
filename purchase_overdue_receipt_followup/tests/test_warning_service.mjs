// Standalone client-service contract test: node <this file>.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../static/src/js/overdue_warning_service.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?$/gm, '');

async function setup(allowed = true) {
    let service;
    const scheduled = [];
    const notifications = [];
    const calls = [];
    const actions = [];
    const doc = { hidden: false };
    const state = { fail: false };
    const context = {
        registry: { category: () => ({ add: (name, value) => { service = value; } }) },
        browser: { setTimeout: (fn) => scheduled.push(fn), setInterval: (fn) => scheduled.push(fn) },
        user: { hasGroup: async () => allowed },
        _t: (text) => text,
        document: doc,
        console: { debug() {} },
        Set,
    };
    vm.runInNewContext(source, context);
    await service.start({}, {
        orm: { call: async (model, method, args) => {
            calls.push({ model, method, args });
            if (state.fail) { throw new Error('offline'); }
            return args[0].includes(7) ? false : { id: 7, message: 'Overdue supplier receipt' };
        } },
        action: {
            doActionButton: async (params) => actions.push(params),
            doAction: async () => assert.fail('Raw actions bypass the button endpoint action preparation'),
        },
        notification: { add: (message, options) => notifications.push({ message, options }) },
    });
    return { scheduled, notifications, calls, actions, doc, state };
}

const denied = await setup(false);
assert.equal(denied.scheduled.length, 0, 'Non-purchase users must not poll');
const client = await setup();
assert.equal(client.scheduled.length, 2, 'Initial delayed check and periodic refresh registered');
client.doc.hidden = true;
await client.scheduled[0]();
assert.equal(client.calls.length, 0, 'Hidden tabs do not poll');
client.doc.hidden = false;
client.state.fail = true;
await client.scheduled[0]();
assert.equal(client.notifications.length, 0, 'Offline refresh does not interrupt buyer');
client.state.fail = false;
await client.scheduled[0]();
assert.equal(client.notifications.length, 1, 'Polling recovers after failure');
assert.equal(client.notifications[0].options.sticky, true);
await client.scheduled[1]();
assert.equal(client.notifications.length, 1, 'Seen alerts do not repeat in same page session');
await client.notifications[0].options.buttons[0].onClick();
assert.deepEqual(JSON.parse(JSON.stringify(client.actions[0])), {
    type: 'object', name: 'action_review', resModel: 'purchase.receipt.followup', resId: 7, context: {},
}, 'Review uses the standard button endpoint with the warned record');
assert.ok(client.calls.every((call) => call.method === 'get_popup_warning'),
          'Client notification never creates a purchase');
console.log('Warning service: 8 contract checks passed (including standard review button dispatch)');
