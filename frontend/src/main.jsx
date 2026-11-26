import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUp,
  Plus,
  X,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  LogOut,
  Paperclip,
  FileText,
  Users,
  UserPlus,
  Check,
  ArrowRight,
  Upload,
  Building2,
  ShieldCheck,
  Sparkles,
  Copy,
  CheckCheck,
  Settings2,
  MoreHorizontal,
  AlertCircle,
} from "lucide-react";
import "./style.css";

const TYPES = {
  PAN_CARD: "PAN card",
  AADHAAR_CARD: "Aadhaar",
  BANK_PASSBOOK: "Bank passbook",
  CHEQUE: "Cancelled cheque",
};
const ROLES = {
  super_admin: "Forward engineer",
  owner: "Owner",
  hr_admin: "HR admin",
  employee: "Employee",
};
const formValues = (form) => Object.fromEntries(new FormData(form));
function Mark({ large = false }) {
  return (
    <span className={"mark " + (large ? "large" : "")}>
      <Sparkles size={large ? 26 : 16} strokeWidth={1.5} />
    </span>
  );
}
function Btn({ children, primary = false, className = "", ...props }) {
  return (
    <button
      type="button"
      className={(primary ? "btn primary" : "btn") + " " + className}
      {...props}
    >
      {children}
    </button>
  );
}
function Field({ label, ...props }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input {...props} />
    </label>
  );
}
function ErrorLine({ text }) {
  return text ? (
    <div className="error-line" role="alert">
      <AlertCircle size={16} />
      <span>{text}</span>
    </div>
  ) : null;
}
async function request(path, { method = "GET", body, csrf, signal } = {}) {
  const headers = { Accept: "application/json" };
  if (csrf && method !== "GET") headers["X-CSRF-Token"] = csrf;
  if (body && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const response = await fetch(path, {
    method,
    body,
    headers,
    credentials: "same-origin",
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const e = new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Could not complete this request.",
    );
    e.status = response.status;
    throw e;
  }
  return data;
}
function App() {
  const [session, setSession] = useState(null),
    [loading, setLoading] = useState(true),
    [thread, setThread] = useState(null);
  const [fields, setFields] = useState([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [prompt, setPrompt] = useState("");
  const [menu, setMenu] = useState(false),
    [account, setAccount] = useState(false),
    [agent, setAgent] = useState(false);
  const [file, setFile] = useState(null),
    [kind, setKind] = useState(""),
    [pending, setPending] = useState(null),
    [fresh, setFresh] = useState(-1);
  const [inspector, setInspector] = useState(null),
    [drag, setDrag] = useState(false),
    [orgs, setOrgs] = useState(null);
  const input = useRef(),
    scroll = useRef(),
    textarea = useRef(),
    lock = useRef(false),
    nearBottom = useRef(true),
    menuRef = useRef();
  const api = (path, options = {}) =>
    request(path, { ...options, csrf: session?.csrf_token });
  const role = session?.user.role,
    employee = role === "employee";
  useEffect(() => {
    const close = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target))
        setMenu(false);
    };
    const key = (e) => {
      if (e.key === "Escape") {
        setMenu(false);
        setAccount(false);
        setAgent(false);
        setInspector(null);
        setOrgs(null);
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", key);
    };
  }, []);
  async function start(details) {
    setSession(details);
    if (details.user.must_change) return;
    const opt = { csrf: details.csrf_token };
    const [list, config] = await Promise.all([
      request("/api/conversations", opt),
      request("/api/organizations/current", opt),
    ]);
    setFields(config.fields || []);
    let current;
    if (list.conversations?.length)
      current = await request(
        "/api/conversations/" + list.conversations[0].id,
        opt,
      );
    else
      current = await request("/api/conversations", { ...opt, method: "POST" });
    if (details.user.role === "owner" && !current.messages.length)
      current = await request("/api/conversations/" + current.id + "/turn", {
        ...opt,
        method: "POST",
        body: {
          text: "Configure onboarding",
          organization_id: details.user.tenant_id,
        },
      });
    setThread(current);
  }
  useEffect(() => {
    request("/api/auth/session")
      .then(start)
      .catch((e) => {
        if (e.status !== 401) setError(e.message);
      })
      .finally(() => setLoading(false));
  }, []);
  async function perform(fn) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
      if (e.status === 401) {
        setSession(null);
        setThread(null);
        setInspector(null);
      }
    } finally {
      lock.current = false;
      setBusy(false);
      setPending(null);
    }
  }
  function reveal(current) {
    setThread(current);
    setFresh(current.messages.length - 1);
  }
  async function send(text, extra = {}) {
    if (!thread || !text.trim()) return;
    await perform(async () => {
      setMenu(false);
      setPending(text);
      nearBottom.current = true;
      setPrompt("");
      const result = await api("/api/conversations/" + thread.id + "/turn", {
        method: "POST",
        body: { text, ...extra },
      });
      reveal(result);
      if (role === "owner" && !result.active_setup)
        setFields((await api("/api/organizations/current")).fields || []);
    });
  }
  useEffect(() => {
    if (nearBottom.current)
      scroll.current?.scrollTo({
        top: scroll.current.scrollHeight,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      });
  }, [thread, pending]);
  function chooseFile(selected) {
    if (!selected) return;
    const allowed = employee ? /\.(pdf|png|jpe?g|webp)$/i : /\.xlsx?$/i;
    if (!allowed.test(selected.name)) {
      setError(
        employee
          ? "Choose an image or PDF document."
          : "Choose an Excel workbook.",
      );
      return;
    }
    setFile(selected);
    setKind("");
    setMenu(false);
  }
  async function upload() {
    if (!file || !thread) return;
    const body = new FormData();
    body.set("file", file);
    if (kind) body.set("document_type", kind);
    await perform(async () => {
      setPending("Attached " + file.name);
      nearBottom.current = true;
      const current = await api(
        "/api/conversations/" + thread.id + "/attachment",
        { method: "POST", body },
      );
      reveal(current);
      setFile(null);
      const record = current.messages.at(-1)?.data?.profile;
      if (employee && record?.documents?.length)
        await openRecord(record, record.documents.at(-1));
    });
  }
  async function openRecord(person, doc) {
    const record = await api(
      employee
        ? "/api/onboarding/me"
        : "/api/onboarding/employees/" + person.id,
    );
    setInspector({
      person: record,
      doc:
        record.documents?.find((d) => d.id === doc?.id) ||
        record.documents?.at(-1) ||
        null,
    });
  }
  async function older() {
    await perform(async () => {
      const page = await api(
        "/api/conversations/" + thread.id + "/older?before=" + thread.offset,
      );
      nearBottom.current = false;
      setThread({
        ...thread,
        offset: page.offset,
        messages: [...page.messages, ...thread.messages],
      });
      setFresh(-1);
    });
  }
  const ownerSetup = () =>
    send("Configure onboarding", { organization_id: session.user.tenant_id });
  const actions =
    role === "super_admin"
      ? [
          ["Invite owner", UserPlus, () => send("Invite owner")],
          [
            "Configure organization",
            Settings2,
            () =>
              perform(async () => {
                setOrgs(await api("/api/organizations"));
                setMenu(false);
              }),
          ],
        ]
      : employee
        ? [
            ["Upload document", Paperclip, () => input.current.click()],
            [
              "My profile & checklist",
              ShieldCheck,
              () => send("My checklist", { action: "profile" }),
            ],
            [
              "Submit for review",
              CheckCheck,
              () => send("Submit for review", { action: "submit" }),
            ],
          ]
        : [
            [
              "Add employee",
              UserPlus,
              () => send("Add employee", { action: "add" }),
            ],
            ["Upload employee list", Upload, () => input.current.click()],
            [
              "View submissions",
              Users,
              () => send("Show submissions", { action: "submissions" }),
            ],
            [
              "Review documents",
              ShieldCheck,
              () => send("Review documents", { action: "review" }),
            ],
            [
              "Export master sheet",
              FileText,
              () => send("Export master Excel", { action: "export" }),
            ],
            ...(role === "owner"
              ? [
                  [
                    "Invite HR admin",
                    UserPlus,
                    () => send("Appoint HR", { action: "appoint" }),
                  ],
                  [
                    "HR team",
                    Users,
                    () => send("Show HR list", { action: "hr_list" }),
                  ],
                  ["Configure onboarding", Settings2, ownerSetup],
                ]
              : []),
          ];
  if (loading)
    return (
      <div className="app-loading">
        <Mark />
        <span>Opening your workspace</span>
      </div>
    );
  if (!session || session.user.must_change)
    return (
      <Access
        change={Boolean(session)}
        error={error}
        busy={busy}
        onSubmit={(values) =>
          perform(async () => {
            if (session) {
              await api("/api/auth/password", { method: "POST", body: values });
              setSession(null);
              setThread(null);
            } else {
              const auth = await request("/api/auth/login", {
                method: "POST",
                body: values,
              });
              await start(
                await request("/api/auth/session", { csrf: auth.csrf_token }),
              );
            }
          })
        }
      />
    );
  const suggestions =
    role === "super_admin"
      ? ["Invite an owner"]
      : employee
        ? ["My checklist", "Upload a document"]
        : ["Add an employee", "Show submissions", "Find an employee"];
  const messages = thread?.messages || [];
  return (
    <div className={"app " + (inspector ? "with-inspector" : "")}>
      <section className="chat-shell">
        <header className="topbar">
          <div className="brand-group">
            <span className="wordmark">AI.DO</span>
            <span className="brand-divider" />
            <div className="agent-control">
              <button className="agent-button" onClick={() => setAgent(!agent)}>
                Onboarding <ChevronDown size={14} />
              </button>
              {agent && (
                <div className="agent-menu">
                  <Mark />
                  <div>
                    <strong>Onboarding agent</strong>
                    <small>Employee onboarding & document review</small>
                  </div>
                  <Check size={15} />
                </div>
              )}
            </div>
          </div>
          <div className="account-control">
            <button
              className="account-button"
              aria-label="Account menu"
              onClick={() => setAccount(!account)}
            >
              <span className="avatar">
                {session.user.name
                  ?.split(/\s+/)
                  .slice(0, 2)
                  .map((n) => n[0])
                  .join("") || "A"}
              </span>
              <span className="account-copy">
                <strong>{session.user.name}</strong>
                <small>{ROLES[role]}</small>
              </span>
              <ChevronDown size={13} />
            </button>
            {account && (
              <div className="account-menu">
                <span>{session.user.email}</span>
                <button
                  onClick={() =>
                    perform(async () => {
                      await api("/api/auth/logout", { method: "POST" });
                      setSession(null);
                      setThread(null);
                      setInspector(null);
                      setAccount(false);
                    })
                  }
                >
                  <LogOut size={15} />
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>
        <div
          ref={scroll}
          className="chat-scroll"
          onScroll={(e) => {
            const t = e.currentTarget;
            nearBottom.current =
              t.scrollHeight - t.scrollTop - t.clientHeight < 140;
          }}
        >
          {!messages.length && !pending ? (
            <div className="welcome">
              <Mark large />
              <p className="eyebrow">YOUR ONBOARDING WORKSPACE</p>
              <h1>
                What can I help
                <br />
                you move forward?
              </h1>
              <p className="welcome-copy">
                {role === "super_admin"
                  ? "Invite an owner, then shape their onboarding process together."
                  : employee
                    ? "Your documents, details and next steps. All in one conversation."
                    : "Bring people onboard, from the first invitation to the final review."}
              </p>
              <div className="starter-grid">
                {suggestions.map((s, i) => (
                  <button
                    key={s}
                    disabled={busy}
                    onClick={() =>
                      s.toLowerCase().startsWith("upload")
                        ? input.current.click()
                        : send(s)
                    }
                  >
                    <span>{s}</span>
                    {i === 0 ? (
                      <UserPlus size={17} />
                    ) : (
                      <ArrowRight size={17} />
                    )}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="message-list">
              {thread?.offset > 0 && (
                <button className="older" disabled={busy} onClick={older}>
                  Load earlier messages
                </button>
              )}
              {messages.map((message, i) => (
                <Message
                  key={(thread.offset || 0) + i}
                  message={message}
                  fresh={i === fresh}
                  onResize={() => {
                    if (nearBottom.current)
                      scroll.current?.scrollTo({
                        top: scroll.current.scrollHeight,
                      });
                  }}
                >
                  {message.data && (
                    <Result
                      data={message.data}
                      active={
                        message.data.type === "schema_choice"
                          ? i === messages.length - 1
                          : message.data.id ===
                            (["setup", "owner_invite"].includes(
                              message.data.type,
                            )
                              ? thread.active_setup
                              : message.data.type === "employee_draft"
                                ? thread.active_draft
                                : thread.active_confirmation)
                      }
                      role={role}
                      busy={busy}
                      fields={fields}
                      send={send}
                      choose={() => input.current.click()}
                      open={(person, doc) =>
                        perform(() => openRecord(person, doc))
                      }
                    />
                  )}
                </Message>
              ))}
              {pending && (
                <>
                  <Message message={{ role: "user", text: pending }} />
                  <div className="assistant-message pending" role="status">
                    <Mark />
                    <span className="thinking">
                      <i />
                      <i />
                      <i />
                    </span>
                    <span>Thinking</span>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
        <footer className="composer-region">
          {orgs && (
            <section className="organization-picker">
              <div className="card-heading">
                <h3>Select organization</h3>
                <button
                  className="icon-button"
                  aria-label="Close organization list"
                  onClick={() => setOrgs(null)}
                >
                  <X size={16} />
                </button>
              </div>
              {orgs.map((o) => (
                <button
                  key={o.id}
                  onClick={() => {
                    setOrgs(null);
                    send("Configure " + o.name, { organization_id: o.id });
                  }}
                >
                  <Building2 size={15} />
                  {o.name}
                  <ArrowRight size={15} />
                </button>
              ))}
            </section>
          )}
          <ErrorLine text={error} />
          {file && (
            <div className="file-chip">
              <FileText size={20} />
              <div>
                <strong>{file.name}</strong>
                <span>
                  {(file.size / 1024).toFixed(0)} KB · Ready to upload
                </span>
              </div>
              {employee && (
                <select
                  aria-label="Document type"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  <option value="">Auto-detect</option>
                  {Object.entries(TYPES).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              )}
              <Btn primary disabled={busy} onClick={upload}>
                Upload
              </Btn>
              <button
                className="icon-button"
                aria-label="Remove attachment"
                disabled={busy}
                onClick={() => setFile(null)}
              >
                <X size={16} />
              </button>
            </div>
          )}
          <form
            className={"composer " + (drag ? "dragging" : "")}
            onSubmit={(e) => {
              e.preventDefault();
              if (!busy) send(prompt);
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              if (e.dataTransfer.files.length > 1)
                setError("Attach one file at a time.");
              else chooseFile(e.dataTransfer.files[0]);
            }}
          >
            <div className="plus-control" ref={menuRef}>
              <button
                className={"plus-button " + (menu ? "open" : "")}
                type="button"
                disabled={busy}
                aria-expanded={menu}
                aria-label="Actions and attachments"
                onClick={() => setMenu(!menu)}
              >
                <Plus size={22} />
              </button>
              {menu && (
                <div className="action-menu">
                  {actions.map(([label, Icon, action]) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => {
                        setMenu(false);
                        action();
                      }}
                    >
                      <Icon size={17} />
                      <span>{label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <textarea
              ref={textarea}
              rows={1}
              value={prompt}
              maxLength={3000}
              placeholder="Message Onboarding…"
              aria-label="Message Onboarding"
              disabled={busy}
              onChange={(e) => {
                setPrompt(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height =
                  Math.min(e.target.scrollHeight, 150) + "px";
              }}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  if (prompt.trim() && !busy) send(prompt);
                }
              }}
            />
            <button
              className="send-button"
              type="submit"
              aria-label="Send message"
              disabled={busy || !prompt.trim()}
            >
              {busy ? <span className="send-spinner" /> : <ArrowUp size={20} />}
            </button>
          </form>
          <p className="composer-note">
            Review employee details and original documents before approving.
          </p>
          <input
            ref={input}
            type="file"
            hidden
            accept={employee ? ".pdf,.png,.jpg,.jpeg,.webp" : ".xls,.xlsx"}
            onChange={(e) => {
              chooseFile(e.target.files[0]);
              e.target.value = "";
            }}
          />
        </footer>
      </section>
      {inspector && (
        <Inspector
          key={inspector.person.id + ":" + inspector.doc?.id}
          {...inspector}
          employee={employee}
          busy={busy}
          api={api}
          perform={perform}
          onClose={() => setInspector(null)}
          onUpdate={(person) => setInspector({ ...inspector, person })}
        />
      )}
    </div>
  );
}
function Access({ change, error, busy, onSubmit }) {
  return (
    <div className="access-page">
      <div className="access-wordmark">AI.DO</div>
      <div className="access-card">
        <Mark large />
        <h1>{change ? "Make it yours." : "Welcome back."}</h1>
        <p>
          {change
            ? "Choose your password to open your workspace."
            : "Your people. Your process. One conversation."}
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit(formValues(e.currentTarget));
          }}
        >
          {change ? (
            <>
              <Field
                label="Temporary password"
                name="old_password"
                type="password"
                autoComplete="current-password"
                required
              />
              <Field
                label="New password"
                name="new_password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                required
              />
            </>
          ) : (
            <>
              <Field
                label="Email address"
                name="email"
                type="email"
                placeholder="you@company.com"
                autoComplete="username"
                required
              />
              <Field
                label="Password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </>
          )}
          <ErrorLine text={error} />
          <button className="btn primary" disabled={busy}>
            {busy ? "Please wait…" : change ? "Set password" : "Continue"}
            <ArrowRight size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}
function Message({ message, fresh, children, onResize }) {
  const [shown, setShown] = useState(message.text),
    [copied, setCopied] = useState(false);
  useEffect(() => {
    if (
      !fresh ||
      message.role === "user" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      setShown(message.text);
      return;
    }
    let n = 0;
    const words = message.text.match(/\S+\s*/g) || [];
    setShown("");
    const timer = setInterval(() => {
      n += 4;
      setShown(words.slice(0, n).join(""));
      onResize?.();
      if (n >= words.length) clearInterval(timer);
    }, 18);
    return () => clearInterval(timer);
  }, [fresh, message.text]);
  const mine = message.role === "user";
  return (
    <article
      className={
        (mine ? "user-message" : "assistant-message") + (fresh ? " arrive" : "")
      }
    >
      {!mine && <Mark />}
      <div className="message-body">
        <p className="message-text">{shown}</p>
        {children}
        {!mine && message.text && (
          <button
            className="copy-button"
            aria-label="Copy response"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(message.text);
                setCopied(true);
                setTimeout(() => setCopied(false), 1800);
              } catch {
                setCopied(false);
              }
            }}
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        )}
      </div>
    </article>
  );
}
function Result({ data, active, role, busy, fields, send, choose, open }) {
  const confirm = () =>
    send("Confirm", { action: "confirm", confirmation_id: data.id });
  const cancel = () =>
    send("Cancel", { action: "cancel", confirmation_id: data.id });
  const confirmation = (
    <div className="card-actions">
      <Btn primary disabled={busy} onClick={confirm}>
        <Check size={15} />
        Confirm
      </Btn>
      <Btn disabled={busy} onClick={cancel}>
        Cancel
      </Btn>
    </div>
  );
  switch (data.type) {
    case "owner_invite":
      return active ? (
        <InlineForm
          title="Invite the owner"
          subtitle="Send their invitation. Configure the schema afterward."
          busy={busy}
          cancel={cancel}
          submit={(v) =>
            send("Invite " + v.name, {
              draft_id: data.id,
              setup: {
                name: v.company,
                owner: { name: v.name, email: v.email },
              },
            })
          }
        >
          <Field
            label="Company name"
            name="company"
            placeholder="Company or organization"
            maxLength={160}
            required
          />
          <div className="form-grid">
            <Field
              label="Owner name"
              name="name"
              placeholder="Full name"
              maxLength={120}
              required
            />
            <Field
              label="Owner email"
              name="email"
              type="email"
              placeholder="owner@company.com"
              required
            />
          </div>
        </InlineForm>
      ) : null;
    case "employee_draft":
      return active ? (
        <InlineForm
          title="New employee"
          subtitle="Check the details before sending their invitation."
          busy={busy}
          cancel={cancel}
          submit={(v) => {
            const metadata = {};
            fields
              .filter(
                (f) =>
                  !["name", "email", "phone", "client", "track"].includes(
                    f.key,
                  ),
              )
              .forEach((f) => {
                const value = v["meta." + f.key];
                delete v["meta." + f.key];
                if (f.type === "boolean") metadata[f.key] = value === "on";
                else if (value)
                  metadata[f.key] = f.type === "number" ? Number(value) : value;
              });
            send("Review employee details", {
              action: "add",
              draft_id: data.id,
              fields: { ...v, metadata },
            });
          }}
        >
          <Field
            label="Full name"
            name="name"
            defaultValue={data.fields?.name || ""}
            required
            maxLength={120}
          />
          <div className="form-grid">
            <Field
              label="Email address"
              type="email"
              name="email"
              defaultValue={data.fields?.email || ""}
              required
            />
            <Field
              label="Phone number"
              type="tel"
              name="phone"
              defaultValue={data.fields?.phone || ""}
              required
            />
          </div>
          {fields
            .filter(
              (f) =>
                !["name", "email", "phone", "client", "track"].includes(f.key),
            )
            .map((f) => (
              <Field
                key={f.key}
                label={f.label}
                name={"meta." + f.key}
                type={
                  { date: "date", number: "number", boolean: "checkbox" }[
                    f.type
                  ] || "text"
                }
                required={f.type !== "boolean" && f.required}
                defaultValue={data.fields?.metadata?.[f.key]}
              />
            ))}
          {Object.values(data.errors || {}).map((e, i) => (
            <ErrorLine key={i} text={e} />
          ))}
        </InlineForm>
      ) : null;
    case "setup":
      if (!data.organization)
        return (
          <Result
            data={{ ...data, type: "owner_invite" }}
            active={active}
            role={role}
            busy={busy}
            fields={fields}
            send={send}
            choose={choose}
            open={open}
          />
        );
      return active ? (
        <SchemaForm
          key={data.id}
          data={data}
          send={send}
          busy={busy}
          cancel={cancel}
        />
      ) : null;
    case "schema_choice":
      return (
        <Card>
          <Delivery invitations={data.invitations} />
          {active && (
            <div className="schema-options">
              <button disabled={busy} onClick={choose}>
                <Upload size={20} />
                <strong>Upload a sheet</strong>
                <span>Use your existing employee columns</span>
                <ArrowRight size={16} />
              </button>
              <button
                disabled={busy}
                onClick={() => send("Create schema in chat")}
              >
                <Sparkles size={20} />
                <strong>Create through chat</strong>
                <span>Describe the fields and documents</span>
                <ArrowRight size={16} />
              </button>
            </div>
          )}
        </Card>
      );
    case "confirmation":
      return active ? (
        <Card>
          <div className="card-heading">
            <span className="soft-icon">
              <Check size={17} />
            </span>
            <h3>Ready to proceed?</h3>
          </div>
          <p className="muted">{data.summary}</p>
          {confirmation}
        </Card>
      ) : null;
    case "invitations":
      return (
        <Card>
          <h3>Invitation delivery</h3>
          <Delivery invitations={data.invitations} />
        </Card>
      );
    case "employee":
    case "profile":
      return (
        <Person
          person={data.employee || data.profile}
          role={role}
          busy={busy}
          send={send}
          open={open}
        />
      );
    case "employees":
      return (
        <Card>
          <div className="card-heading">
            <Users size={18} />
            <h3>Employees</h3>
            <span className="count">{data.employees?.length || 0}</span>
          </div>
          {!data.employees?.length ? (
            <p className="muted">No employees to show.</p>
          ) : (
            data.employees.map((person) => (
              <button
                className="employee-row"
                key={person.id}
                disabled={busy}
                onClick={() =>
                  send("Show " + person.email, { action: "status" })
                }
              >
                <span className="person-avatar">{person.name?.[0]}</span>
                <span>
                  <strong>{person.name}</strong>
                  <small>{person.email}</small>
                </span>
                <Badge status={person.status} />
                <ChevronRight size={16} />
              </button>
            ))
          )}
        </Card>
      );
    case "hr_admins":
      return (
        <Card>
          <div className="card-heading">
            <ShieldCheck size={18} />
            <h3>HR team</h3>
          </div>
          {data.admins?.length ? (
            data.admins.map((a) => (
              <div className="employee-row" key={a.id}>
                <span className="person-avatar">{a.name?.[0]}</span>
                <span>
                  <strong>{a.name}</strong>
                  <small>{a.email}</small>
                </span>
                <Badge status={a.status} />
              </div>
            ))
          ) : (
            <p className="muted">No HR administrators found.</p>
          )}
        </Card>
      );
    case "import":
      return (
        <Card>
          <div className="card-heading">
            <FileText size={18} />
            <h3>Review employee list</h3>
          </div>
          <p className="muted">{data.accepted || 0} valid rows</p>
          {(data.rejected || []).map((r, i) => (
            <ErrorLine
              key={i}
              text={"Row " + r.row + " · " + r.issues.join(", ")}
            />
          ))}
          {active && data.id && confirmation}
        </Card>
      );
    case "export":
      return data.href === "/api/onboarding/export" ? (
        <Card>
          <a className="btn" href={data.href}>
            <FileText size={16} />
            Download master Excel
          </a>
        </Card>
      ) : null;
    case "upload":
      return (
        <Btn onClick={choose} disabled={busy}>
          <Paperclip size={16} />
          Choose document
        </Btn>
      );
    default:
      return null;
  }
}
function Card({ children }) {
  return <section className="result-card">{children}</section>;
}
function InlineForm({ title, subtitle, children, submit, cancel, busy }) {
  return (
    <Card>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!busy) submit(formValues(e.currentTarget));
        }}
      >
        <div className="card-heading">
          <span className="soft-icon">
            <UserPlus size={17} />
          </span>
          <h3>{title}</h3>
        </div>
        <p className="card-subtitle">{subtitle}</p>
        <fieldset disabled={busy} className="form-fields">
          {children}
        </fieldset>
        <div className="card-actions">
          <button className="btn primary" disabled={busy}>
            Review invitation
            <ArrowRight size={15} />
          </button>
          <Btn onClick={cancel} disabled={busy}>
            Cancel
          </Btn>
        </div>
      </form>
    </Card>
  );
}
function Delivery({ invitations = [] }) {
  return invitations.map((i, n) => (
    <div key={i.email + n} className="delivery">
      <span className={i.email_accepted ? "success-icon" : "failure-icon"}>
        {i.email_accepted ? (
          <CheckCheck size={17} />
        ) : (
          <AlertCircle size={17} />
        )}
      </span>
      <span>
        <strong>{i.email}</strong>
        <small>
          {i.email_accepted
            ? "Accepted by Gmail"
            : "Delivery failed — check email setup"}
        </small>
      </span>
    </div>
  ));
}
function Badge({ status }) {
  const labels = {
    draft: "Awaiting submission",
    submitted: "Ready for review",
    onboarded: "Onboarded",
    active: "Active",
    password_change_required: "Invited",
  };
  return (
    <span className={"badge " + status}>
      {labels[status] || status?.replaceAll("_", " ")}
    </span>
  );
}
function Person({ person, role, busy, send, open }) {
  const [editing, setEditing] = useState(false);
  if (!person) return null;
  return (
    <Card>
      <div className="card-heading">
        <span className="person-avatar">{person.name?.[0]}</span>
        <div className="person-title">
          <h3>{person.name}</h3>
          <small>{person.email}</small>
        </div>
        <Badge status={person.status} />
      </div>
      <dl className="detail-grid">
        {[
          ["Phone", person.phone],
          ["Client", person.client],
          ["Track", person.track],
        ]
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
      </dl>
      {person.workflow && (
        <div className="checklist">
          <span>
            <ShieldCheck size={15} />
            {person.workflow.government_types.length}/
            {person.workflow.minimum_government} government documents
          </span>
          <span>
            <FileText size={15} />
            {person.workflow.bank_types.length}/{person.workflow.minimum_bank}{" "}
            bank proof
          </span>
        </div>
      )}
      <div className="document-list">
        {person.documents?.map((doc) => (
          <button
            key={doc.id}
            disabled={busy}
            onClick={() => open(person, doc)}
          >
            <span className="file-icon">
              <FileText size={17} />
            </span>
            <span>
              <strong>{TYPES[doc.kind] || doc.kind}</strong>
              <small>Open original & extracted fields</small>
            </span>
            <ChevronRight size={16} />
          </button>
        ))}
      </div>
      {role === "employee" && (
        <>
          <Btn disabled={busy} onClick={() => setEditing(!editing)}>
            Edit my details
          </Btn>
          {editing && (
            <form
              className="form-fields compact-edit"
              onSubmit={(e) => {
                e.preventDefault();
                const v = formValues(e.currentTarget);
                send("Change my name to " + v.name + ", phone to " + v.phone);
              }}
            >
              <Field
                name="name"
                label="Full name"
                defaultValue={person.name}
                required
              />
              <Field
                name="phone"
                label="Phone"
                defaultValue={person.phone}
                required
              />
              <button className="btn primary" disabled={busy}>
                Review changes
              </button>
            </form>
          )}
        </>
      )}
      {["owner", "hr_admin"].includes(role) &&
        person.status === "submitted" && (
          <div className="card-actions">
            <Btn
              primary
              disabled={busy}
              onClick={() =>
                send("Onboard " + person.email, { action: "onboard" })
              }
            >
              <Check size={15} />
              Approve onboarding
            </Btn>
            <Btn
              disabled={busy}
              onClick={() =>
                send("Reopen " + person.email, { action: "reopen" })
              }
            >
              Request correction
            </Btn>
          </div>
        )}
      {["owner", "hr_admin"].includes(role) && (
        <details className="quiet-details">
          <summary>More actions</summary>
          <Btn
            disabled={busy}
            onClick={() =>
              send("Offboard " + person.email, { action: "offboard" })
            }
          >
            Offboard employee
          </Btn>
        </details>
      )}
    </Card>
  );
}
function SchemaForm({ data, send, busy, cancel }) {
  const [schema, setSchema] = useState(() => structuredClone(data.schema));
  function fieldChange(index, key, value) {
    setSchema((old) => ({
      ...old,
      fields: old.fields.map((f, i) =>
        i === index ? { ...f, [key]: value } : f,
      ),
    }));
  }
  return (
    <Card>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const rename_fields = {};
          data.schema.fields.forEach((f, i) => {
            if (f.key !== schema.fields[i].key)
              rename_fields[f.key] = schema.fields[i].key;
          });
          send("Review schema change", {
            draft_id: data.id,
            setup: {
              expected_version: data.organization.version,
              schema_definition: schema,
              rename_fields,
            },
          });
        }}
      >
        <div className="card-heading">
          <span className="soft-icon">
            <Settings2 size={17} />
          </span>
          <h3>Onboarding requirements</h3>
        </div>
        <p className="card-subtitle">
          {data.organization?.name} · Review the fields and documents your
          employees provide.
        </p>
        <fieldset disabled={busy} className="form-fields">
          <div className="form-grid">
            {[
              ["government_minimum", "Government documents"],
              ["bank_minimum", "Bank documents"],
            ].map(([k, label]) => (
              <Field
                key={k}
                label={label}
                type="number"
                min={0}
                max={2}
                value={schema[k]}
                onChange={(e) =>
                  setSchema({ ...schema, [k]: Number(e.target.value) })
                }
                required
              />
            ))}
          </div>
          {[
            ["government_types", ["PAN_CARD", "AADHAAR_CARD"]],
            ["bank_types", ["BANK_PASSBOOK", "CHEQUE"]],
          ].map(([group, kinds]) => (
            <div key={group} className="checkbox-row">
              {kinds.map((k) => (
                <label key={k}>
                  <input
                    type="checkbox"
                    checked={schema[group].includes(k)}
                    onChange={(e) =>
                      setSchema({
                        ...schema,
                        [group]: e.target.checked
                          ? [...schema[group], k]
                          : schema[group].filter((x) => x !== k),
                      })
                    }
                  />
                  {TYPES[k]}
                </label>
              ))}
            </div>
          ))}
          <details className="quiet-details">
            <summary>
              Employee fields <span>{schema.fields.length}</span>
            </summary>
            <div className="schema-fields">
              {schema.fields.map((f, i) => (
                <div key={i}>
                  <Field
                    label={f.label}
                    value={f.key}
                    disabled={[
                      "name",
                      "email",
                      "phone",
                      "client",
                      "track",
                    ].includes(f.key)}
                    onChange={(e) => fieldChange(i, "key", e.target.value)}
                  />
                  <select
                    aria-label={f.label + " type"}
                    value={f.type}
                    disabled={[
                      "name",
                      "email",
                      "phone",
                      "client",
                      "track",
                    ].includes(f.key)}
                    onChange={(e) => fieldChange(i, "type", e.target.value)}
                  >
                    {["text", "number", "date", "boolean"].map((t) => (
                      <option key={t}>{t}</option>
                    ))}
                  </select>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={f.required}
                      onChange={(e) =>
                        fieldChange(i, "required", e.target.checked)
                      }
                    />
                    Required
                  </label>
                </div>
              ))}
            </div>
          </details>
        </fieldset>
        <div className="card-actions">
          <button className="btn primary" disabled={busy}>
            Review schema
            <ArrowRight size={15} />
          </button>
          <Btn onClick={cancel} disabled={busy}>
            Cancel
          </Btn>
        </div>
      </form>
    </Card>
  );
}
function Inspector({
  person,
  doc,
  employee,
  busy,
  api,
  perform,
  onClose,
  onUpdate,
}) {
  const [page, setPage] = useState(1),
    [pages, setPages] = useState(1),
    [image, setImage] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [tab, setTab] = useState("fields");
  const ref = useRef(),
    close = useRef();
  useEffect(() => {
    const previous = document.activeElement;
    close.current?.focus();
    return () => previous?.focus();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let blob;
    if (!doc) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    fetch("/api/onboarding/documents/" + doc.id + "/preview?page=" + page, {
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (r) => {
        if (!r.ok) {
          const d = await r.json();
          throw new Error(d.detail || "Preview unavailable");
        }
        setPages(Number(r.headers.get("X-Page-Count")) || 1);
        blob = URL.createObjectURL(await r.blob());
        if (!controller.signal.aborted) setImage(blob);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      if (blob) URL.revokeObjectURL(blob);
    };
  }, [doc?.id, page]);
  const original = doc?.extraction?.extracted_data || {};
  const latest =
    person.documents?.filter((d) => d.kind === doc?.kind).at(-1)?.id ===
    doc?.id;
  const editable = ["draft", "submitted"].includes(person.status) && latest;
  const values = latest ? person.fields?.[doc?.kind] || original : original;
  const check = person.name_checks?.find((c) => c.type === doc?.kind);
  return (
    <aside
      className="inspector"
      role="dialog"
      aria-label="Document inspector"
      ref={ref}
      onKeyDown={(e) => {
        if (e.key === "Tab") {
          const focusable = [
            ...ref.current.querySelectorAll("button,input,textarea,select,a"),
          ].filter((n) => !n.disabled && n.offsetParent !== null);
          if (e.shiftKey && document.activeElement === focusable[0]) {
            e.preventDefault();
            focusable.at(-1)?.focus();
          } else if (
            !e.shiftKey &&
            document.activeElement === focusable.at(-1)
          ) {
            e.preventDefault();
            focusable[0]?.focus();
          }
        }
      }}
    >
      <header className="inspector-header">
        <div>
          <span className="eyebrow">DOCUMENT INSPECTOR</span>
          <h2>{TYPES[doc?.kind] || "Employee documents"}</h2>
        </div>
        <button
          ref={close}
          className="icon-button"
          aria-label="Close document inspector"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </header>
      <div className="inspector-scroll">
        <div className="inspector-person">
          <span className="person-avatar">{person.name?.[0]}</span>
          <div>
            <strong>{person.name}</strong>
            <small>{person.email}</small>
          </div>
          <Badge status={person.status} />
        </div>
        <div className="preview-toolbar">
          <span>
            <FileText size={14} />
            Original document
          </span>
          <div>
            <button
              className="icon-button"
              aria-label="Previous page"
              disabled={page <= 1 || loading}
              onClick={() => setPage(page - 1)}
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              {page} / {pages}
            </span>
            <button
              className="icon-button"
              aria-label="Next page"
              disabled={page >= pages || loading}
              onClick={() => setPage(page + 1)}
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
        <div className="preview-surface">
          {loading ? (
            <div className="preview-loading">
              <span className="send-spinner" />
              Loading document
            </div>
          ) : error ? (
            <ErrorLine text={error} />
          ) : image ? (
            <img src={image} alt={TYPES[doc?.kind] + " original document"} />
          ) : (
            <span>No document attached.</span>
          )}
        </div>
        <div className="tabs">
          <button
            className={tab === "fields" ? "selected" : ""}
            onClick={() => setTab("fields")}
          >
            Extracted fields
          </button>
          <button
            className={tab === "changes" ? "selected" : ""}
            onClick={() => setTab("changes")}
          >
            Change history <span>{person.revisions?.length || 0}</span>
          </button>
        </div>
        {tab === "fields" ? (
          <>
            <p className="inspector-hint">
              Compare each value with the original before saving.
            </p>
            <form
              className="form-fields"
              key={person.version}
              onSubmit={(e) => {
                e.preventDefault();
                const fields = formValues(e.currentTarget);
                perform(async () => {
                  const result = await api(
                    "/api/onboarding/employees/" + person.id + "/fields",
                    {
                      method: "POST",
                      body: {
                        version: person.version,
                        fields: { [doc.kind]: fields },
                      },
                    },
                  );
                  onUpdate(result);
                });
              }}
            >
              {Object.entries(values)
                .filter(
                  ([, v]) =>
                    v === null ||
                    ["string", "number", "boolean"].includes(typeof v),
                )
                .map(([k, v]) => (
                  <div key={k} className="inspector-field">
                    <Field
                      label={k.replaceAll("_", " ")}
                      name={k}
                      defaultValue={v ?? ""}
                      disabled={!editable || busy}
                    />
                    {String(original[k] ?? "") !== String(v ?? "") && (
                      <small>
                        Original OCR · {String(original[k] ?? "Blank")}
                      </small>
                    )}
                  </div>
                ))}
              {editable && Object.keys(values).length > 0 && (
                <button className="btn primary" disabled={busy}>
                  Save reviewed fields
                  <Check size={15} />
                </button>
              )}
            </form>
            {check && (
              <section
                className={
                  "name-check " + (check.review_required ? "attention" : "")
                }
              >
                <div>
                  <ShieldCheck size={17} />
                  <strong>
                    {check.review_required ? "Name needs review" : "Name check"}
                  </strong>
                </div>
                <p>
                  {check.prompt ||
                    check.reason?.replaceAll("_", " ") ||
                    check.result}
                </p>
                {!employee &&
                  editable &&
                  check.reason === "middle_name_difference" && (
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        const v = formValues(e.currentTarget);
                        perform(async () =>
                          onUpdate(
                            await api(
                              "/api/onboarding/employees/" +
                                person.id +
                                "/name-review",
                              {
                                method: "POST",
                                body: {
                                  version: person.version,
                                  document_type: doc.kind,
                                  reason: v.reason,
                                  decision: e.nativeEvent.submitter.value,
                                },
                              },
                            ),
                          ),
                        );
                      }}
                    >
                      <textarea
                        name="reason"
                        aria-label="Name review reason"
                        placeholder="Record your review decision…"
                        minLength={5}
                        required
                      />
                      <div className="card-actions">
                        <button
                          className="btn primary"
                          value="accepted"
                          disabled={busy}
                        >
                          Accept name
                        </button>
                        <button
                          className="btn"
                          value="rejected"
                          disabled={busy}
                        >
                          Request correction
                        </button>
                      </div>
                    </form>
                  )}
              </section>
            )}
          </>
        ) : (
          <div className="revision-list">
            {person.revisions?.length ? (
              person.revisions.map((r, i) => (
                <section key={i}>
                  <div className="revision-heading">
                    <strong>{r.action.replaceAll("_", " ")}</strong>
                    <small>{new Date(r.created).toLocaleDateString()}</small>
                  </div>
                  {(r.changes || [])
                    .filter(
                      (c) => !c.document_type || c.document_type === doc?.kind,
                    )
                    .map((c, j) => (
                      <div className="revision-row" key={j}>
                        <span>{c.field.replaceAll("_", " ")}</span>
                        <div>
                          <small>Before</small>
                          <p>{String(c.before ?? "Blank")}</p>
                        </div>
                        <div>
                          <small>After</small>
                          <p>{String(c.after ?? "Blank")}</p>
                        </div>
                      </div>
                    ))}
                  {r.reason && <p className="muted">{r.reason}</p>}
                </section>
              ))
            ) : (
              <p className="muted">No edits recorded yet.</p>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
createRoot(document.getElementById("root")).render(<App />);
