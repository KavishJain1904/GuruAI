// Verify the real dashboard view-switching code refreshes progress on entry,
// successful review, and back/forward-cache restoration.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('static/index.html', 'utf8');
const start = html.indexOf('            function refreshProgressView()');
const end = html.indexOf('            // ── Memory Chat ──', start);
assert(start !== -1 && end !== -1, 'progress view code is present');

function element() {
    const classes = new Set(['hidden']);
    return {
        className: '',
        classList: {
            add: (...names) => names.forEach(name => classes.add(name)),
            remove: (...names) => names.forEach(name => classes.delete(name)),
            contains: name => classes.has(name),
        },
    };
}
const ids = ['study-view', 'memory-view', 'progress-view', 'nav-study',
    'nav-memory', 'nav-progress', 'delete-session-btn'];
const elements = Object.fromEntries(ids.map(id => [id, element()]));
const listeners = {};
const calls = [];
const window = {
    loadStats: () => calls.push('stats'),
    refreshReviewQueue: () => calls.push('queue'),
    addEventListener: (name, callback) => { listeners[name] = callback; },
};
vm.runInNewContext(html.slice(start, end), {
    window,
    document: { getElementById: id => elements[id] },
    loadMemoryView: () => {},
});

window.switchView('study');
assert.deepEqual(calls, [], 'opening another view leaves progress alone');
window.switchView('progress');
assert.deepEqual(calls, ['stats', 'queue'], 'opening progress refreshes both widgets');
listeners.pageshow({ persisted: false });
assert.equal(calls.length, 2, 'initial page load avoids duplicate requests');
listeners.pageshow({ persisted: true });
assert.deepEqual(calls.slice(-2), ['stats', 'queue'], 'browser Back refreshes restored progress');
listeners['review-recorded']();
assert.equal(calls.length, 6, 'a saved review refreshes visible progress');
window.switchView('study');
listeners['review-recorded']();
assert.equal(calls.length, 6, 'hidden progress does not make unnecessary requests');
window.switchView('progress');
assert.equal(calls.length, 8, 'reopening progress fetches latest data');
console.log('Progress refresh checks passed');
