"use strict";

const get = (id) => document.getElementById(id);
const elements = Object.fromEntries([
  "access", "access-title", "access-description", "access-status", "login-form", "password-form",
  "setup-signout", "workspace", "sidebar", "expand-sidebar", "collapse-sidebar", "new-chat",
  "new-chat-keys", "history", "avatar", "account-name", "account-role", "signout", "agent-toggle",
  "agent-list", "stream", "welcome", "suggestions", "messages", "chat-status", "pending-file",
  "file-name", "file-caption", "document-label", "document-type", "upload-file", "remove-file",
  "composer", "action-toggle", "actions", "action-items", "prompt", "send", "picker",
].map((id) => [id, get(id)]));

const roles = { owner: "Owner", hr_admin: "HR Admin", employee: "Employee" };
const statusLabels = {
  draft: "Draft", submitted: "Submitted", onboarded: "Onboarded", offboarded: "Offboarded",
};
const documentTypes = {
  PAN_CARD: "PAN card", AADHAAR_CARD: "Aadhaar", BANK_PASSBOOK: "Bank passbook", CHEQUE: "Cheque",
};
const narrow = window.matchMedia("(max-width: 680px)");
let session = null;
let activeThread = null;
let threads = [];
let pendingFile = null;
let busy = false;

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
  for (const id of ["new-chat", "action-toggle", "signout", "setup-signout"]) {
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
    updateControls();
  }
}

function clearSession() {
  session = null;
  activeThread = null;
  threads = [];
  clearFile();
  elements.history.replaceChildren();
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
  setSidebar(!narrow.matches);
  buildActions();
  renderThread();
  await refreshHistory();
}

function setSidebar(open) {
  elements.workspace.classList.toggle("sidebar-closed", !open);
  elements["expand-sidebar"].setAttribute("aria-expanded", String(open));
}

function togglePopover(toggleId, panelId, open) {
  elements[panelId].hidden = !open;
  elements[toggleId].setAttribute("aria-expanded", String(open));
}

function closePopovers() {
  togglePopover("agent-toggle", "agent-list", false);
  togglePopover("action-toggle", "actions", false);
}

function renderHistory() {
  const history = elements.history;
  history.replaceChildren();
  if (!threads.length) {
    history.append(node("p", "Your conversations will appear here.", "history-empty"));
  }
  for (const thread of threads) {
    const item = button(thread.title, () => perform(async () => {
      if (thread.id === activeThread?.id) {
        if (narrow.matches) setSidebar(false);
        return;
      }
      const selected = await api("/api/conversations/" + encodeURIComponent(thread.id));
      clearFile();
      setActive(selected);
      if (narrow.matches) setSidebar(false);
    }, "Opening chat…"), "history-item");
    item.title = thread.title;
    if (activeThread?.id === thread.id) item.setAttribute("aria-current", "page");
    history.append(item);
  }
}

async function refreshHistory() {
  const result = await api("/api/conversations");
  threads = Array.isArray(result) ? result : result.conversations || result.threads || [];
  renderHistory();
}

function setActive(thread) {
  activeThread = thread.conversation || thread.thread || thread;
  const { id, title, updated_at } = activeThread;
  threads = [{ id, title, updated_at }, ...threads.filter((item) => item.id !== id)]
    .sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  renderHistory();
  renderThread();
}

function newChat() {
  if (busy || !session) return;
  activeThread = null;
  clearFile();
  status();
  renderHistory();
  renderThread();
  if (narrow.matches) setSidebar(false);
  elements.prompt.focus();
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

function extractionPanel(section, record) {
  if (!/^[a-f0-9]{24}$/i.test(record.id || "")) return;
  const preview = node("div", undefined, "extraction-preview");
  const show = button("Review extracted fields", () => perform(async () => {
    if (preview.childElementCount) {
      preview.replaceChildren();
      show.textContent = "Review extracted fields";
      show.setAttribute("aria-expanded", "false");
      return;
    }
    const path = "/api/onboarding/employees/" + encodeURIComponent(record.id);
    const detail = await api(path);
    for (const document of detail.documents || []) {
      const values = Object.entries(document.extraction?.extracted_data || {})
        .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
        .map(([field, value]) => [field.replaceAll("_", " "), value]);
      const group = node("details");
      group.append(node("summary", documentTypes[document.kind] || document.kind));
      if (values.length) writeFields(group, values);
      else group.append(node("p", "No extracted fields available."));
      preview.append(group);
    }
    if (!preview.childElementCount) preview.append(node("p", "No documents have been uploaded."));
    show.textContent = "Hide extracted fields";
    show.setAttribute("aria-expanded", "true");
  }, "Loading extracted fields…"));
  show.setAttribute("aria-expanded", "false");
  section.append(show, preview);
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
    section.append(node("p", `Document checklist · ${government}/2 government · ${bank}/1 bank`));
  }
  if (full) {
    for (const document of record.documents || []) {
      if (!/^[a-f0-9-]{1,64}$/i.test(document.id || "")) continue;
      const label = documentTypes[document.kind] || document.kind;
      const link = node("a", label);
      link.href = "/api/onboarding/documents/" + encodeURIComponent(document.id);
      const line = node("p");
      line.append(link);
      if (document.extraction?.status) line.append(" · " + document.extraction.status);
      section.append(line);
    }
    for (const check of record.name_checks || []) {
      section.append(node("p", `${documentTypes[check.type] || check.type} · ${check.result}`));
    }
    if (session.user.role !== "employee") extractionPanel(section, record);
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
  if (active) {
    const controls = node("div", undefined, "draft-controls");
    const confirm = node("button", "Review invitation", "primary");
    confirm.type = "submit";
    controls.append(confirm, button("Cancel", () => sendTurn("Cancel", { action: "cancel" })));
    form.append(controls);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      sendTurn("Review employee details", {
        action: "add", draft_id: data.id, fields: Object.fromEntries(new FormData(form)),
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
  list.replaceChildren();
  list.hidden = !messages.length;
  elements.welcome.hidden = Boolean(messages.length);
  messages.forEach((message, index) => {
    const mine = message.role === "user";
    const turn = node("article", undefined, "turn " + (mine ? "user" : "assistant"));
    if (!mine) turn.append(node("p", "Onboarding Agent", "turn-label"));
    turn.append(node("p", message.text, "turn-text"));
    if (message.data) {
      const result = renderResult(message.data, index);
      if (result) turn.append(result);
    }
    list.append(turn);
  });
  elements.stream.scrollTop = elements.stream.scrollHeight;
}

function sendTurn(text, options = {}, clearPrompt = false) {
  return perform(async () => {
    closePopovers();
    const id = await ensureThread();
    const result = await api("/api/conversations/" + encodeURIComponent(id) + "/turn", {
      method: "POST", body: { text, ...options },
    });
    if (clearPrompt) {
      elements.prompt.value = "";
      resizePrompt();
    }
    setActive(result);
  }, "Working on your request…");
}

function buildActions() {
  const plus = elements["action-items"];
  const suggestions = elements.suggestions;
  plus.replaceChildren();
  suggestions.replaceChildren();
  const employee = session.user.role === "employee";
  const actions = employee ? [
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
  for (const label of employee ? ["My checklist", "Upload document"] : ["Add employee", "Show submissions", "Review documents"]) {
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
    setActive(result);
    clearFile();
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
elements["new-chat"].addEventListener("click", newChat);
elements["expand-sidebar"].addEventListener("click", () => setSidebar(true));
elements["collapse-sidebar"].addEventListener("click", () => setSidebar(false));
elements["agent-toggle"].addEventListener("click", () => {
  const open = elements["agent-list"].hidden;
  closePopovers();
  togglePopover("agent-toggle", "agent-list", open);
});
elements["action-toggle"].addEventListener("click", () => {
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
  if (session && !elements.workspace.hidden && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    newChat();
  }
});
narrow.addEventListener("change", () => setSidebar(!narrow.matches));

elements["new-chat-keys"].textContent = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘ K" : "Ctrl K";

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
