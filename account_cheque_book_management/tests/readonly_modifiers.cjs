// Run: node --experimental-vm-modules <path-to-this-file>
// Exercise Odoo's actual browser expression evaluator: Python Form tests use
// Python list comparison and cannot detect JavaScript array identity semantics.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

(async () => {
    const addon = path.resolve(__dirname, '..');
    const workspace = path.resolve(addon, '..', '..');
    const directory = path.join(workspace, 'server/odoo/addons/web/static/src/core/py_js');
    const modules = new Map();
    for (const filename of fs.readdirSync(directory).filter(name => name.endsWith('.js'))) {
        const identifier = path.join(directory, filename);
        modules.set(identifier, new vm.SourceTextModule(fs.readFileSync(identifier, 'utf8'), {identifier}));
    }
    const entry = modules.get(path.join(directory, 'py.js'));
    await entry.link((specifier, referencing) => modules.get(path.resolve(path.dirname(referencing.identifier), specifier + '.js')));
    await entry.evaluate();
    const {evaluateBooleanExpr} = entry.namespace;
    assert.equal(evaluateBooleanExpr('cheque_attempt_ids != []', {cheque_attempt_ids: []}), true,
        'Reproduce why the previous expression incorrectly locked a new payment');
    const xml = fs.readFileSync(path.join(addon, 'views/payment_views.xml'), 'utf8');
    for (const field of ['cheque_book_id', 'cheque_leaf_id', 'cheque_date']) {
        const attributes = xml.match(new RegExp('<field name="' + field + '"[^>]*readonly="([^"]+)"'));
        assert.ok(attributes, field + ': readonly modifier must exist');
        assert.equal(evaluateBooleanExpr(attributes[1], {cheque_attempt_ids: []}), false,
            field + ': editable before reservation');
        assert.equal(evaluateBooleanExpr(attributes[1], {cheque_attempt_ids: [21]}), true,
            field + ': protected after reservation');
    }
    console.log('PASS: all 3 cheque fields editable before reservation and protected afterward, using Odoo browser evaluator');
})().catch(error => { console.error(error); process.exitCode = 1; });
