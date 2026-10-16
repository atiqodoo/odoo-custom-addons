// Run: node --test custom_addon/purchase_net_price_compute/tests/tally_attachments.test.mjs
// Load the real widget and Odoo FileModel; stub only the OWL/Odoo service boundary.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const addon = new URL('../', import.meta.url);
const odoo = new URL('../../server/odoo/addons/', addon);
let definition;
const context = vm.createContext({
    Component: class {},
    standardFieldProps: {},
    useState: (state) => state,
    registry: { category: () => ({ add: (name, value) => {
        assert.equal(name, 'pnpc_tally_attachments');
        definition = value;
    } }) },
    url: (route, params) => `${route}?${new URLSearchParams(params)}`,
});
function load(path) {
    const source = readFileSync(path, 'utf8')
        .replace(/^import .*;\r?\n/gm, '')
        .replace(/^export /gm, '');
    vm.runInContext(source, context, { filename: path.pathname });
}
load(new URL('web/static/src/core/file_viewer/file_model.js', odoo));
load(new URL('static/src/fields/tally_attachments.js', addon));

function widget(files) {
    const component = new definition.component();
    component.props = { name: 'available_attachment_ids', record: { data: {
        available_attachment_ids: { records: files.map((data, index) => ({
            resId: index + 1, data,
        })) },
    } } };
    component.props.record.update = async (values) => Object.assign(component.props.record.data, values);
    if (files.length) {
        component.props.record.data.attachment_id = [1, files[0].name];
    }
    component.setup();
    return component;
}

test('all source attachments are retained, including beyond the usual list page size', () => {
    const files = widget(Array.from({ length: 65 }, (_, i) => ({
        name: `file${i}.pdf`, mimetype: 'application/pdf', type: 'binary',
    }))).files;
    assert.equal(files.length, 65);
    assert.equal(files[64].id, 65);
    assert.equal(files[64].displayName, 'file64.pdf');
});

test('attachment click changes the form selection for the inline preview', async () => {
    const component = widget([
        { name: 'invoice.pdf', mimetype: 'application/pdf' },
        { name: 'receipt.png', mimetype: 'image/png' },
        { name: 'data.zip', mimetype: 'application/zip' },
    ]);
    const files = component.files;
    await component.select(files[1]);
    assert.equal(component.props.record.data.attachment_id[0], 2);
    assert.equal(component.selectedIndex, 1);
    assert.equal(component.state.isSelecting, false);
    assert.equal(files.filter((file) => file.isViewable).length, 2);
    assert.match(files[0].defaultSource, /pdfjs\/web\/viewer.html/);
    assert.match(files[1].defaultSource, /\/web\/image\/2/);
    assert.match(files[2].downloadUrl, /download=true/);
});

test('previous and next cycle all attachments, including downloadable formats', async () => {
    const component = widget([
        { name: 'invoice.pdf', mimetype: 'application/pdf' },
        { name: 'data.zip', mimetype: 'application/zip' },
        { name: 'receipt.png', mimetype: 'image/png' },
    ]);
    await component.navigate(1);
    assert.equal(component.selectedIndex, 1);
    await component.navigate(1);
    assert.equal(component.selectedIndex, 2);
    await component.navigate(1);
    assert.equal(component.selectedIndex, 0);
    await component.navigate(-1);
    assert.equal(component.selectedIndex, 2);
});

test('failed selection releases loading state and preserves current selection', async () => {
    const component = widget([{ name: 'one.pdf' }, { name: 'two.pdf' }]);
    component.props.record.update = async () => { throw new Error('Access denied'); };
    await assert.rejects(component.select(component.files[1]), /Access denied/);
    assert.equal(component.state.isSelecting, false);
    assert.equal(component.selectedIndex, 0);
});

test('empty, single-file and missing selections are safe to navigate', async () => {
    assert.equal(widget([]).navigate(1), undefined);
    const single = widget([{ name: 'one.pdf' }]);
    await single.navigate(1);
    assert.equal(single.selectedIndex, 0);
    single.props.record.data.attachment_id = false;
    await single.navigate(-1);
    assert.equal(single.selectedIndex, 0);
});

test('empty source document is supported', () => {
    assert.equal(widget([]).files.length, 0);
    assert.equal(definition.isEmpty(), false);
});

test('OWL template assignments do not overwrite component getters', () => {
    const template = readFileSync(new URL('static/src/fields/tally_attachments.xml', addon), 'utf8');
    const component = widget([{ name: 'invoice.pdf', mimetype: 'application/pdf' }]);
    // OWL resolves t-set names against the component context, including its prototype.
    for (const [, name] of template.matchAll(/t-set="([^"]+)"/g)) {
        assert.equal(name in component, false, `Template variable ${name} shadows a component member`);
    }
    assert.match(template, /t-foreach="attachmentFiles"/);
    assert.match(template, /this\.select\(file\)/);
    assert.match(template, /this\.navigate\(-1\)/);
    assert.match(template, /this\.navigate\(1\)/);
    assert.doesNotMatch(readFileSync(new URL('static/src/fields/tally_attachments.js', addon), 'utf8'), /useFileViewer/);
});

test('metadata stays read-only and names are passed as text to the template', () => {
    const files = widget([{ name: '<script>alert(1)</script>.pdf', mimetype: 'application/pdf' }]).files;
    assert.equal(files[0].displayName, '<script>alert(1)</script>.pdf');
    const template = readFileSync(new URL('static/src/fields/tally_attachments.xml', addon), 'utf8');
    assert.match(template, /t-out="file.displayName"/);
    assert.doesNotMatch(template, /t-raw|onFileRemove|onFileUploaded/);
    assert.equal(definition.relatedFields.some((field) => field.name === 'access_token'), false);
});
