// Run: node frontend/test_frontend.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const common = fs.readFileSync(path.join(__dirname, 'common.js'), 'utf8');
const storage = new Map();
function page(name) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { textContent: '', innerHTML: '', value: '', style: {}, classList: { add() {}, remove() {} }, listeners: {}, addEventListener(event, handler) { this.listeners[event] = handler; } });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: element, querySelectorAll: () => [], addEventListener() {} },
    window: { location: { search: '?id=2&view=actions', href: '' } },
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
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
  const priorityForm = page('create_priority.html');
  assert.equal(priorityForm.element('owner-options').innerHTML, '');
  const owner = priorityForm.element('owner');
  owner.value = '  New Person  ';
  owner.listeners.change();
  owner.value = 'new person';
  owner.listeners.change();
  owner.value = '  ';
  owner.listeners.change();
  assert.deepEqual(JSON.parse(storage.get('development-plan.names')), ['New Person']);
  const actionForm = page('create_action.html');
  assert.match(actionForm.element('action-owner-options').innerHTML, /New Person/);
  const reviewForm = page('action_detail.html');
  assert.match(reviewForm.element('reviewer-options').innerHTML, /New Person/);
  reviewForm.element('rev-name').value = '<img src=x onerror="bad()">';
  reviewForm.element('rev-name').listeners.change();
  owner.listeners.focus();
  assert.ok(priorityForm.element('owner-options').innerHTML.includes('&lt;img'));
  assert.ok(!priorityForm.element('owner-options').innerHTML.includes('<img'));
  for (const invalid of ['bad JSON', '{}', '[null, 5, "", "Valid"]']) {
    storage.set('development-plan.names', invalid);
    assert.doesNotThrow(() => page('create_priority.html'));
  }
  priorityForm.context.localStorage.getItem = () => { throw new Error('Storage blocked'); };
  assert.doesNotThrow(() => owner.listeners.focus());
  for (const name of ['create_priority.html', 'create_action.html']) {
    assert.ok(!fs.readFileSync(path.join(__dirname, name), 'utf8').includes('<option value='));
  }
  const progressView = page('action_detail.html');
  vm.runInContext('currentAction = { id: 2 }; loadActionDetail = async () => {};', progressView.context);
  progressView.element('progress-input').value = '42.5';
  const submission = { preventDefault() {}, currentTarget: { reportValidity: () => true } };
  let progressRequest;
  progressView.context.fetch = async (url, options) => { progressRequest = { url, options }; return { ok: true }; };
  await progressView.element('progress-form').listeners.submit(submission);
  assert.match(progressRequest.url, /actions\/2\/progress$/);
  assert.equal(progressRequest.options.method, 'PATCH');
  assert.equal(JSON.parse(progressRequest.options.body).progress, 42.5);
  assert.equal(progressView.element('progress-feedback').textContent, 'Saved');
  progressView.context.fetch = async () => { throw new Error('Connection lost'); };
  await progressView.element('progress-form').listeners.submit(submission);
  assert.equal(progressView.element('progress-feedback').textContent, 'Connection lost');
  assert.equal(progressView.element('save-progress-btn').disabled, false);
  assert.equal(progressView.element('progress-input').disabled, false);
  for (const filename of ['priorities.html', 'priority_detail.html']) {
    const filteredView = page(filename);
    const listId = filename === 'priorities.html' ? 'priorities-list' : 'actions-cards-list';
    const records = [{ id: 1, title: 'Alpha', status: 'On Track' }, { id: 2, title: 'Beta', status: 'At Risk' }, { id: 3, title: 'Gamma', status: 'Off Track' }];
    filteredView.context.records = records;
    vm.runInContext(filename === 'priorities.html' ? 'items = records; renderList();' : 'currentPriority = { id: 1, actions: records }; renderActionsList();', filteredView.context);
    assert.match(filteredView.element(listId).innerHTML, /Alpha/);
    assert.match(filteredView.element(listId).innerHTML, /Beta/);
    for (const [status, expected] of [['On Track', 'Alpha'], ['At Risk', 'Beta'], ['Off Track', 'Gamma']]) {
      vm.runInContext(`toggleStatusFilter(${JSON.stringify(status)})`, filteredView.context);
      const result = filteredView.element(listId).innerHTML;
      assert.match(result, new RegExp(expected));
      for (const record of records.filter(record => record.title !== expected)) assert.ok(!result.includes(record.title));
      vm.runInContext(`toggleStatusFilter(${JSON.stringify(status)})`, filteredView.context);
      for (const record of records) assert.ok(filteredView.element(listId).innerHTML.includes(record.title));
    }
    vm.runInContext(filename === 'priorities.html' ? "searchQuery = 'Alpha'; toggleStatusFilter('At Risk');" : "actionsSearchQuery = 'Alpha'; toggleStatusFilter('At Risk');", filteredView.context);
    assert.match(filteredView.element(listId).innerHTML, /No (items|actions) match/);
  }
  for (const filename of ['action_detail.html', 'priority_detail.html']) {
    const statusView = page(filename);
    vm.runInContext(filename === 'action_detail.html' ? "currentAction = { status: 'On Track' }; loadActionDetail = async () => {};" : "currentPriority = { status: 'On Track' }; loadPriorityDetails = async () => {};", statusView.context);
    // The editor retains the original reload callback; return a complete record for that callback.
    const record = { id: 2, priority_id: 1, title: 'Example', status: 'At Risk', progress: 0, actions: [], subactions: [], reviews: [] };
    let savedStatus;
    statusView.context.fetch = async (url, options) => {
      if (options) savedStatus = JSON.parse(options.body).status;
      return { ok: true, json: async () => record };
    };
    statusView.element('status-input').value = 'At Risk';
    await statusView.element('status-input').listeners.change();
    assert.equal(savedStatus, 'At Risk');
    assert.equal(statusView.element('status-feedback').textContent, 'Saved');
    statusView.context.fetch = async () => { throw new Error('Offline'); };
    statusView.element('status-input').value = 'Off Track';
    await statusView.element('status-input').listeners.change();
    assert.equal(statusView.element('status-input').value, 'At Risk');
    assert.equal(statusView.element('status-input').disabled, false);
    assert.equal(statusView.element('status-feedback').textContent, 'Offline');
  }
  const detailView = page('action_detail.html');
  const loadedRecord = { id: 2, priority_id: 1, title: 'Almost done', status: 'On Track', progress: 99.9, subactions: [], reviews: [] };
  detailView.context.fetch = async () => ({ ok: true, json: async () => loadedRecord });
  await vm.runInContext('loadActionDetail()', detailView.context);
  assert.equal(detailView.element('overview-progress-text').textContent, '99.9%');
  assert.equal(detailView.element('overview-completion-status').textContent, 'In Progress');
  const failures = [];
  detailView.context.console = { error: error => failures.push(error), warn() {} };
  detailView.context.fetch = async (url, options) => {
    if (!options) throw new Error('Refresh failed');
    return { ok: true };
  };
  detailView.element('progress-input').value = '80';
  await detailView.element('progress-form').listeners.submit(submission);
  assert.equal(detailView.element('progress-feedback').textContent, 'Saved. Reload to refresh the display.');
  assert.match(detailView.element('load-error').textContent, /Refresh failed/);
  detailView.element('status-input').value = 'At Risk';
  await detailView.element('status-input').listeners.change();
  assert.equal(detailView.element('status-input').value, 'At Risk');
  assert.equal(detailView.element('status-feedback').textContent, 'Saved. Reload to refresh the display.');

  // Repeated clicks during a pending request must not create duplicates or undo a toggle.
  vm.runInContext('loadActionDetail = async () => true;', detailView.context);
  for (const formId of ['add-subaction-form', 'add-review-form']) {
    detailView.element('new-subaction-title').value = 'Step';
    detailView.element('new-subaction-date').value = '2026-09-11';
    detailView.element('rev-name').value = 'Reviewer';
    detailView.element('rev-date').value = '2026-09-11';
    detailView.element('rev-comment').value = 'Checked';
    detailView.context.document.querySelector = () => ({ value: 'Approved' });
    const button = { disabled: false };
    const event = { preventDefault() {}, currentTarget: { querySelector: () => button } };
    let release, requests = 0;
    detailView.context.fetch = () => { requests++; return new Promise(resolve => { release = resolve; }); };
    const pending = detailView.element(formId).listeners.submit(event);
    await detailView.element(formId).listeners.submit(event);
    assert.equal(requests, 1);
    release({ ok: true });
    await pending;
    assert.equal(button.disabled, false);
  }
  let releaseToggle, toggles = 0;
  detailView.context.fetch = () => { toggles++; return new Promise(resolve => { releaseToggle = resolve; }); };
  const pendingToggle = vm.runInContext('toggleSubAction(1)', detailView.context);
  await vm.runInContext('toggleSubAction(1)', detailView.context);
  assert.equal(toggles, 1);
  releaseToggle({ ok: true });
  await pendingToggle;
  console.log('Frontend regression checks passed: six pages, names, statuses, filters, progress, failed refreshes and duplicate submissions.');
})().catch(error => { console.error(error); process.exitCode = 1; });
