'use strict';

const $ = id => document.getElementById(id);
let csrf = '', conv = '', busy = false, activeTask = null, selected = null;
const conversationTitles = new Map();

function node(tag, text, parent) {
 const element = document.createElement(tag);
 if (text !== undefined) element.textContent = text;
 if (parent) parent.append(element);
 return element;
}

function notice(text) {
 $('notice').textContent = text;
 $('notice').hidden = false;
}

function loginView() {
 conversationTitles.clear();
 $('conversations').replaceChildren();
 csrf = '';
 conv = '';
 selected = null;
 activeTask = null;
 $('chatlog').replaceChildren();
 $('workspace').hidden = true;
 $('loginView').hidden = false;
}

async function api(path, options = {}) {
 const headers = {...(options.headers || {})};
 if (options.body && !(options.body instanceof FormData)) {
  headers['Content-Type'] = 'application/json';
  options.body = JSON.stringify(options.body);
 }
 if (options.method && !['GET', 'HEAD'].includes(options.method)) {
  headers['X-CSRF-Token'] = csrf;
 }
 const response = await fetch('/api' + path, {...options, headers, credentials: 'same-origin'});
 const raw = await response.text();
 let data;
 try {
  data = raw ? JSON.parse(raw) : {};
 } catch {
  throw Error('Unexpected server response (' + response.status + ').');
 }
 if (!response.ok) {
  if (response.status === 401) loginView();
  const message = typeof data.detail === 'string'
   ? data.detail
   : 'Request failed (' + response.status + ').';
  throw Error(message + (data.request_id ? ' Request: ' + data.request_id : ''));
 }
 return data;
}

async function guard(action, label = 'Working…') {
 if (busy) return;
 busy = true;
 $('progress').textContent = label;
 for (const id of ['attach', 'send', 'newChat']) $(id).disabled = true;
 try {
  await action();
  $('notice').hidden = true;
 } catch (error) {
  notice(error.message);
 } finally {
  busy = false;
  $('progress').textContent = '';
  for (const id of ['attach', 'send', 'newChat']) $(id).disabled = false;
  $('composer').elements.message.focus();
 }
}

function button(text, action, parent, primary = false) {
 const element = node('button', text, parent);
 element.type = 'button';
 if (primary) element.className = 'primary';
 element.onclick = () => guard(action);
 return element;
}

function bubble(text, role = 'assistant') {
 if ($('welcome')) $('welcome').remove();
 const element = node('div', text, $('chatlog'));
 element.className = 'bubble ' + role;
 scroll();
 return element;
}

function scroll() {
 $('chatlog').scrollTop = $('chatlog').scrollHeight;
}

function task(title) {
 if (activeTask) activeTask.remove();
 activeTask = node('section', undefined, $('chatlog'));
 activeTask.className = 'task';
 if (title) node('h2', title, activeTask);
 return activeTask;
}

function table(rows, columns, parent, master = false) {
 const wrapper = node('div', undefined, parent);
 wrapper.className = 'scroll' + (master ? ' master' : '');
 const result = node('table', undefined, wrapper);
 const header = node('tr', undefined, node('thead', undefined, result));
 columns.forEach(column => node('th', column, header));
 const body = node('tbody', undefined, result);
 rows.forEach(values => {
  const row = node('tr', undefined, body);
  values.forEach(value => node('td', value ?? '', row));
 });
 return result;
}

function conversationTitle(messages) {
 const prompts = messages
  .filter(message => message.role === 'user')
  .map(message => message.content.replace(/\s+/g, ' ').trim())
  .filter(text => text && !/^(?:\[.*\]|select\s+[a-z0-9_-]+|confirm|cancel)$/i.test(text));
 const greeting = /^(?:hi|hello|hey|good morning|good afternoon|good evening)[!.?]*$/i;
 const topic = prompts.find(text => !greeting.test(text)) || prompts[0];

 if (!topic) return 'New conversation';

 const characters = Array.from(topic);
 return characters.length <= 48
  ? topic
  : characters.slice(0, 47).join('').trimEnd() + '…';
}

async function refreshConversations() {
 const rows = await api('/conversations');
 const container = $('conversations');
 container.replaceChildren();

 const entries = rows.map(row => {
  const cached = conversationTitles.get(row.id);
  const item = button(
   cached?.title || 'New conversation',
   () => openConversation(row.id),
   container
  );
  if (row.id === conv) {
   item.className = 'active';
   if (cached) $('chatTitle').textContent = cached.title;
  }
  return {row, item, cached};
 });

 const unresolved = entries.filter(({row, cached}) => cached?.updated !== row.updated);
 for (let offset = 0; offset < unresolved.length; offset += 4) {
  await Promise.all(unresolved.slice(offset, offset + 4).map(async ({row, item}) => {
   try {
    const {messages} = await api('/conversations/' + row.id);
    if (!item.isConnected) return;
    const title = conversationTitle(messages);
    conversationTitles.set(row.id, {updated: row.updated, title});
    item.textContent = title;
    if (row.id === conv) $('chatTitle').textContent = title;
   } catch {
    // Keep the sidebar usable if a single conversation cannot be loaded.
   }
  }));
 }
}

async function newChat() {
 conv = Array.from(crypto.getRandomValues(new Uint32Array(4)), n => n.toString(16)).join('');
 selected = null;
 activeTask = null;
 $('chatlog').replaceChildren();
 $('chatTitle').textContent = 'New conversation';
 bubble('Hi, welcome.');
 document.body.classList.remove('sidebar-open');
 await refreshConversations();
}

async function openConversation(id) {
 conv = id;
 selected = null;
 activeTask = null;
 $('chatlog').replaceChildren();
 const data = await api('/conversations/' + id);
 data.messages.forEach(message => bubble(message.content, message.role));
 $('chatTitle').textContent = conversationTitle(data.messages);
 document.body.classList.remove('sidebar-open');
 if (data.pending) {
  renderConfirmation(data.pending);
 } else if (data.selected_id) {
  selected = await api('/employees/' + data.selected_id);
  renderEmployee(selected);
 }
 await refreshConversations();
}

async function send(text) {
 if (!conv) await newChat();
 bubble(text, 'user');
 const result = await api('/chat', {
  method: 'POST',
  body: {message: text, conversation_id: conv}
 });
 await handle(result);
 await refreshConversations();
}

async function handle(result) {
 if (result.reply) bubble(result.reply);
 if (activeTask) {
  activeTask.remove();
  activeTask = null;
 }
 if (result.action === 'confirm') renderConfirmation(result);
 if (result.employee) {
  selected = result.employee;
  renderEmployee(selected);
 } else if (result.document) {
  renderDocument(result.document);
 }
 if (result.action === 'list') {
  selected = null;
  await showMaster();
 }
 if (result.action === 'export') await downloadMaster();
 if (result.action === 'deleted') selected = null;
 if (result.action === 'import') renderImport(result);
 if (result.choices) {
  const box = task('Choose an employee');
  for (const person of result.choices) {
   button(person.name + ' · ' + person.email, () => send('select ' + person.id), box);
  }
 }
 if (result.report) {
  const box = task('Audit');
  node('p', result.report.summary, box);
  for (const issue of result.report.issues || []) node('p', issue, box);
 }
 scroll();
}

function renderConfirmation(result) {
 const box = task('Review change');
 node('pre', JSON.stringify(result.proposal, null, 2), box);
 const actions = node('div', undefined, box);
 actions.className = 'buttons';
 button('Confirm', async () => {
  const confirmed = await api('/actions/' + result.pending_id + '/confirm', {
   method: 'POST',
   body: {conversation_id: conv}
  });
  await handle(confirmed);
 }, actions, true);
 button('Cancel', () => send('cancel'), actions);
}

function renderDocument(result) {
 const box = task(result.classification.document_type.replaceAll('_', ' '));
 if (result.extraction.is_mock) {
  node('div', 'MOCK · manually annotated sample, not OCR or verified identity', box).className = 'tag';
 }
 table(
  Object.entries(result.prefill).filter(([key]) => key !== 'additional_fields'),
  ['Field', 'Prefilled value'],
  box
 );
}

function renderEmployee(person) {
 const box = task(person.name);
 node('p', person.email + ' · ' + person.phone, box).className = 'dim';
 const mocked = (person.documents || []).some(document => document.extraction?.is_mock);
 if (mocked) node('div', 'MOCK data · not verified identity', box).className = 'tag';
 if (person.workflow) {
  node('p', person.workflow.next_step + ' · ' +
   person.workflow.government_types.length + '/2 government · ' +
   person.workflow.bank_types.length + '/1 bank', box);
 }

 const kinds = Object.keys(person.fields || {});
 if (!kinds.length) {
  node('p', 'Attach a document using +. I will classify it and fill the fields.', box);
  return;
 }

 const events = person.audit || [];
 const last = action => Math.max(-1, ...events.map((event, index) => event.action === action ? index : -1));
 const confirmed = last('fields_confirmed') > last('document_extracted');

 if (!confirmed) {
  node('p', 'Review the prefilled fields.', box);
  const form = node('form', undefined, box);
  const edited = structuredClone(person.fields);
  for (const kind of kinds) {
   node('h3', kind.replaceAll('_', ' '), form);
   for (const [key, value] of Object.entries(edited[kind])) {
    if (key === 'additional_fields') continue;
    const label = node('label', key.replaceAll('_', ' '), form);
    const field = node('input', undefined, label);
    field.value = value ?? '';
    field.oninput = () => { edited[kind][key] = field.value; };
   }
  }
  node('button', 'Confirm fields', form).className = 'primary';
  form.onsubmit = event => {
   event.preventDefault();
   guard(async () => {
    selected = await api('/employees/' + person.id + '/fields', {
     method: 'PUT',
     body: {version: person.version, fields: edited}
    });
    renderEmployee(selected);
   });
  };
 } else if (!Object.keys(person.verification || {}).length) {
  node('p', 'Fields confirmed. Run the consistency audit when ready.', box);
  button('Run audit', async () => {
   const report = await api('/employees/' + person.id + '/audit', {
    method: 'POST',
    body: {version: person.version}
   });
   bubble(report.summary);
   selected = await api('/employees/' + person.id);
   renderEmployee(selected);
  }, box, true);
 } else {
  node('p', person.verification.summary, box);
  for (const issue of person.verification.issues || []) node('p', issue, box);
  node('p', 'Use + to add the next document, or type a change.', box).className = 'dim';
 }
 scroll();
}

function renderImport(result) {
 const box = task('Review import');
 node('p', result.preview.accepted.length + ' valid · ' +
  result.preview.rejected.length + ' skipped', box);
 table(
  result.preview.accepted.map(row => [row.person.name, row.person.email, row.person.phone]),
  ['Name', 'Email', 'Phone'],
  box
 );
 for (const row of result.preview.rejected) {
  node('p', 'Row ' + row.row + ': ' + row.issues.join(' '), box);
 }
 if (result.preview.accepted.length) {
  button('Confirm import', async () => {
   await handle(await api('/imports/' + result.import_id + '/confirm', {method: 'POST'}));
  }, box, true);
 }
}

async function showMaster() {
 const data = await api('/employees/master');
 const box = task('Master employee sheet');
 button('Download Excel', downloadMaster, box);
 if (!data.rows.length) {
  node('p', 'No employees yet.', box);
  return;
 }
 const master = table(data.rows, data.columns.map(column => column.replaceAll('_', ' ')), box, true);
 Array.from(master.tBodies[0].rows).forEach((row, index) => {
  row.cells[0].replaceChildren();
  button('Open', () => send('select ' + data.rows[index][0]), row.cells[0]);
 });
}

async function downloadMaster() {
 const response = await fetch('/api/employees/export', {credentials: 'same-origin'});
 if (!response.ok) {
  if (response.status === 401) loginView();
  let data = {};
  try { data = await response.json(); } catch {}
  throw Error(data.detail || 'Download failed. Sign in and retry.');
 }
 const blob = await response.blob();
 const url = URL.createObjectURL(blob);
 const link = node('a', undefined, document.body);
 link.href = url;
 link.download = 'master_employees.xlsx';
 link.click();
 link.remove();
 setTimeout(() => URL.revokeObjectURL(url), 30000);
}

async function upload(files) {
 if (!conv) await newChat();
 for (const file of files) {
  bubble(file.name, 'user');
  const form = new FormData();
  form.append('file', file);
  const result = await api('/chat/' + conv + '/attachments', {
   method: 'POST',
   body: form
  });
  await handle(result);
  if (files.length > 1) break;
 }
 if (files.length > 1) bubble('Finish this document or import task, then attach the next file.');
 await refreshConversations();
}

async function signedIn() {
 const data = await api('/auth/session');
 csrf = data.csrf_token;
 $('loginView').hidden = true;
 $('workspace').hidden = false;
 await refreshConversations();
 if (!conv) await newChat();
}

$('loginForm').onsubmit = event => {
 event.preventDefault();
 guard(async () => {
  const data = await api('/auth/login', {
   method: 'POST',
   body: Object.fromEntries(new FormData(event.target))
  });
  csrf = data.csrf_token;
  event.target.elements.password.value = '';
  await signedIn();
 });
};

$('composer').onsubmit = event => {
 event.preventDefault();
 const field = event.target.elements.message;
 const text = field.value.trim();
 if (!text) return;
 field.value = '';
 field.style.height = 'auto';
 guard(() => send(text));
};

const input = $('composer').elements.message;
input.oninput = () => {
 input.style.height = 'auto';
 input.style.height = Math.min(input.scrollHeight, 180) + 'px';
};
input.onkeydown = event => {
 if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
  event.preventDefault();
  if (!busy) $('composer').requestSubmit();
 }
};

$('attach').onclick = () => {
 if (!busy) $('files').click();
};
$('files').onchange = event => {
 const files = Array.from(event.target.files);
 event.target.value = '';
 guard(() => upload(files), 'Reading document…');
};
$('newChat').onclick = () => guard(newChat);
$('master').onclick = () => guard(() => send('list'));
$('showMaster').onclick = () => guard(() => send('list'));
$('add').onclick = () => guard(() => send('add'));

$('logout').onclick = () => guard(async () => {
 await api('/auth/logout', {method: 'POST'});
 conv = '';
 selected = null;
 activeTask = null;
 $('chatlog').replaceChildren();
 loginView();
});

$('account').onclick = () => guard(async () => {
 const box = task('Change password');
 const form = node('form', undefined, box);
 for (const [name, title] of [
  ['old_password', 'Current password'],
  ['new_password', 'New password (16+ characters)']
 ]) {
  const label = node('label', title, form);
  const field = node('input', undefined, label);
  field.type = 'password';
  field.name = name;
  field.required = true;
  field.autocomplete = name === 'old_password' ? 'current-password' : 'new-password';
  if (name === 'new_password') field.minLength = 16;
 }
 const submit = node('button', 'Change password', form);
 submit.className = 'primary';
 form.onsubmit = event => {
  event.preventDefault();
  guard(async () => {
   await api('/auth/password', {
    method: 'POST',
    body: Object.fromEntries(new FormData(form))
   });
   conv = '';
   loginView();
  });
 };
 scroll();
});

$('menu').onclick = () => document.body.classList.add('sidebar-open');
$('closeSidebar').onclick = () => document.body.classList.remove('sidebar-open');

let drag = 0;
document.addEventListener('dragenter', event => {
 if (Array.from(event.dataTransfer?.types || []).includes('Files')) {
  event.preventDefault();
  drag++;
  if (!$('workspace').hidden) $('dropHint').hidden = false;
 }
});
document.addEventListener('dragover', event => {
 if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault();
});
document.addEventListener('dragleave', () => {
 if (--drag <= 0) {
  drag = 0;
  $('dropHint').hidden = true;
 }
});
document.addEventListener('drop', event => {
 event.preventDefault();
 drag = 0;
 $('dropHint').hidden = true;
 if (!$('workspace').hidden) {
  guard(() => upload(Array.from(event.dataTransfer?.files || [])), 'Reading document…');
 }
});

(async () => {
 try {
  await signedIn();
 } catch (error) {
  if (!/sign in/i.test(error.message)) notice(error.message);
 }
})();