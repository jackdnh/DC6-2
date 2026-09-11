function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
}

function localDate(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

async function apiFetch(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(typeof detail === 'string' ? detail :
      Array.isArray(detail) ? detail.map(error => `${error.loc.slice(1).join('.')}: ${error.msg}`).join('\n') :
      `Request failed (${response.status})`);
  }
  return response;
}

function setupNameSuggestions(inputId, listId) {
  const input = document.getElementById(inputId);
  const list = document.getElementById(listId);
  const storageKey = 'development-plan.names';
  function readNames() {
    try {
      const names = JSON.parse(localStorage.getItem(storageKey) || '[]');
      return Array.isArray(names) ? names.filter(name => typeof name === 'string' && name.trim()) : [];
    } catch {
      return [];
    }
  }
  function render(names = readNames()) {
    list.innerHTML = names.map(name => `<option value="${escapeHtml(name)}"></option>`).join('');
  }
  input.addEventListener('focus', () => render());
  input.addEventListener('change', () => {
    const name = input.value.trim();
    if (!name) return;
    const names = readNames();
    if (!names.some(saved => saved.toLowerCase() === name.toLowerCase())) {
      names.push(name);
      names.sort((a, b) => a.localeCompare(b));
      try {
        localStorage.setItem(storageKey, JSON.stringify(names));
      } catch (error) {
        console.warn('Name suggestions could not be saved in this browser.', error);
      }
    }
    render(names);
  });
  render();
}

const TRACKING_STATUSES = ['On Track', 'At Risk', 'Off Track'];

function updateStatusFilters(selected) {
  document.querySelectorAll('[data-status-filter]').forEach(button => {
    const active = button.dataset.statusFilter === selected;
    button.setAttribute('aria-pressed', String(active));
    button.classList.toggle('ring-2', active);
    button.classList.toggle('ring-blue-500', active);
  });
}

function setupStatusEditor(url, getRecord, reload) {
  const select = document.getElementById('status-input');
  const feedback = document.getElementById('status-feedback');
  select.addEventListener('change', async () => {
    const record = getRecord();
    if (!record || select.disabled) return;
    const previous = record.status;
    select.disabled = true;
    feedback.textContent = 'Saving...';
    try {
      await apiFetch(url, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: select.value })
      });
      record.status = select.value;
      const refreshed = await reload();
      feedback.textContent = refreshed === false ? 'Saved. Reload to refresh the display.' : 'Saved';
    } catch (error) {
      select.value = previous;
      feedback.textContent = error.message || 'Unable to save status.';
    } finally {
      select.disabled = false;
    }
  });
}
