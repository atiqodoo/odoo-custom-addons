// Execute the actual POS synchronization method with controlled network/model adapters.
// Run: node custom_addon/pos_auto_variant_price_rounding/tests/price_sync.test.cjs
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const { test } = require("node:test");

const source = readFileSync(join(__dirname, "../static/src/price_sync.js"), "utf8")
    .replace(/^import .*;\r?\n/gm, "");
let methods;
const timers = [];
vm.runInNewContext(source, {
    patch: (_target, extension) => { methods = extension; },
    PosStore: { prototype: {} }, document: {},
    browser: { clearTimeout() {}, setTimeout(fn, delay) { timers.push({ fn, delay }); return timers.length; } },
    _t: (text) => text,
    computeProductPricelistCache(data) {
        data.cacheBuilds++;
        data.product.cachedPricelistRules = {
            1: data.items.filter((item) => !item.deleted),
        };
    },
});

function fixture(call) {
    const data = { items: [], cacheBuilds: 0, product: { id: 7, cachedPricelistRules: {} } };
    const itemModel = { getAll: () => data.items.filter((item) => !item.deleted) };
    const add = (raw) => data.items.push({ ...raw, delete(options) {
        assert.equal(options.silent, true, "cache replacement must not enqueue backend unlink commands");
        this.deleted = true;
    } });
    add({ id: 1, fixed_price: 100 });
    const line = { product_id: 7, price_unit: 100, qty: 2 };
    const store = {
        config: { id: 1, auto_variant_price_sync_interval: 45 },
        models: { "product.product": { getAll: () => [data.product] }, "product.pricelist.item": itemModel },
        data: Object.assign(data, {
            call,
            models: { loadData(values) { for (const raw of values["product.pricelist.item"]) add(raw); } },
        }),
        notification: { messages: [], add(text) { this.messages.push(text); } },
        order: { lines: [line] },
    };
    store.syncVariantPrices = methods.syncVariantPrices.bind(store);
    return { store, data, line, itemModel };
}

test("replaces stale rules, rebuilds cache and preserves current order prices", async () => {
    const { store, data, line, itemModel } = fixture(async () => ({
        revision: "new", interval: 30, rules: [{ id: 2, fixed_price: 150 }],
    }));
    await store.syncVariantPrices();
    assert.deepEqual(itemModel.getAll().map((item) => item.id), [2]);
    assert.equal(data.product.cachedPricelistRules[1][0].fixed_price, 150);
    assert.equal(line.price_unit, 100);
    assert.equal(line.qty, 2);
    assert.equal(store.variantPriceRevision, "new");
    assert.equal(timers.at(-1).delay, 30000);
});

test("network failures keep cached data, retry, and warn only once", async () => {
    const { store, itemModel } = fixture(async () => { throw new Error("offline"); });
    await store.syncVariantPrices();
    await store.syncVariantPrices();
    assert.equal(itemModel.getAll()[0].fixed_price, 100);
    assert.equal(store.notification.messages.length, 1);
    assert.equal(store.variantPriceRevision, undefined);
    assert.equal(timers.at(-1).delay, 45000);
    store.data.call = async () => ({ revision: "recovered", interval: 30, rules: [] });
    await store.syncVariantPrices();
    assert.equal(store.variantPriceSyncWarning, false);
    assert.equal(itemModel.getAll().length, 0);
});

test("unchanged revision still refreshes date-sensitive caches", async () => {
    const { store, data } = fixture(async () => ({ revision: "same", interval: 30, rules: null }));
    await store.syncVariantPrices();
    assert.equal(data.cacheBuilds, 1);
    assert.equal(data.items[0].deleted, undefined);
});

test("a notification during an in-flight fetch causes another fetch", async () => {
    let release;
    let calls = 0;
    const { store } = fixture(async () => {
        calls++;
        if (calls === 1) await new Promise((resolve) => { release = resolve; });
        return { revision: String(calls), interval: 30, rules: null };
    });
    const first = store.syncVariantPrices();
    await store.syncVariantPrices();
    release();
    await first;
    assert.equal(calls, 2);
    assert.equal(store.variantPriceRevision, "2");
});

test("native Odoo model relationships and price cache survive a rule replacement", async () => {
    const native = vm.createContext({
        reactive: (value) => value, toRaw: (value) => value,
        uuidv4: () => "test", registry: { category: () => ({ add() {} }) },
        _t: (text) => text, roundPrecision: (value) => value,
        luxon: { DateTime: { now: () => Date.now() } },
        deserializeDateTime: (text) => new Date(text).getTime(),
    });
    const nativeFile = (name) => readFileSync(join(__dirname,
        "../../../server/odoo/addons/point_of_sale/static/src/", name), "utf8")
        .replace(/^import .*;\r?\n/gm, "").replace(/export /g, "");
    vm.runInContext(nativeFile("app/models/related_models.js"), native);
    vm.runInContext(nativeFile("app/models/product_product.js"), native);
    const utils = nativeFile("utils.js");
    vm.runInContext(utils.slice(utils.indexOf("function computeProductPricelistCache")), native);
    const api = vm.runInContext("({createRelatedModels, ProductProduct, computeProductPricelistCache})", native);
    const int = { type: "integer" };
    const m2o = (relation) => ({ type: "many2one", relation });
    const definitions = {
        "product.category": { id: int, parent_id: m2o("product.category") },
        "product.template": { id: int },
        "product.product": { id: int, product_tmpl_id: m2o("product.template"),
            categ_id: m2o("product.category"), lst_price: { type: "float" } },
        "product.pricelist": { id: int,
            item_ids: { type: "one2many", relation: "product.pricelist.item", inverse_name: "pricelist_id" } },
        "product.pricelist.item": { id: int, pricelist_id: m2o("product.pricelist"),
            product_id: m2o("product.product"), product_tmpl_id: m2o("product.template"),
            min_quantity: { type: "float" }, fixed_price: { type: "float" }, compute_price: { type: "char" } },
    };
    for (const fields of Object.values(definitions)) {
        for (const [name, field] of Object.entries(fields)) fields[name] = { ...field, name };
    }
    const { models } = api.createRelatedModels(definitions,
        { "product.product": api.ProductProduct }, { dynamicModels: [] });
    models.loadData({
        "product.template": [{ id: 1 }],
        "product.product": [{ id: 7, product_tmpl_id: 1, lst_price: 1 }],
        "product.pricelist": [{ id: 1 }],
        "product.pricelist.item": [{ id: 1, pricelist_id: 1, product_id: 7,
            compute_price: "fixed", fixed_price: 100, min_quantity: 0 }],
    });
    const { store } = fixture(async () => ({ revision: "native", interval: 30, rules: [
        { id: 2, pricelist_id: 1, product_id: 7, compute_price: "fixed", fixed_price: 150, min_quantity: 0 },
    ] }));
    store.models = models;
    store.data.models = models;
    // The synchronization extension uses the native cache builder in this test.
    let nativeSync;
    vm.runInNewContext(source, {
        patch: (_target, extension) => { nativeSync = extension.syncVariantPrices; },
        PosStore: { prototype: {} }, browser: { clearTimeout() {}, setTimeout() {} },
        _t: (text) => text, computeProductPricelistCache: api.computeProductPricelistCache,
    });
    await nativeSync.call(store);
    assert.equal(models["product.product"].get(7).get_price(models["product.pricelist"].get(1), 1), 150);
    assert.equal(models["product.pricelist"].get(1).item_ids.length, 1);
    assert.equal(models["product.pricelist"].get(1).item_ids[0].id, 2);
    for (const commands of Object.values(models.commands)) {
        assert.equal(commands.delete.size, 0);
        assert.equal(commands.unlink.size, 0);
        assert.equal(commands.update.size, 0);
    }
});
