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
    [agent, setAgent] = useState(false);
  const [file, setFile] = useState(null),
    [kind, setKind] = useState(""),
    [pending, setPending] = useState(null),
    [fresh, setFresh] = useState(-1);
  const [drag, setDrag] = useState(false),
    [orgs, setOrgs] = useState(null);
  const [requestForm, setRequestForm] = useState(false);
  const [documentPolicy, setDocumentPolicy] = useState(null);
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
        setAgent(false);
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
    setDocumentPolicy(config);
    let current;
    if (list.conversations?.length)
      current = await request(
        "/api/conversations/" + list.conversations[0].id,
        opt,
      );
    else
      current = await request("/api/conversations", { ...opt, method: "POST" });
    if (details.user.role === "employee" && !current.messages?.length) {
      current = await request("/api/conversations/" + current.id + "/turn", {...opt, method:"POST", body:{text:"Get started", action:"profile"}});
    }
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
      setRequestForm(false);
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
    if (role === "owner") {
      setError("HR adds employees and the super admin configures the schema.");
      return;
    }
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
  const oversight = [
    [
      "View submissions",
      Users,
      () => send("Show submissions", { action: "submissions" }),
    ],
    [
      "Employee requests",
      CheckCheck,
      () => send("Show requests", { action: "requests" }),
    ],
  ];
  const actions =
    role === "super_admin"
      ? [
          ["Invite owner", UserPlus, () => send("Invite owner")],
          [
            "Configure company",
            Settings2,
            () =>
              perform(async () => {
                setOrgs(await api("/api/organizations"));
                setMenu(false);
              }),
          ],
          [
            "Company accounts",
            Users,
            () => send("Show accounts", { action: "accounts" }),
          ],
        ]
      : role === "owner"
        ? [
            [
              "Appoint HR admin",
              UserPlus,
              () => send("Appoint HR", { action: "appoint" }),
            ],
            [
              "HR team",
              Users,
              () => send("Show HR list", { action: "hr_list" }),
            ],
            [
              "Manage HR accounts",
              Settings2,
              () => send("Show accounts", { action: "accounts" }),
            ],
            ...oversight,
          ]
        : employee
          ? [
              ["Upload document", Paperclip, () => input.current.click()],
              [
                "My profile & checklist",
                ShieldCheck,
                () => send("My checklist", { action: "profile" }),
              ],
              ["Request HR permission", CheckCheck, () => setRequestForm(true)],
              [
                "My requests",
                FileText,
                () => send("My requests", { action: "requests" }),
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
                "Manage employee accounts",
                Settings2,
                () => send("Show accounts", { action: "accounts" }),
              ],
              ...oversight,
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
        : role === "owner"
          ? ["Appoint HR admin", "Show submissions", "Show requests"]
          : ["Add an employee", "Show submissions", "Find an employee"];
  const messages = thread?.messages || [];
  return (
    <div className="app">
      <button
        className="logout-button"
        disabled={busy}
        onClick={() =>
          perform(async () => {
            await api("/api/auth/logout", { method: "POST" });
            setSession(null);
            setThread(null);
            setFile(null);
            setOrgs(null);
            setPrompt("");
            setMenu(false);
            setAgent(false);
          })
        }
      >
        <LogOut size={16} />
        <span>Log out</span>
      </button>
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
          <div className="account-identity">
            <span className="avatar">
              {session.user.name
                ?.split(/\s+/)
                .slice(0, 2)
                .map((n) => n[0])
                .join("") || "A"}
            </span>
            <div>
              <strong>{session.user.name}</strong>
              <small>{ROLES[role]}</small>
            </div>
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
          {requestForm && (
            <section className="result-card request-compose">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const v = formValues(e.currentTarget);
                  send("Request HR permission", {
                    action: "request_hr",
                    payload: { message: v.message, fields: {} },
                  });
                }}
              >
                <div className="card-heading">
                  <h3>Ask HR</h3>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Close request form"
                    onClick={() => setRequestForm(false)}
                  >
                    <X size={16} />
                  </button>
                </div>
                <textarea
                  name="message"
                  aria-label="Request to HR"
                  placeholder="Describe the permission or help you need…"
                  minLength={3}
                  maxLength={2000}
                  required
                />
                <button className="btn primary" disabled={busy}>
                  Review request
                  <ArrowRight size={15} />
                </button>
              </form>
            </section>
          )}

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
                  <option value="">Choose document type</option>
                  {Object.entries(TYPES).filter(([k]) => [...(documentPolicy?.government_types || []), ...(documentPolicy?.bank_types || [])].includes(k)).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              )}
              <Btn primary disabled={busy || (employee && !kind)} onClick={upload}>
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
            {employee ? "Upload your required documents, then submit to HR. Ask here if you need help." : role === "hr_admin" ? "Review submitted applications and original documents before approving onboarding." : role === "owner" ? "Appoint HR and track your company’s onboarding progress." : "Configure your company’s onboarding requirements and accounts."}
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
function Result({ data, active, role, busy, fields, send, choose }) {
  const confirm = () =>
    send("Confirm", { action: "confirm", confirmation_id: data.id });
  const cancel = () =>
    send("Cancel", { action: "cancel", confirmation_id: data.id });
  const confirmation = (
    <div className="card-actions">
      <Btn primary disabled={busy} onClick={confirm}>
        <Check size={15} />
        {data.confirm_label || "Confirm change"}
      </Btn>
      <Btn disabled={busy} onClick={cancel}>
        Cancel
      </Btn>
    </div>
  );
  switch (data.type) {
    case "task_progress":
      return <Card><div className="card-heading"><Sparkles size={17}/><h3>{data.goal}</h3></div><dl className="detail-grid">{Object.entries(data.known || {}).map(([key,value]) => <div key={key}><dt>{({name:"Full name",email:"Work email",organization_name:"Company",phone:"Phone"})[key] || key}</dt><dd>{String(value)}</dd></div>)}</dl><p className="muted">Still needed: {(data.missing || []).map(key => ({name:"full name",email:"work email",organization_name:"company name",phone:"phone number"})[key] || key).join(", ")}. Reply in the chat to continue. No invitation has been sent.</p></Card>;
    case "company_configuration": {
      const c = data.configuration || {};
      return <Card><div className="card-heading"><Settings2 size={17}/><h3>{c.name || "Company onboarding"}</h3></div><p className="muted">Current employee fields: {(c.fields || []).map(f => f.label).join(", ")}</p><p className="muted">Government documents: {c.government_minimum} required from {(c.government_types || []).map(k => TYPES[k] || k).join(", ") || "none"}.</p><p className="muted">{c.bank_minimum ? `Bank proof: ${c.bank_minimum} required from ${(c.bank_types || []).map(k => TYPES[k] || k).join(", ")}.` : "Bank proof is not required."}</p></Card>;
    }
    case "accounts":
      return (
        <Card>
          <div className="card-heading">
            <Users size={17} />
            <h3>Company accounts</h3>
          </div>
          {data.accounts?.length ? (
            data.accounts.map((a) => (
              <AccountCard
                key={a.id + ":" + a.revision}
                account={a}
                busy={busy}
                send={send}
              />
            ))
          ) : (
            <p className="muted">No accounts found.</p>
          )}
        </Card>
      );
    case "requests":
      return (
        <Card>
          <div className="card-heading">
            <CheckCheck size={17} />
            <h3>Employee requests</h3>
          </div>
          {data.requests?.length ? (
            data.requests.map((r) => (
              <RequestCard
                key={r.id + ":" + r.version}
                item={r}
                role={role}
                busy={busy}
                send={send}
              />
            ))
          ) : (
            <p className="muted">No requests yet.</p>
          )}
        </Card>
      );

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
            <h3>{data.confirm_label || "Review this action"}</h3>
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
          {role === "hr_admin" && <><p className="muted">The employees can sign in using their invitation, upload their documents and submit them to HR. You can track their progress in the employee list.</p><Btn disabled={busy} onClick={() => send("List employees")}>View employee list</Btn></>}
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
            <p className="muted">No employees in this view. “List employees” shows everyone; “Review submissions” shows only applications submitted to HR.</p>
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
          <p className="muted">{data.accepted || 0} employees are ready to add. Confirm below to create their accounts and send invitations.</p>
          {(data.people || []).map(p => <div className="employee-row" key={p.email}><span><strong>{p.name}</strong><small>{p.email}</small></span></div>)}
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
    submitted: "Submitted · HR review pending",
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
function Person({ person, role, busy, send }) {
  const [editing, setEditing] = useState(false);
  const [correctionError, setCorrectionError] = useState("");
  const [previewDoc, setPreviewDoc] = useState(null);
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
        <section className="onboarding-guide" aria-label="Onboarding steps">
          <ol className="journey">
            <li className={person.workflow.ready_to_submit ? "done" : "current"}>1. Upload documents</li>
            <li className={person.status === "submitted" || person.status === "onboarded" ? "done" : ""}>2. Submit to HR</li>
            <li className={person.status === "onboarded" ? "done" : person.status === "submitted" ? "current" : ""}>3. HR review</li>
          </ol>
          <div className="requirement-list">
            {[
              ["Government documents", person.workflow.minimum_government, person.workflow.government_types, person.workflow.allowed_government_types],
              ["Bank proof", person.workflow.minimum_bank, person.workflow.bank_types, person.workflow.allowed_bank_types],
            ].map(([label, minimum, received, allowed]) => (
              <div className="requirement" key={label}>
                <strong>{label}</strong>
                <span>{minimum ? `${received.length} of ${minimum} received` : "Not required by your company"}</span>
                <small>{minimum ? (minimum === (allowed || []).length ? "Upload each document below" : `Choose ${minimum} different types below`) : (allowed || []).length ? "Optional accepted documents" : "No bank document needs to be uploaded."}</small>
                <ul className="document-requirements">{(allowed || []).map(k => <li key={k}><span>{TYPES[k] || k}</span><em>{received.includes(k) ? "Received" : minimum ? "Not uploaded" : "Optional"}</em></li>)}</ul>
              </div>
            ))}
          </div>
          <p className="next-step">{person.status === "submitted" ? "Submitted to HR. Wait for review; uploading is complete." : person.status === "onboarded" ? "HR approved onboarding." : person.workflow.ready_to_submit ? "Documents received. Check the details, then submit your application to HR." : "Upload the missing accepted documents using + → Upload document. Each required document must be a different type."}</p>
          {role === "employee" && person.status === "draft" && (
            <div className="card-actions">
              <Btn disabled={busy} onClick={() => send("How do I upload documents?", {action:"upload"})}>Upload guidance</Btn>
              <Btn primary disabled={busy || !person.workflow.ready_to_submit} onClick={() => send("Submit to HR", {action:"submit"})}>Submit to HR</Btn>
            </div>
          )}
        </section>
      )}
      <div className="document-list">
        {person.documents?.filter((doc, i, docs) => !docs.slice(i+1).some(other => other.kind === doc.kind)).map((doc) => (
          <button
            key={doc.id}
            disabled={busy}
            onClick={() =>
              setPreviewDoc(previewDoc?.id === doc.id ? null : doc)
            }
          >
            <span className="file-icon">
              <FileText size={17} />
            </span>
            <span>
              <strong>{TYPES[doc.kind] || doc.kind}</strong>
              <small>Uploaded · {doc.extraction?.status === "success" ? "Fields extracted" : "Check extracted details"} · Preview</small>
            </span>
            <ChevronRight size={16} />
          </button>
        ))}
      </div>
      {previewDoc?.extraction?.extracted_data && <div className="extracted-fields"><h4>Details read from this document</h4><dl className="detail-grid">{Object.entries(previewDoc.extraction.extracted_data).filter(([,v]) => v !== null && v !== "" && typeof v !== "object").map(([key,value]) => <div key={key}><dt>{key.replaceAll("_"," ")}</dt><dd>{String(value)}</dd></div>)}</dl><p className="muted">Check these details against your document. If they are incorrect, ask HR for help.</p></div>}
      {previewDoc && (
        <DocumentPreview
          key={previewDoc.id}
          doc={previewDoc}
          onClose={() => setPreviewDoc(null)}
        />
      )}
      {role === "employee" && (
        <>
          <Btn disabled={busy} onClick={() => setEditing(!editing)}>
            Request a correction
          </Btn>
          {editing && (
            <form
              className="form-fields compact-edit"
              onSubmit={(e) => {
                e.preventDefault();
                const v = formValues(e.currentTarget);
                const changes = Object.fromEntries(
                  Object.entries(v).filter(
                    ([k, value]) => value !== String(person[k] ?? ""),
                  ),
                );
                if (!Object.keys(changes).length) {
                  setCorrectionError("Change at least one detail before requesting a correction.");
                  return;
                }
                setCorrectionError("");
                send("Request a profile correction", {
                  action: "request_hr",
                  payload: {
                    message: "Please review my contact details.",
                    fields: changes,
                  },
                });
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
              <Field
                name="email"
                type="email"
                label="Email address"
                defaultValue={person.email}
                required
              />
              <button className="btn primary" disabled={busy}>
                Review correction request
              </button>
              <ErrorLine text={correctionError} />
            </form>
          )}
        </>
      )}
      {role === "hr_admin" && person.status === "submitted" && (
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
            onClick={() => send("Reopen " + person.email, { action: "reopen" })}
          >
            Request correction
          </Btn>
        </div>
      )}
      {role === "hr_admin" && person.status !== "submitted" && person.status !== "onboarded" && <p className="muted">Awaiting the employee’s submission. HR approval is available after they choose Submit to HR.</p>}
      {role === "hr_admin" && (
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
function AccountCard({ account: a, busy, send }) {
  const [edit, setEdit] = useState(false);
  return (
    <section className="account-record">
      <div className="employee-row">
        <span className="person-avatar">{a.name[0]}</span>
        <span>
          <strong>{a.name}</strong>
          <small>
            {a.email} · {ROLES[a.role]}
          </small>
        </span>
        <Badge
          status={
            a.disabled
              ? "disabled"
              : a.must_change
                ? "password_change_required"
                : "active"
          }
        />
      </div>
      <div className="account-actions">
        <Btn disabled={busy} onClick={() => setEdit(!edit)}>
          Correct details
        </Btn>
        {a.must_change && !a.disabled && (
          <Btn
            disabled={busy}
            onClick={() =>
              send("Resend invitation", {
                action: "account_resend",
                payload: { id: a.id },
              })
            }
          >
            Resend invitation
          </Btn>
        )}
        <Btn
          disabled={busy}
          onClick={() =>
            send(a.disabled ? "Restore account" : "Disable account", {
              action: a.disabled ? "account_enable" : "account_disable",
              payload: { id: a.id, revision: a.revision },
            })
          }
        >
          {a.disabled ? "Restore access" : "Disable access"}
        </Btn>
      </div>
      {edit && (
        <form
          className="form-fields compact-edit"
          onSubmit={(e) => {
            e.preventDefault();
            const v = formValues(e.currentTarget);
            const fields = Object.fromEntries(
              Object.entries(v).filter(([k, value]) => value !== a[k]),
            );
            if (Object.keys(fields).length)
              send("Correct account details", {
                action: "account_change",
                payload: { id: a.id, revision: a.revision, fields },
              });
          }}
        >
          <Field label="Full name" name="name" defaultValue={a.name} required />
          <Field
            label="Email address"
            name="email"
            type="email"
            defaultValue={a.email}
            required
          />
          <button className="btn primary" disabled={busy}>
            Review correction
          </button>
        </form>
      )}
    </section>
  );
}
function RequestCard({ item: r, role, busy, send }) {
  return (
    <section className="request-record">
      <div className="card-heading">
        <h3>{r.name || "Your request"}</h3>
        <Badge status={r.status} />
      </div>
      <p className="muted">{r.message}</p>
      {Object.entries(r.fields || {}).map(([k, value]) => (
        <p className="request-value" key={k}>
          {k} · {String(r.before_values?.[k] ?? "")} → {String(value)}
        </p>
      ))}
      {r.note && <p className="muted">HR decision · {r.note}</p>}
      {r.status === "pending" && role === "employee" && (
        <Btn
          disabled={busy}
          onClick={() =>
            send("Cancel my request", {
              action: "cancel_request",
              payload: { id: r.id },
            })
          }
        >
          Cancel request
        </Btn>
      )}
      {r.status === "pending" && role === "hr_admin" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const v = formValues(e.currentTarget);
            send("Review HR decision", {
              action: e.nativeEvent.submitter.value,
              payload: { id: r.id, note: v.note },
            });
          }}
        >
          <textarea
            name="note"
            aria-label="HR decision reason"
            placeholder="Reason for your decision…"
            minLength={3}
            maxLength={1000}
            required
          />
          <div className="card-actions">
            <button
              className="btn primary"
              value="approve_request"
              disabled={busy}
            >
              Approve request
            </button>
            <button className="btn" value="reject_request" disabled={busy}>
              Reject request
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
function DocumentPreview({ doc, onClose }) {
  const [page, setPage] = useState(1),
    [pages, setPages] = useState(1),
    [image, setImage] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    let url;
    setLoading(true);
    setError("");
    fetch("/api/onboarding/documents/" + doc.id + "/preview?page=" + page, {
      credentials: "same-origin",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const value = await response.json();
          throw new Error(value.detail || "Preview unavailable.");
        }
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setImage(url);
        setPages(Number(response.headers.get("X-Page-Count")) || 1);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [doc.id, page]);
  return (
    <section className="inline-document" aria-label="Document preview">
      <div className="preview-toolbar">
        <span>{TYPES[doc.kind] || doc.kind}</span>
        <button
          className="icon-button"
          aria-label="Close document preview"
          onClick={onClose}
        >
          <X size={16} />
        </button>
      </div>
      <div className="preview-surface">
        {loading ? (
          <p className="muted">Loading preview…</p>
        ) : error ? (
          <ErrorLine text={error} />
        ) : (
          <img src={image} alt={(TYPES[doc.kind] || doc.kind) + " original"} />
        )}
      </div>
      {pages > 1 && (
        <div className="inline-pagination">
          <Btn
            disabled={loading || page <= 1}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft size={15} />
            Previous
          </Btn>
          <span>
            {page} / {pages}
          </span>
          <Btn
            disabled={loading || page >= pages}
            onClick={() => setPage(page + 1)}
          >
            Next
            <ChevronRight size={15} />
          </Btn>
        </div>
      )}
    </section>
  );
}
createRoot(document.getElementById("root")).render(<App />);
