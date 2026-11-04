// Exercise widget loading, safe text rendering, paging, and request failures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function element() {
    return { hidden: false, innerHTML: '', textContent: '', listeners: {},
        addEventListener(type, callback) { this.listeners[type] = callback; } };
}
const elements = Object.fromEntries(['details', '[data-history-list]', '[data-history-previous]',
    '[data-history-next]', '[data-history-refresh]'].map(key => [key, element()]));
const container = { innerHTML: '', querySelector: key => elements[key] };
const callbacks = {};
const requests = [];
let fail = false;
const event = { kind: 'self_rating', score: 0.8, subject: 'Biology', topic: 'Mitosis',
    mastery_before: 0.5, mastery_after: 0.59, reviewed_at: '2026-10-04T12:30:00',
    next_review_date: '2026-10-07T12:30:00', notes: '<img src=x onerror=alert(1)>',
    question: '<script>bad()</script>', selected_answer: 'A&B', correct_answer: 'C' };
const window = { addEventListener: (name, callback) => callbacks[name] = callback };
vm.runInNewContext(fs.readFileSync('static/widgets/review-history.js', 'utf8'), {
    window, document: { getElementById: () => container },
    fetch: async url => { requests.push(url); return { ok: !fail,
        json: async () => ({ items: [event], has_more: requests.length === 1 }) }; }
});
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
    window.initReviewHistoryWidget('history');
    assert.equal(requests.length, 0, 'history is loaded on demand');
    elements.details.open = true;
    elements.details.listeners.toggle();
    await settle();
    const html = elements['[data-history-list]'].innerHTML;
    assert.match(html, /Self-rating · 8\/10/);
    assert.match(html, /50% → 59%/);
    assert.match(html, /&lt;img/);
    assert.doesNotMatch(html, /<img|<script>/);
    assert.match(html, /A&amp;B/);
    assert.equal(elements['[data-history-next]'].hidden, false);
    elements['[data-history-next]'].listeners.click();
    await settle();
    assert.match(requests.at(-1), /offset=10/);
    assert.equal(elements['[data-history-previous]'].hidden, false);
    callbacks['review-recorded']();
    await settle();
    assert.match(requests.at(-1), /offset=0/);
    fail = true;
    elements['[data-history-refresh]'].listeners.click();
    await settle();
    assert.match(elements['[data-history-list]'].textContent, /Unable to load/);
    console.log('Review history widget checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
