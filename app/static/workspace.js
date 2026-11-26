"use strict";

const get = (id) => document.getElementById(id);
const elements = Object.fromEntries([
  "access", "access-title", "access-description", "access-status", "login-form", "password-form",
  "setup-signout", "workspace", "avatar", "account-name", "account-role", "signout", "agent-toggle",
  "agent-list", "stream", "welcome", "suggestions", "messages", "chat-status", "pending-file",
  "file-name", "file-caption", "document-label", "document-type", "upload-file", "remove-file",
  "composer", "action-toggle", "actions", "action-items", "prompt", "send", "picker",
  "document-drawer", "preview-title", "close-preview", "previous-page", "next-page", "page-position",
  "preview-status", "document-image", "review-fields",
].map((id) => [id, get(id)]));

const roles = { super_admin: "Forward engineer", owner: "Owner", hr_admin: "HR Admin", employee: "Employee" };
const statusLabels = {
  draft: "Draft", submitted: "Submitted", onboarded: "Onboarded", offboarded: "Offboarded",
};
const documentTypes = {
  PAN_CARD: "PAN card", AADHAAR_CARD: "Aadhaar", BANK_PASSBOOK: "Bank passbook", CHEQUE: "Cheque",
};
const narrow = window.matchMedia("(max-width: 680px)");
let session = null;
let activeThread = null;
let customerFields = [];
let preview = null;
let previewUrl = null;
let previewSequence = 0;
let pendingFile = null;
let busy = false;
let animateReply = false;
let revealController = null;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");


function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(svg.namespaceURI, "use");
  use.setAttribute("href", "/assets/workspace-icons.svg#" + name);
  svg.append(use);
  return svg;
}

function button(text, handler, className = "inline-action") {
  const item = node("button", text, className);
  item.type = "button";
  item.addEventListener("click", handler);
  return item;
}

async function api(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  if (method !== "GET" && session) headers["X-CSRF-Token"] = session.csrf_token;
  if (body && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const response = await fetch(path, { method, body, headers, credentials: "same-origin" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "Couldn’t complete that request.";
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return data;
}

function status(text = "", error = false) {
  const target = elements.workspace.hidden ? elements["access-status"] : elements["chat-status"];
  target.hidden = !text;
  target.textContent = text;
  target.classList.toggle("error", error);
}

function updateControls() {
  elements.send.disabled = busy || !elements.prompt.value.trim();
  elements["upload-file"].disabled = busy;
  elements["remove-file"].disabled = busy;
  elements["document-type"].disabled = busy;
  elements.prompt.readOnly = busy;
  for (const id of ["action-toggle", "signout", "setup-signout"]) {
    elements[id].disabled = busy;
  }
  for (const form of [elements["login-form"], elements["password-form"]]) {
    form.querySelector("[type=submit]").disabled = busy;
  }
  elements.workspace.setAttribute("aria-busy", String(busy));
}

async function perform(task, waiting = "") {
  if (busy) return;
  const wasSignedIn = Boolean(session);
  busy = true;
  updateControls();
  status(waiting);
  try {
    await task();
    status();
  } catch (error) {
    if (error.status === 401 && wasSignedIn && !elements.workspace.hidden) {
      clearSession();
      status("Your session expired. Sign in again to continue.", true);
    } else {
      status(error.message || "Couldn’t complete that request. Try again.", true);
    }
  } finally {
    busy = false;
    document.querySelector(".thinking-turn")?.remove();
    updateControls();
  }
}

function clearSession() {
  session = null;
  activeThread = null;
  closePreview();
  clearFile();

  elements.messages.replaceChildren();
  elements.prompt.value = "";
  elements["account-name"].textContent = "";
  elements["account-role"].textContent = "";
  elements.avatar.textContent = "";
  elements["login-form"].reset();
  elements["password-form"].reset();
  elements.workspace.hidden = true;
  elements.access.hidden = false;
  elements["access-title"].textContent = "Onboarding Agent";
  elements["access-description"].textContent = "Sign in to your onboarding workspace.";
  elements["login-form"].hidden = false;
  elements["password-form"].hidden = true;
  status();
}

function showPasswordSetup() {
  elements.workspace.hidden = true;
  elements.access.hidden = false;
  elements["access-title"].textContent = "Set a new password";
  elements["access-description"].textContent = "Update your temporary password to open your workspace.";
  elements["login-form"].hidden = true;
  elements["password-form"].hidden = false;
  elements["password-form"].elements.old_password.focus();
}

async function openSession(details) {
  session = details;
  if (session.user.must_change) {
    showPasswordSetup();
    return;
  }
  const name = session.user.name || session.user.email || "Account";
  elements["account-name"].textContent = name;
  elements["account-role"].textContent = roles[session.user.role] || session.user.role;
  elements.avatar.textContent = name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  elements.access.hidden = true;
  elements.workspace.hidden = false;

  customerFields = (await api("/api/organizations/current")).fields || [];
  buildActions();
  renderThread();
  const result = await api("/api/conversations");
  const saved = Array.isArray(result) ? result : result.conversations || result.threads || [];
  if (saved.length) setActive(await api("/api/conversations/" + encodeURIComponent(saved[0].id)));
  if (session.user.role === "owner" && !activeThread?.messages?.length) {
    const id = await ensureThread();
    const result = await api("/api/conversations/" + id + "/turn", {
      method:"POST",body:{text:"Configure onboarding",organization_id:session.user.tenant_id}});
    setActive(result);
  }
}

function togglePopover(toggleId, panelId, open) {
  elements[panelId].hidden = !open;
  elements[toggleId].setAttribute("aria-expanded", String(open));
}

function closePopovers() {
  togglePopover("agent-toggle", "agent-list", false);
  togglePopover("action-toggle", "actions", false);
}

function setActive(thread) {
  activeThread = thread.conversation || thread.thread || thread;
  renderThread();
}

async function ensureThread() {
  if (activeThread) return activeThread.id;
  const created = await api("/api/conversations", { method: "POST" });
  setActive(created);
  return activeThread.id;
}

function writeFields(parent, fields) {
  const list = node("dl", undefined, "fields");
  for (const [label, value] of fields) {
    if (value === undefined || value === null || value === "") continue;
    list.append(node("dt", label), node("dd", String(value)));
  }
  if (list.childElementCount) parent.append(list);
}

function closePreview() {
  previewSequence += 1;
  preview = null;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  elements["document-image"].removeAttribute("src");
  elements["document-drawer"].hidden = true;
  elements.workspace.classList.remove("review-open");
  elements["review-fields"].replaceChildren();
}

async function loadPreviewPage(page) {
  if (!preview) return;
  const sequence = ++previewSequence;
  const id = preview.document.id;
  elements["preview-status"].textContent = "Loading preview…";
  const response = await fetch("/api/onboarding/documents/" + encodeURIComponent(id) + "/preview?page=" + page, {
    credentials: "same-origin",
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || "Document preview unavailable.");
  }
  const image = await response.blob();
  if (!preview || sequence !== previewSequence) return;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(image);
  elements["document-image"].src = previewUrl;
  elements["document-image"].alt = (documentTypes[preview.document.kind] || preview.document.kind) + " page " + page;
  preview.page = page;
  preview.pages = Number(response.headers.get("X-Page-Count")) || 1;
  elements["page-position"].textContent = "Page " + page + " of " + preview.pages;
  elements["previous-page"].disabled = page <= 1;
  elements["next-page"].disabled = page >= preview.pages;
  elements["preview-status"].textContent = "";
}

function renderReviewFields(person, document) {
  const target = elements["review-fields"];
  target.replaceChildren();
  const original = document.extraction?.extracted_data || {};
  const latest = person.documents.filter(d => d.kind === document.kind).at(-1)?.id === document.id;
  const values = latest ? (person.fields?.[document.kind] || original) : original;
  const editable = ["draft","submitted"].includes(person.status) && (person.documents || []).filter(d => d.kind === document.kind).at(-1)?.id === document.id;
  const form = node("form", undefined, "review-form");
  form.append(node("h3", "Extracted fields"));
  for (const [name, value] of Object.entries(values)) {
    if (value !== null && !["string", "number", "boolean"].includes(typeof value)) continue;
    const label = node("label", name.replaceAll("_", " "));
    const input = node("input");
    input.name = name;
    input.value = value ?? "";
    input.disabled = !editable;
    label.append(node("small", "OCR · " + (original[name] ?? "Blank")), input);
    form.append(label);
  }
  const feedback = node("p", "", "review-feedback");
  feedback.setAttribute("role", "status");
  if (editable && form.querySelector("input")) {
    const save = node("button", "Save reviewed fields", "primary");
    save.type = "submit";
    form.append(save);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (busy) return;
      await perform(async () => {
        const fields = Object.fromEntries(new FormData(form));
        const result = await api("/api/onboarding/employees/" + encodeURIComponent(person.id) + "/fields", {
          method: "POST", body: {version: person.version, fields: {[document.kind]: fields}},
        });
        if (!preview || preview.person.id !== person.id) return;
        preview.person = result;
        renderReviewFields(result, result.documents.find(item => item.id === document.id) || document);
        elements["preview-status"].textContent = "Reviewed fields saved.";
      }, "Saving reviewed fields…");
    });
  }
  form.append(feedback);
  target.append(form);
  for (const revision of person.revisions || []) {
    const changes = (revision.changes || []).filter(change => !change.document_type || change.document_type === document.kind);
    if (!changes.length) continue;
    const table = node("table", undefined, "revision-table");
    const heading = table.insertRow();
    for (const label of ["Field", "Before edit", "After edit"]) heading.append(node("th", label));
    const before = revision.action === "fields_revised" ? revision.before?.[document.kind] : revision.before;
    const after = revision.action === "fields_revised" ? revision.after?.[document.kind] : revision.after;
    const comparison = before && after ? Object.keys({...before,...after}).filter(key => typeof before[key] !== "object" || before[key] === null)
      .map(field => ({field,before:before[field],after:after[field]})) : changes;
    for (const change of comparison) {
      const row = table.insertRow();
      if (change.before !== change.after) row.className = "revised-value";
      for (const value of [change.field, change.before, change.after]) row.append(node("td", value ?? "—"));
    }
    target.append(node("h3", "Review changes"), table, node("p","Compare the edited values with the original document before approving."));
  }
  const check = (person.name_checks || []).find(item => item.type === document.kind);
  if (check) {
    const block = node("section", undefined, "name-review");
    block.append(node("h3", "Name verification"), node("p", check.result));
    if (check.reason) block.append(node("p", check.reason));
    if (check.prompt) block.append(node("p", check.prompt));
    if (editable && session.user.role !== "employee" && check.reason === "middle_name_difference") {
      const reason = node("textarea");
      reason.placeholder = "Reason for your decision";
      reason.setAttribute("aria-label", "Name review reason");
      block.append(reason);
      for (const [label, decision] of [["Accept name", "accepted"], ["Request correction", "rejected"]]) {
        block.append(button(label, () => perform(async () => {
          if (!reason.value.trim()) throw new Error("Enter a reason for the name review.");
          const result = await api("/api/onboarding/employees/" + encodeURIComponent(person.id) + "/name-review", {
            method: "POST", body: {version: person.version, document_type: document.kind, decision, reason: reason.value.trim()},
          });
          if (!preview || preview.person.id !== person.id) return;
          preview.person = result;
          renderReviewFields(result, document);
        }), "inline-action"));
      }
    }
    target.append(block);
  }
}

function openDocument(person, document) {
  return perform(() => showDocument(person,document), "Opening document…");
}

async function showDocument(person, document) {
    closePreview();
    const record = session.user.role === "employee"
      ? await api("/api/onboarding/me")
      : await api("/api/onboarding/employees/" + encodeURIComponent(person.id));
    preview = {person: record, document: (record.documents || []).find(item => item.id === document.id) || document, page: 1, pages: 1};
    elements["preview-title"].textContent = documentTypes[document.kind] || document.kind;
    elements["document-drawer"].hidden = false;
    elements.workspace.classList.add("review-open");
    renderReviewFields(record, preview.document);
    await loadPreviewPage(1);
    elements["close-preview"].focus();
}

function personCard(parent, record, full) {
  if (!record) return;
  const section = node("section", undefined, "person");
  section.append(node("h3", record.name || "Employee"));
  writeFields(section, [
    ["Status", statusLabels[record.status] || record.status], ["Email", record.email],
    ["Phone", record.phone], ["Client", record.client], ["Track", record.track],
  ]);
  if (full && record.workflow) {
    const government = (record.workflow.government_types || []).length;
    const bank = (record.workflow.bank_types || []).length;
    section.append(node("p", `Document checklist · ${government}/${record.workflow.minimum_government} government · ${bank}/${record.workflow.minimum_bank} bank`));
  }
  if (full) {
    for (const document of record.documents || []) {
      if (!/^[a-f0-9-]{1,64}$/i.test(document.id || "")) continue;
      const label = documentTypes[document.kind] || document.kind;
      const line = node("p");
      line.append(button("Review " + label, () => openDocument(record, document)));
      if (document.extraction?.status) line.append(" · " + document.extraction.status);
      section.append(line);
    }
    for (const check of record.name_checks || []) {
      section.append(node("p", `${documentTypes[check.type] || check.type} · ${check.result}`));
    }

  } else if (record.email && session.user.role !== "employee") {
    section.append(button("Open record", () => sendTurn("Show " + record.email, { action: "status" })));
  }
  parent.append(section);
}

function renderDraft(container, data, active) {
  const form = node("form", undefined, "employee-draft");
  form.noValidate = true;
  form.append(node("h3", "Employee details"));
  form.append(node("p", "Check the details below before preparing the invitation.", "draft-intro"));
  const fields = [
    ["name", "Full name", "text", 120], ["email", "Work email", "email", 254],
    ["phone", "Phone", "tel", 30],
  ];
  for (const [name, label, type, maximum] of fields) {
    const field = node("label", label, "draft-field");
    const input = node("input");
    input.name = name;
    input.type = type;
    input.maxLength = maximum;
    input.placeholder = { name: "Full name", email: "name@company.com", phone: "+91 98765 43210" }[name];
    input.autocomplete = { name: "name", email: "email", phone: "tel" }[name];
    input.value = data.fields?.[name] || "";
    input.required = true;
    input.disabled = !active;
    field.append(input);
    if (data.errors?.[name]) {
      const error = node("span", data.errors[name], "draft-error");
      error.id = `draft-${data.id}-${container.dataset.messageIndex}-${name}-error`;
      input.setAttribute("aria-invalid", "true");
      input.setAttribute("aria-describedby", error.id);
      field.append(error);
    }
    form.append(field);
  }
  const custom = customerFields.filter(f => !["name","email","phone","track","client"].includes(f.key));
  for (const spec of custom) {
    const label = node("label",spec.label,"draft-field");
    const input = node("input");
    input.type = ({number:"number",date:"date",boolean:"checkbox"})[spec.type] || "text";
    input.name = "meta." + spec.key;
    input.required = spec.required && input.type !== "checkbox";
    input.disabled = !active;
    label.append(input); form.append(label);
  }
  if (active) {
    const controls = node("div", undefined, "draft-controls");
    const confirm = node("button", "Review invitation", "primary");
    confirm.type = "submit";
    controls.append(confirm, button("Cancel", () => sendTurn("Cancel", { action: "cancel" })));
    form.append(controls);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(form));
      const metadata = {};
      for (const spec of custom) {
        const key = "meta." + spec.key, value = values[key]; delete values[key];
        if (spec.type === "boolean") metadata[spec.key] = Boolean(value);
        else if (value) metadata[spec.key] = spec.type === "number" ? Number(value) : value;
      }
      sendTurn("Review employee details", {
        action: "add", draft_id: data.id, fields: {...values, metadata},
      });
    });
  }
  container.append(form);
}

function confirmationButtons(container, data, active) {
  if (!active) return;
  const actions = node("div", undefined, "draft-controls");
  actions.append(
    button("Confirm", () => sendTurn("Confirm", { action: "confirm", confirmation_id: data.id }), "primary"),
    button("Cancel", () => sendTurn("Cancel", { action: "cancel", confirmation_id: data.id })),
  );
  container.append(actions);
}

function renderResult(data, index) {
  const container = node("div", undefined, "result");
  container.dataset.messageIndex = index;
  const stateKey = data.type === "employee_draft" ? "active_draft" : "active_confirmation";
  const latest = activeThread.messages.findLastIndex((message) => message.data?.id === data.id);
  const active = Object.hasOwn(activeThread, stateKey)
    ? Boolean(data.id && data.id === activeThread[stateKey] && index === latest)
    : index === activeThread.messages.length - 1;
  switch (data.type) {
    case "owner_invite":
      if (activeThread.active_setup !== data.id || latest !== index) return null;
      renderOwnerInvite(container,data);
      break;
    case "schema_choice":
      if (index !== activeThread.messages.length - 1) return null;
      for (const invitation of data.invitations || []) container.append(node("p",
        invitation.email + (invitation.email_accepted ? " · Invitation sent" : " · Email delivery failed")));
      container.append(button("Upload employee sheet", chooseFile, "primary"),
        button("Create schema in chat", () => sendTurn("Create schema in chat")));
      break;
    case "setup":
      if (activeThread.active_setup !== data.id || latest !== index) return null;
      renderSetup(container, data);
      break;
    case "hr_admins":
      container.append(node("h3", "HR team"));
      for (const admin of data.admins || []) {
        const section = node("section", undefined, "person");
        section.append(node("h3", admin.name || "HR admin"));
        const labels = {active: "Active", disabled: "Disabled", invitation_expired: "Invitation expired", password_change_required: "Needs password change"};
        writeFields(section, [["Email", admin.email], ["Status", labels[admin.status] || admin.status]]);
        container.append(section);
      }
      if (!(data.admins || []).length) container.append(node("p", "No HR accounts found."));
      break;
    case "employee_draft":
      renderDraft(container, data, active);
      break;
    case "employee":
    case "profile":
      personCard(container, data.employee || data.profile, true);
      break;
    case "employees":
      for (const record of data.employees || []) personCard(container, record, false);
      if (!container.childElementCount) return null;
      break;
    case "invitations":
      for (const invitation of data.invitations || []) {
        container.append(node("p", `${invitation.email} · ${invitation.email_accepted ? "Accepted by Gmail" : "Delivery failed"}`));
      }
      break;
    case "confirmation":
      if (!active) return null;
      confirmationButtons(container, data, active);
      break;
    case "import":
      container.append(node("h3", "Excel import preview"));
      container.append(node("p", `${data.accepted || 0} valid rows`));
      for (const row of data.rejected || []) {
        container.append(node("p", `Row ${row.row} · ${(row.issues || []).join(", ") || "Check the workbook fields."}`));
      }
      if (data.id) confirmationButtons(container, data, active);
      break;
    case "export":
      if (data.href !== "/api/onboarding/export") return null;
      container.append(Object.assign(node("a", "Download master Excel"), { href: data.href }));
      break;
    case "upload":
      container.append(button("Choose document", chooseFile));
      break;
    default:
      return null;
  }
  return container;
}

function renderThread() {
  const messages = activeThread?.messages || [];
  const list = elements.messages;
  revealController?.abort();
  list.replaceChildren();
  list.hidden = !messages.length;
  elements.welcome.hidden = Boolean(messages.length);
  if (activeThread?.offset > 0) list.append(button("Earlier messages", () => perform(async () => {
    const page = await api("/api/conversations/" + activeThread.id + "/older?before=" + activeThread.offset);
    activeThread.messages.unshift(...page.messages); activeThread.offset = page.offset;
    renderThread(); elements.stream.scrollTop = 0;
  })));
  messages.forEach((message, index) => {
    const mine = message.role === "user";
    const turn = node("article", undefined, "turn " + (mine ? "user" : "assistant"));
    if (!mine) turn.append(node("p", "Onboarding Agent", "turn-label"));
    const text = node("p", message.text, "turn-text");
    turn.append(text);
    if (animateReply && !mine && index === messages.length - 1) {
      turn.classList.add("message-enter");
      if (!reducedMotion.matches) revealText(text, message.text);
    }
    if (message.data) {
      const result = renderResult(message.data, index);
      if (result) turn.append(result);
    }
    list.append(turn);
  });
  animateReply = false;
  scrollToLatest();
}

function sendTurn(text, options = {}, clearPrompt = false) {
  return perform(async () => {
    closePopovers();
    const id = await ensureThread();
    showPending(text);
    const result = await api("/api/conversations/" + encodeURIComponent(id) + "/turn", {
      method: "POST", body: { text, ...options },
    });
    if (clearPrompt) {
      elements.prompt.value = "";
      resizePrompt();
    }
    animateReply = true;
    setActive(result);
    if (result.active_setup === null && session.user.role === "owner")
      customerFields = (await api("/api/organizations/current")).fields || [];
  }, "");
}

function buildActions() {
  const plus = elements["action-items"];
  const suggestions = elements.suggestions;
  plus.replaceChildren();
  suggestions.replaceChildren();
  const employee = session.user.role === "employee";
  const actions = session.user.role === "super_admin" ? [["Invite owner", "profile", () => sendTurn("Invite owner")], ["Edit organization", "profile", selectOrganization]] : employee ? [
    ["Upload document", "paperclip", chooseFile],
    ["My onboarding checklist", "profile", () => sendTurn("My checklist", { action: "profile" })],
    ["Submit for review", "check", () => sendTurn("Submit for review", { action: "submit" })],
  ] : [
    ["Upload employee workbook", "sheet", chooseFile],
    ["Add employee", "employee", () => sendTurn("Add employee", { action: "add" })],
    ["View submissions", "list", () => sendTurn("Show submissions", { action: "submissions" })],
    ["Review documents", "review", () => sendTurn("Review documents", { action: "review" })],
    ["Export master Excel", "download", () => sendTurn("Export master Excel", { action: "export" })],
  ];
  if (session.user.role === "owner") {
    actions.push(["Configure onboarding", "profile", () => sendTurn("Configure onboarding", {organization_id:session.user.tenant_id})]);
    actions.push(["HR team", "profile", () => sendTurn("Show HR list", { action: "hr_list" })]);
    actions.push(["Appoint HR admin", "profile", () => sendTurn("Appoint HR", { action: "appoint" })]);
  }
  for (const [label, glyph, handler] of actions) {
    const item = button(label, () => {
      closePopovers();
      handler();
    }, "action-item");
    item.prepend(icon(glyph));
    plus.append(item);
  }
  for (const label of session.user.role === "super_admin" ? ["Configure customer"] : employee ? ["My checklist", "Upload document"] : ["Add employee", "Show submissions", "Review documents"]) {
    suggestions.append(button(label, () => sendTurn(label), "suggestion"));
  }
}

function chooseFile() {
  if (!session || busy) return;
  const picker = elements.picker;
  picker.accept = session.user.role === "employee" ? ".pdf,.png,.jpg,.jpeg,.webp" : ".xls,.xlsx";
  picker.value = "";
  picker.click();
}

function setFile(file) {
  if (!file || busy || !session) return;
  const employee = session.user.role === "employee";
  const supported = employee ? /\.(pdf|png|jpg|jpeg|webp)$/i : /\.xlsx?$/i;
  if (!supported.test(file.name)) {
    status(employee ? "Choose a PDF, PNG, JPEG or WEBP document." : "Choose an XLS or XLSX workbook.", true);
    return;
  }
  pendingFile = file;
  elements["file-name"].textContent = file.name;
  elements["file-caption"].textContent = employee ? "Ready to upload" : "Ready for import preview";
  elements["document-label"].hidden = !employee;
  elements["document-type"].replaceChildren(new Option("Detect automatically", ""));
  for (const [value, label] of Object.entries(documentTypes)) {
    elements["document-type"].append(new Option(label, value));
  }
  elements["pending-file"].hidden = false;
  status();
}

function clearFile() {
  pendingFile = null;
  elements["pending-file"].hidden = true;
  elements.picker.value = "";
}

function uploadFile() {
  if (!pendingFile) return;
  const body = new FormData();
  body.set("file", pendingFile);
  if (session.user.role === "employee" && elements["document-type"].value) {
    body.set("document_type", elements["document-type"].value);
  }
  return perform(async () => {
    const id = await ensureThread();
    const result = await api("/api/conversations/" + encodeURIComponent(id) + "/attachment", {
      method: "POST", body,
    });
    animateReply = true;
    setActive(result);
    customerFields = (await api("/api/organizations/current")).fields || [];
    clearFile();
    const record = activeThread.messages.at(-1)?.data?.profile;
    if (session.user.role === "employee" && record?.documents?.length)
      await showDocument(record,record.documents.at(-1));
  }, "Processing your attachment…");
}

function resizePrompt() {
  const prompt = elements.prompt;
  prompt.style.height = "auto";
  prompt.style.height = Math.min(130, prompt.scrollHeight) + "px";
  updateControls();
}

function signOut() {
  return perform(async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch (error) {
      if (error.status !== 401) throw error;
    }
    clearSession();
  }, "Signing out…");
}

elements["login-form"].addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form));
  perform(async () => {
    await api("/api/auth/login", { method: "POST", body });
    form.reset();
    await openSession(await api("/api/auth/session"));
  }, "Signing in…");
});

elements["password-form"].addEventListener("submit", (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.currentTarget));
  perform(async () => {
    await api("/api/auth/password", { method: "POST", body });
    clearSession();
    elements["access-description"].textContent = "Password changed. Sign in with your new password.";
  }, "Updating password…");
});

elements.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = elements.prompt.value.trim();
  if (text) sendTurn(text, {}, true);
});
elements.prompt.addEventListener("input", resizePrompt);
elements.prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    elements.composer.requestSubmit();
  }
});
elements["close-preview"].addEventListener("click", closePreview);
elements["previous-page"].addEventListener("click", () => perform(() => loadPreviewPage(preview.page - 1)));
elements["next-page"].addEventListener("click", () => perform(() => loadPreviewPage(preview.page + 1)));
elements["agent-toggle"].addEventListener("click", () => {
  const open = elements["agent-list"].hidden;
  closePopovers();
  togglePopover("agent-toggle", "agent-list", open);
});
elements["action-toggle"].addEventListener("click", () => {
  buildActions();
  const open = elements.actions.hidden;
  closePopovers();
  togglePopover("action-toggle", "actions", open);
});
elements.picker.addEventListener("change", () => setFile(elements.picker.files[0]));
elements["remove-file"].addEventListener("click", clearFile);
elements["upload-file"].addEventListener("click", uploadFile);
elements["setup-signout"].addEventListener("click", signOut);
elements.signout.addEventListener("click", signOut);

for (const target of [elements.composer, elements.stream]) {
  target.addEventListener("dragover", (event) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    elements.composer.classList.add("dragover");
  });
  target.addEventListener("dragleave", () => elements.composer.classList.remove("dragover"));
  target.addEventListener("drop", (event) => {
    if (!event.dataTransfer.files.length) return;
    event.preventDefault();
    elements.composer.classList.remove("dragover");
    if (event.dataTransfer.files.length > 1) {
      status("Attach one file at a time.", true);
      return;
    }
    setFile(event.dataTransfer.files[0]);
  });
}

document.addEventListener("click", (event) => {
  if (!event.target.closest(".agent-control") && !event.target.closest(".actions-control")) closePopovers();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closePopovers();
  if (event.key === "Escape" && preview) closePreview();
});

perform(async () => {
  try {
    await openSession(await api("/api/auth/session"));
  } catch (error) {
    if (error.status === 401) {
      clearSession();
      return;
    }
    if (!session) clearSession();
    throw error;
  }
}, "Checking your session…");

function renderSetup(container, data) {
  const form = node("form", undefined, "employee-draft");
  const schema = structuredClone(data.schema);
  form.append(node("h3", "Customer onboarding setup"), node("p", schema.fields.map(f => f.label).join(" · ")));
  if (data.organization) form.append(node("p", data.organization.name + " · version " + data.organization.version));
  for (const [key, label, type, required] of [
    ["org", "Organization", "text", true], ["owner", "Owner name", "text", true],
    ["email", "Owner email", "email", true], ["hr", "HR name (optional)", "text", false],
    ["hrEmail", "HR email (optional)", "email", false], ["government_minimum","Government documents required","number",true],
    ["bank_minimum","Bank documents required","number",true]]) {
    if (data.organization && !key.endsWith("_minimum")) continue;
    const field = node("label", label), input = node("input");
    input.name = key; input.type = type; input.required = required;
    if (type === "number") { input.min = 0; input.max = 2; input.value = schema[key]; }
    field.append(input); form.append(field);
  }
  for (const [group,choices] of [["government_types",["PAN_CARD","AADHAAR_CARD"]],["bank_types",["BANK_PASSBOOK","CHEQUE"]]]) {
    const set=node("fieldset");
    set.append(node("legend",group === "government_types" ? "Accepted government documents" : "Accepted bank proofs"));
    for (const kind of choices) {
      const label=node("label",documentTypes[kind]), box=node("input");
      box.type="checkbox"; box.checked=schema[group].includes(kind);
      box.onchange=()=> { schema[group]=box.checked ? [...schema[group],kind] : schema[group].filter(item=>item!==kind); };
      label.prepend(box);set.append(label);
    }
    form.append(set);
  }
  const definitions = node("details"); definitions.append(node("summary","Edit fields and migration mapping"));
  const rows = [];
  for (const item of schema.fields) {
    const line = node("label", item.label, "draft-field");
    const input = node("input"); input.value = item.key;
    input.disabled = ["name","email","phone","track","client"].includes(item.key);
    const select = node("select");
    for (const t of ["text","number","date","boolean"]) select.add(new Option(t,t));
    select.value=item.type; select.disabled=input.disabled;
    const required = node("input"); required.type="checkbox"; required.checked=item.required; required.disabled=input.disabled;
    line.append(input,select,node("span","Required"),required); definitions.append(line);
    rows.push({item,input,select,required,old:item.key});
  }
  form.append(definitions);
  const submit = node("button", data.organization ? "Review schema change" : "Review invitation", "primary"); submit.type = "submit"; form.append(submit);
  form.onsubmit = event => {
    event.preventDefault();
    const v = Object.fromEntries(new FormData(form));
    schema.government_minimum = Number(v.government_minimum);
    schema.bank_minimum = Number(v.bank_minimum);
    const rename_fields = {};
    for (const {item,input,select,required,old} of rows) {
      item.key=input.value.trim(); item.type=select.value; item.required=required.checked;
      if (old !== item.key) rename_fields[old]=item.key;
    }
    if (data.organization) return sendTurn("Review schema change", {draft_id:data.id, setup:{
      expected_version:data.organization.version,schema_definition:schema,rename_fields}});
    sendTurn("Review customer configuration", {draft_id:data.id,setup:{name:v.org,owner:{name:v.owner,email:v.email},
      hr:v.hr || v.hrEmail ? {name:v.hr,email:v.hrEmail} : null,schema_definition:schema}});
  };
  container.append(form);
}

async function selectOrganization() {
  return perform(async () => {
    const orgs = await api("/api/organizations");
    const list = elements.suggestions;
    list.replaceChildren();
    const panel = elements["action-items"];
    panel.replaceChildren();
    for (const org of orgs) panel.append(button(org.name, () => sendTurn("Configure " + org.name, {organization_id:org.id}), "action-item"));
    togglePopover("action-toggle","actions",true);
  });
}

function scrollToLatest() {
  elements.stream.scrollTo({top:elements.stream.scrollHeight,behavior:reducedMotion.matches ? "instant" : "smooth"});
}
function showPending(text) {
  revealController?.abort();
  elements.welcome.hidden = true;
  elements.messages.hidden = false;
  document.querySelector(".pending-message")?.remove();
  document.querySelector(".thinking-turn")?.remove();
  const user = node("article",undefined,"turn user message-enter pending-message");
  user.append(node("p",text,"turn-text"));
  const thinking = node("article",undefined,"turn assistant thinking-turn");
  thinking.setAttribute("role","status"); thinking.setAttribute("aria-label","AI.DO is thinking");
  const dots=node("span",undefined,"thinking-dots");
  for (let i=0;i<3;i++) dots.append(node("i"));
  thinking.append(dots,node("span","Thinking…","thinking-label"));
  elements.messages.append(user,thinking); scrollToLatest();
}
async function revealText(target,text) {
  const controller = new AbortController(); revealController = controller;
  target.setAttribute("aria-label",text);
  const words = text.match(/\S+\s*/g) || [];
  target.textContent = "";
  for (let i=0;i<words.length;i+=3) {
    if (controller.signal.aborted) return;
    target.textContent += words.slice(i,i+3).join("");
    if (elements.stream.scrollHeight-elements.stream.scrollTop-elements.stream.clientHeight < 180) scrollToLatest();
    await new Promise(resolve=>setTimeout(resolve,18));
  }
  target.textContent=text; target.removeAttribute("aria-label");
}
function renderOwnerInvite(container,data) {
  const form=node("form",undefined,"employee-draft owner-invite");
  form.append(node("h3","Invite the owner"),node("p","Send their login invitation. Set up the onboarding schema next.","draft-intro"));
  for (const [name,label,type] of [["org","Company name","text"],["name","Owner name","text"],["email","Owner email","email"]]) {
    const field=node("label",label,"draft-field"), input=node("input");
    input.name=name;input.type=type;input.required=true;input.maxLength=name==="email" ? 254 : 120;
    field.append(input);form.append(field);
  }
  const submit=node("button","Review invitation","primary");submit.type="submit";
  form.append(submit,button("Cancel",()=>sendTurn("Cancel",{action:"cancel"})));
  form.onsubmit=event=>{
    event.preventDefault();
    const v=Object.fromEntries(new FormData(form));
    sendTurn("Invite "+v.name,{draft_id:data.id,setup:{name:v.org,owner:{name:v.name,email:v.email}}});
  };
  container.append(form);
}
