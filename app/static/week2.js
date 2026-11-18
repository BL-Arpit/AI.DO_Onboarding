'use strict';

const byId = id => document.getElementById(id);
const panel = byId('panel');
const employeeDialog = byId('add-employee');
const employeeForm = byId('add-employee-form');
const employeeError = byId('add-employee-error');
let inviting = false;
let user;
let csrf = '';
let busy = false;

function append(parent, tag, text) {
  const element = document.createElement(tag);
  element.textContent = text || '';
  parent.append(element);
  return element;
}

async function api(path, method = 'GET', data) {
  const headers = {};
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
  if (data && !(data instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    data = JSON.stringify(data);
  }
  const response = await fetch('/api' + path, { method, headers, body: data, credentials: 'same-origin' });
  const result = await response.json();
  if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Check the entered values and try again.');
  return result;
}

async function run(action) {
  if (busy) return;
  busy = true;
  const notice = byId(user ? 'notice' : 'login-notice');
  notice.textContent = 'Working…';
  try {
    await action();
    notice.textContent = '';
  } catch (error) {
    notice.textContent = error.message;
  } finally {
    busy = false;
  }
}

function button(parent, label, action) {
  const control = append(parent, 'button', label);
  control.type = 'button';
  control.onclick = () => run(action);
  return control;
}

function say(text, mine = false) {
  byId('welcome').hidden = true;
  const chat = byId('chat');
  chat.hidden = false;
  append(chat, 'p', text).classList.toggle('user', mine);
  chat.scrollTop = chat.scrollHeight;
}

function box(title) {
  byId('welcome').hidden = true;
  panel.replaceChildren();
  const section = append(panel, 'section');
  append(section, 'h2', title);
  return section;
}

function form(parent, fields, label, action) {
  const element = append(parent, 'form');
  for (const field of fields) {
    const input = append(append(element, 'label', field.label), 'input');
    input.name = field.name;
    input.type = field.type || 'text';
    input.value = field.value || '';
    input.required = true;
    if (field.min) input.minLength = field.min;
    if (field.disabled) input.disabled = true;
    if (field.accept) input.accept = field.accept;
  }
  append(element, 'button', label).className = 'primary';
  element.onsubmit = event => {
    event.preventDefault();
    const data = new FormData(element);
    run(() => action(data));
  };
  return element;
}

function report(result) {
  for (const item of result.invitations) {
    say(item.email + (item.email_accepted ? ' · invitation accepted by mail service' : ' · invitation email failed. For employees, open Submissions to resend.'));
  }
}

const contact = [
  { name: 'name', label: 'Name' },
  { name: 'email', label: 'Email', type: 'email' },
  { name: 'phone', label: 'Phone', type: 'tel', min: 8 },
];

const types = [
  ['PAN', 'PAN_CARD'], ['Aadhaar', 'AADHAAR_CARD'],
  ['Bank passbook', 'BANK_PASSBOOK'], ['Cheque', 'CHEQUE'],
];

function documents(parent, person, review = false) {
  const latest = new Map(person.documents.map(doc => [doc.kind, doc]));
  for (const [kind, doc] of latest) {
    const block = append(parent, 'details');
    append(block, 'summary', types.find(item => item[1] === kind)?.[0] || kind);
    const link = append(block, 'a', 'Download original');
    link.href = '/api/week2/documents/' + doc.id;
    for (const [field, value] of Object.entries(doc.extraction.extracted_data || {})) {
      if (value && typeof value === 'string') append(block, 'p', field.replaceAll('_', ' ') + ' · ' + value);
    }
    if (review) {
      const check = person.name_checks.find(item => item.type === kind);
      if (check) append(block, 'p', 'Name check · ' + check.result);
    }
  }
}

async function profile() {
  const person = await api('/week2/me');
  const section = box('Your profile');
  append(section, 'p', person.email + ' · ' + person.status);
  const flow = person.workflow;
  append(section, 'p', flow.government_types.length + '/2 government · ' + flow.bank_types.length + '/1 bank');
  if (person.status === 'draft' || person.status === 'onboarded') {
    form(section, [
      { ...contact[0], value: person.name, disabled: person.status === 'onboarded' },
      { ...contact[2], value: person.phone },
    ], 'Save profile', async data => {
      const fields = Object.fromEntries(data);
      if (!fields.name) fields.name = person.name;
      await api('/week2/me', 'PUT', fields);
      await profile();
    });
  }
  documents(section, person);
  if (person.status !== 'draft') return;
  const upload = append(section, 'form');
  const select = append(append(upload, 'label', 'Document type'), 'select');
  select.name = 'document_type';
  for (const [label, value] of types) append(select, 'option', label).value = value;
  const file = append(append(upload, 'label', 'Document'), 'input');
  file.name = 'file';
  file.type = 'file';
  file.required = true;
  file.accept = 'image/jpeg,image/png,image/webp,application/pdf';
  append(upload, 'button', 'Upload document');
  upload.onsubmit = event => {
    event.preventDefault();
    run(async () => {
      await api('/week2/me/documents', 'POST', new FormData(upload));
      await profile();
    });
  };
  if (flow.government_types.length >= 2 && flow.bank_types.length) {
    button(section, 'Submit for review', async () => {
      await api('/week2/me/submit', 'POST', { version: person.version });
      await profile();
    });
  }
}

async function employeeList(submitted) {
  const rows = await api('/week2/employees?submitted=' + submitted);
  const section = box(submitted ? 'Ready for review' : 'Submissions');
  const status = { draft: 'Awaiting submission', submitted: 'Submitted', onboarded: 'Onboarded' };
  if (!rows.length) append(section, 'p', 'No employees in this list.');
  for (const person of rows) {
    const row = append(section, 'div');
    row.className = 'row';
    button(row, person.name, async () => {
      const detail = await api('/week2/employees/' + person.id);
      const details = box(detail.name);
      append(details, 'p', detail.email + ' · ' + detail.phone + ' · ' + status[detail.status]);
      documents(details, detail, true);
      button(details, 'Back to list', () => employeeList(submitted));
    });
    append(row, 'span', status[person.status] || person.status);
    const change = async action => {
      await api('/week2/employees/' + person.id + '/' + action, 'POST', { version: person.version });
      await employeeList(submitted);
    };
    if (person.status === 'submitted') {
      button(row, 'Onboard', () => change('onboard'));
      button(row, 'Request correction', () => change('reopen'));
    }
    if (person.status === 'draft') button(row, 'Resend invitation', async () => {
      report(await api('/week2/employees/' + person.id + '/resend', 'POST'));
    });
    button(row, 'Delete / Offboard', async () => {
      if (window.confirm('Offboard ' + person.name + ' and revoke access immediately?')) await change('offboard');
    });
  }
  if (!submitted) append(section, 'a', 'Download master Excel').href = '/api/week2/export';
}

async function command(value) {
  const text = value.trim();
  if (!text) return;
  const normalized = text.toLowerCase().replace(/[?!.]+$/, '');
  if (user.must_change) {
    say('Set a new password to continue.');
    return;
  }
  if (['owner', 'hr_admin'].includes(user.role) && /^(?:add|add (?:an? )?(?:employee|person))$/.test(normalized)) {
    employeeForm.reset();
    employeeError.hidden = true;
    employeeDialog.showModal();
    return;
  }
  say(text, true);
  if (user.role === 'employee') {
    if (/profile|bio|upload|submit|document/.test(normalized)) return profile();
    return say('Open Profile to edit your details, upload documents or submit for review.');
  }
  if (['add list', 'import employee list'].includes(normalized)) {
    form(box('Upload employee list'), [{ name: 'file', label: 'Excel with Name, Email, Phone', type: 'file', accept: '.xls,.xlsx' }], 'Preview', async data => {
      const preview = await api('/week2/import/preview', 'POST', data);
      const section = box('Review invitations');
      for (const row of preview.rejected) append(section, 'p', 'Row ' + row.row + ' · ' + row.issues.join(' '));
      for (const row of preview.accepted) append(section, 'p', row.person.name + ' · ' + row.person.email);
      const pending = preview.accepted.map(row => row.person);
      if (pending.length) button(section, 'Send invitations', async () => {
        while (pending.length) {
          report(await api('/week2/import', 'POST', { people: pending.slice(0, 20) }));
          pending.splice(0, 20);
        }
        await employeeList(false);
      });
    });
  } else if (/\bverify\b|ready for review|review documents/.test(normalized)) {
    await employeeList(true);
  } else if (/\bsubmissions?\b|^list$/.test(normalized)) {
    await employeeList(false);
  } else if (user.role === 'owner' && /^(appoint hr|add hr|resend hr)$/.test(normalized)) {
    form(box('Invite HR admin'), contact.slice(0, 2), 'Invite', async data => {
      report(await api('/week2/admins', 'POST', Object.fromEntries(data)));
    });
  } else {
    say('Try add, add list, submissions or verify.' + (user.role === 'owner' ? ' Use appoint hr to invite an HR admin.' : ''));
  }
}

const sidebar = byId('sidebar');
const menu = byId('menu');

function toggleMenu(open) {
  sidebar.classList.toggle('is-open', open);
  menu.setAttribute('aria-expanded', String(open));
}

function workspaceLink(label, icon, action, selected = false) {
  const nav = byId('workspace-nav');
  const link = button(nav, label, async () => {
    toggleMenu(false);
    await action();
    nav.querySelector('[aria-current]')?.removeAttribute('aria-current');
    link.setAttribute('aria-current', 'page');
  });
  const mark = document.createElement('span');
  mark.setAttribute('aria-hidden', 'true');
  mark.textContent = icon;
  link.prepend(mark);
  if (selected) link.setAttribute('aria-current', 'page');
}

function showWorkspace() {
  panel.replaceChildren();
  byId('chat').hidden = true;
  byId('welcome').hidden = false;
  byId('composer').elements.command.focus();
}

menu.onclick = () => toggleMenu(!sidebar.classList.contains('is-open'));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && sidebar.classList.contains('is-open')) {
    toggleMenu(false);
    menu.focus();
  }
});

async function start() {
  const session = await api('/auth/session');
  user = session.user;
  csrf = session.csrf_token;
  byId('login').hidden = true;
  byId('workspace').hidden = false;
  sidebar.hidden = false;
  menu.hidden = false;
  byId('identity').textContent = user.name;
  byId('avatar').textContent = user.name.trim().slice(0, 1).toUpperCase();
  const roleNames = { owner: 'Owner', hr_admin: 'HR Admin', employee: 'Employee' };
  byId('account-role').textContent = roleNames[user.role] || user.role;
  const shortcuts = byId('shortcuts');
  shortcuts.replaceChildren();
  if (user.must_change) {
    byId('composer').hidden = true;
    form(box('Change temporary password'), [
      { name: 'old_password', label: 'Temporary password', type: 'password' },
      { name: 'new_password', label: 'New password (16+ characters)', type: 'password', min: 16 },
    ], 'Change password', async data => {
      await api('/auth/password', 'POST', Object.fromEntries(data));
      location.reload();
    });
    return;
  }
  const attach = byId('attach');
  if (user.role === 'employee') {
    workspaceLink('My onboarding', '◇', profile, true);
    attach.onclick = () => run(async () => {
      const file = panel.querySelector('input[type=file]');
      if (file) file.click();
      else await profile();
    });
    await profile();
  } else {
    byId('pinned-tools').hidden = false;
    const name = user.name.trim().split(/\s+/)[0];
    byId('greeting').textContent = name ? 'Welcome, ' + name + '.' : 'Welcome to AI.DO.';
    showWorkspace();
    workspaceLink(user.role === 'owner' ? 'Owner Workspace' : 'HR Workspace', '▣', showWorkspace, true);
    workspaceLink('Submissions & Queue', '☷', () => employeeList(false));
    workspaceLink('Document Review', '◇', () => employeeList(true));
    for (const label of ['Add employee', 'View submissions', 'Review documents']) {
      button(shortcuts, label, () => command(label));
    }
    const suggestions = byId('suggested-commands');
    button(suggestions, 'Import employee list', () => command('add list'));
    button(suggestions, 'See who is ready for review', () => command('verify'));
    if (user.role === 'owner') button(suggestions, 'Appoint HR admin', () => command('appoint hr'));
    attach.onclick = () => run(async () => {
      await command('add list');
      panel.querySelector('input[type=file]')?.focus();
    });
  }
}

byId('add-employee-cancel').onclick = () => employeeDialog.close();
byId('add-employee-close').onclick = () => employeeDialog.close();
employeeForm.onreset = () => {
  employeeError.hidden = true;
  employeeForm.elements.name.focus();
};
employeeDialog.oncancel = event => {
  if (inviting) event.preventDefault();
};
employeeDialog.onclose = () => {
  byId('composer').elements.command.focus();
};
employeeForm.onsubmit = async event => {
  event.preventDefault();
  if (inviting) return;
  const data = Object.fromEntries(new FormData(employeeForm));
  const controls = employeeDialog.querySelectorAll('input, button');
  const submit = employeeForm.querySelector('button[type=submit]');
  inviting = true;
  employeeError.hidden = true;
  controls.forEach(control => { control.disabled = true; });
  submit.textContent = 'Sending…';
  try {
    const result = await api('/week2/employees', 'POST', data);
    employeeDialog.close();
    panel.replaceChildren();
    report(result);
  } catch (error) {
    employeeError.textContent = error.message;
    employeeError.hidden = false;
  } finally {
    inviting = false;
    controls.forEach(control => { control.disabled = false; });
    submit.textContent = 'Create and invite';
  }
};

byId('login-form').onsubmit = event => {
  event.preventDefault();
  run(async () => {
    await api('/auth/login', 'POST', Object.fromEntries(new FormData(event.target)));
    event.target.reset();
    await start();
  });
};
byId('composer').onsubmit = event => {
  event.preventDefault();
  if (busy) return;
  const field = event.target.elements.command;
  const text = field.value;
  field.value = '';
  run(() => command(text));
};
byId('logout').onclick = () => run(async () => {
  await api('/auth/logout', 'POST');
  location.reload();
});
start().catch(error => {
  if (user) byId('notice').textContent = error.message;
});
