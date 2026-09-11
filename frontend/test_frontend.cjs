// Run: node frontend/test_frontend.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const common = fs.readFileSync(path.join(__dirname, 'common.js'), 'utf8');
function page(name) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { textContent: '', innerHTML: '', value: '', style: {}, classList: { add() {}, remove() {} }, addEventListener() {} });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: element, addEventListener() {} },
    window: { location: { search: '?id=2&view=actions', href: '' } },
    URLSearchParams, setInterval() {}, console,
  });
  vm.runInContext(common, context);
  const html = fs.readFileSync(path.join(__dirname, name), 'utf8');
  for (const match of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) {
    new vm.Script(match[2], { filename: name });
    if (match[2].includes('const API_BASE')) vm.runInContext(match[2], context);
  }
  return { context, element };
}
(async () => {
  for (const file of fs.readdirSync(__dirname).filter(file => file.endsWith('.html'))) page(file);
  const { context, element } = page('priorities.html');
  assert.equal(vm.runInContext(`escapeHtml('<img src=x onerror="bad()">&')`, context), '&lt;img src=x onerror=&quot;bad()&quot;&gt;&amp;');
  assert.equal(vm.runInContext('localDate({ getFullYear: () => 2026, getMonth: () => 0, getDate: () => 2 })', context), '2026-01-02');
  vm.runInContext(`items = [{ id: 9, priority_id: 4, title: '<img src=x onerror=bad()>', progress: 0 }]; renderList();`, context);
  assert.match(element('priorities-list').innerHTML, /SP4-A9/);
  assert.ok(!element('priorities-list').innerHTML.includes('<img'));
  vm.runInContext(`searchQuery = '<img>'; renderList();`, context);
  assert.ok(!element('priorities-list').innerHTML.includes('<img'));
  for (const name of ['priority_detail.html', 'action_detail.html']) {
    const view = page(name);
    vm.runInContext(name === 'priority_detail.html' ?
      `currentPriority = { id: 2, actions: [{ id: 3, title: '<img>', progress: 0 }] }; renderActionsList(); actionsSearchQuery = '<svg>'; renderActionsList();` :
      `currentAction = { subactions: [{ id: 1, title: '<img>', due_date: '<svg>', completed: false }], reviews: [{ reviewer_name: '<img>', comment: '<svg>', date: '<img>', status: 'Approved' }] }; renderSubActions(); renderReviews();`, view.context);
    for (const id of name === 'priority_detail.html' ? ['actions-cards-list'] : ['subactions-list', 'reviews-list']) {
      assert.ok(!view.element(id).innerHTML.includes('<img>'));
      assert.ok(!view.element(id).innerHTML.includes('<svg>'));
    }
  }
  context.fetch = async () => ({ ok: false, status: 422, json: async () => ({ detail: [{ loc: ['body', 'title'], msg: 'Required' }] }) });
  await assert.rejects(vm.runInContext('apiFetch("/api/priorities")', context), /title: Required/);
  context.fetch = async () => ({ ok: false, status: 500, json: async () => { throw new Error('not JSON'); } });
  await assert.rejects(vm.runInContext('apiFetch("/api/actions")', context), /500/);
  context.fetch = async () => ({ ok: true });
  assert.equal((await vm.runInContext('apiFetch("/api/actions")', context)).ok, true);
  console.log('Frontend regression checks passed (six pages, escaping, action labels, dates, API errors).');
})().catch(error => { console.error(error); process.exitCode = 1; });
