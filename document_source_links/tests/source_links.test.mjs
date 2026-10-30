import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../static/src/source_links.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '')
    .replace('export class DocumentSourceLinks', 'class DocumentSourceLinks');

function widget(call, doAction, resId = 42) {
    const context = {
        Component: class {}, useState: (value) => value,
        useService: (name) => name === 'orm' ? { call } : { doAction },
        standardFieldProps: {}, registry: { category: () => ({ add() {} }) },
    };
    vm.createContext(context);
    vm.runInContext(source + '\nglobalThis.Widget = DocumentSourceLinks;', context);
    const instance = new context.Widget();
    instance.props = { name: 'source_link_data', record: {
        resId, resModel: 'stock.picking', data: { source_link_data: [] },
    } };
    instance.setup();
    return instance;
}

test('click sends parent and source IDs to the server authorization action', async () => {
    let callArgs, action;
    const instance = widget(async (...args) => { callArgs = args; return { marker: 'authorized' }; },
        async (value) => { action = value; });
    await instance.openSource({ model: 'purchase.order', id: 7 });
    assert.equal(callArgs[0], 'stock.picking');
    assert.equal(callArgs[1], 'action_open_source_link');
    assert.equal(JSON.stringify(callArgs[2]), '[[42],"purchase.order",7]');
    assert.equal(action.marker, 'authorized');
    assert.equal(instance.state.opening, false);
});

test('an authorization error never opens a document and resets the button', async () => {
    let opened = false;
    const instance = widget(async () => { throw new Error('denied'); }, async () => { opened = true; });
    await assert.rejects(instance.openSource({ model: 'pos.order', id: 1 }), /denied/);
    assert.equal(opened, false);
    assert.equal(instance.state.opening, false);
});

test('unsaved records and repeated clicks do not issue extra RPCs', async () => {
    let calls = 0, release;
    const call = async () => { calls++; await new Promise((resolve) => { release = resolve; }); return {}; };
    const instance = widget(call, async () => {});
    const first = instance.openSource({ model: 'pos.order', id: 1 });
    await instance.openSource({ model: 'pos.order', id: 1 });
    assert.equal(calls, 1);
    release();
    await first;
    const unsaved = widget(call, async () => {}, false);
    await unsaved.openSource({ model: 'pos.order', id: 1 });
    assert.equal(calls, 1);
});
