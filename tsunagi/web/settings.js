// Tsunagi settings page, on Kiso's settings shell (_kiso/web/shell.js): it owns
// the sidebar, Save and Cancel, the unsaved dots, each page's Revert and
// Restore, the close prompt and the globals used here (S, saved, draft, page,
// call, h, icon, ICONS, clone, same, changed, render, pageChanged,
// pageActions). Talks to Python only through Anki's pycmd bridge
// (adapters/settings_page.py, SettingsBridge). No build step.

const PAGES = [
  ["server", "Server"],
  ["apps", "Apps & keys"],
  ["nokey", "Requests without a key"],
  ["web", "Websites & Anki pages"],
  ["addons", "Add-ons"],
  ["roles", "Roles"],
  ["requests", "Recent requests"],
];

// Sidebar icons: 24-unit stroke paths drawn in the text colour. They support
// the labels, never replace them (aria-hidden).
Object.assign(ICONS, {
  server: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  apps: "M14.5 9.5a4 4 0 1 1-1.2-2.8M13.3 10.7 20 17.4V20h-2.6v-2h-2v-2h-2l-.7-.7",
  nokey: "M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M4 12h11M11 8l4 4-4 4",
  web: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z",
  addons: "M5 8h3.5a2 2 0 1 1 3.5-1.5V8H19v4.5a2 2 0 1 0 0 4V20H5z",
  roles: "M4 5h16v14H4zM9 11a2 2 0 1 0 0-.01M6 16c.6-1.7 1.7-2.5 3-2.5s2.4.8 3 2.5M14 10h3M14 13h3",
  requests: "M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
  chevron: "M9 6l6 6-6 6",
  done: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8 12.5l2.7 2.7L16 9.8",
});

let editing = null;    // role id open in the role editor, or null for the list
let takeover = null;   // the AnkiConnect takeover dialog: {startup, preview, busy, done}
const openApps = new Set();   // app rows showing their detail (full key, New key, Remove)
const openAreas = new Set();

const link = (label, onclick, attrs) => h("button", { type: "button", class: "link", onclick, ...attrs }, label);
// Links inside the pages; the sidebar sets `page` itself (see the nav listener).
const go = (p, role) => {
  page = p; editing = role || null; changed(true); document.getElementById("main").scrollTop = 0;
};
const anyUnsaved = () => Kiso.pages.some((p) => pageChanged(p.id));
const showError = (message) => { document.getElementById("errors").textContent = message; };

// A short footer message, e.g. after a key is copied; the unsaved status comes back after it.
let noticeTimer = 0;
function notify(text) {
  changed(true);
  const status = document.getElementById("status");
  status.textContent = text;
  status.classList.remove("dirty");
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => changed(false), 2500);
}
function copyKey(key, button) {
  call("copy", key);
  if (button) {
    button.textContent = "Copied";
    button.classList.add("done");
    setTimeout(() => { if (button.isConnected) { button.textContent = "Copy"; button.classList.remove("done"); } }, 1500);
  }
}

// The page's state from Python, with what it edits as `cfg` (a Save answers the new `cfg` only).
function load(state) {
  S = state;
  saved = clone(state.cfg);
  draft = clone(state.cfg);
}

// ---------- per-page revert and restore (both only change the draft) ----------

const serverKeys = () => S.fields.filter((f) => f.key !== "cors_allowlist").map((f) => f.key);

function sliceOf(p, d) {
  if (p === "server") return serverKeys().map((k) => d.values[k]);
  if (p === "apps") return d.apps;
  if (p === "nokey") return S.no_key_rows.map((r) => d[r.setting]);
  if (p === "web") return [d.values.cors_allowlist, d.gates];
  if (p === "roles") return d.roles;
  if (p === "addons") return d.addon_enabled;
  return null;  // requests: nothing to save
}

const REVERT = {
  server: (d) => { for (const k of serverKeys()) d.values[k] = saved.values[k]; },
  apps: (d) => { d.apps = clone(saved.apps); openApps.clear(); },
  nokey: (d) => { for (const r of S.no_key_rows) d[r.setting] = saved[r.setting]; d.confirm_remote = false; },
  web: (d) => { d.values.cors_allowlist = saved.values.cors_allowlist; d.gates = clone(saved.gates); },
  roles: (d) => {
    // Keep new roles something still uses, so reverting here cannot break another page.
    const used = new Set([...d.apps.map((a) => a.role), ...S.no_key_rows.map((r) => d[r.setting])]);
    const keep = d.roles.filter((r) => used.has(r.id) && !saved.roles.some((x) => x.id === r.id));
    d.roles = clone(saved.roles).concat(keep);
  },
  addons: (d) => {
    // Approving changed roles too (see setApproval); undo that for the
    // actions whose approval goes back, and leave other role edits alone.
    const before = d.addon_enabled;
    d.addon_enabled = clone(saved.addon_enabled);
    for (const key of new Set([...Object.keys(before), ...Object.keys(saved.addon_enabled)])) {
      if (before[key] === saved.addon_enabled[key]) continue;
      const name = addonName(key);
      for (const r of d.roles) {
        const had = (saved.roles.find((x) => x.id === r.id)?.grants || []).includes(name);
        r.grants = r.grants.filter((g) => g !== name).concat(had ? [name] : []).sort();
      }
    }
  },
};

const RESTORE = {
  server: (d) => { for (const k of serverKeys()) d.values[k] = S.defaults.values[k]; },
  nokey: (d) => { for (const r of S.defaults.no_key_rows) d[r.setting] = r.role; d.confirm_remote = false; },
  web: (d) => { d.values.cors_allowlist = S.defaults.values.cors_allowlist;
                for (const g of S.defaults.gates) d.gates[g.key] = g.on; },
  addons: (d) => {
    d.addon_enabled = {};
    for (const r of d.roles) r.grants = r.grants.filter((g) => !g.startsWith("addon:"));
  },
  roles: (d) => { for (const r of d.roles) { const def = defaultOf(r, d);
                                             if (def) { r.name = def.name; r.grants = def.grants; } } },
};

// The role editor's own Revert and Restore, in the look of Kiso's page actions
// (which every other page gets from pageActions). Each shows only when it would
// change something; both wait for Save. Not .head-actions: Kiso redraws that one.
function roleActions(revert, restore) {
  return h("div", { class: "role-actions" },
    revert && h("button", { type: "button", class: "quiet", id: "revertRole", onclick: () => { revert(); changed(true); },
                            title: "Undo unsaved changes on this role only. Other pages keep theirs." }, "Revert this role"),
    restore && h("button", { type: "button", class: "quiet", id: "resetRole", onclick: () => { restore(); changed(true); },
                             title: "Back to the defaults for this role only. Nothing changes until Save." }, "Restore this role's defaults"));
}

function header(title, lead) {
  return h("header", { class: "page-head" },
    h("div", {}, h("h1", {}, title), lead && h("p", { class: "lead" }, lead)),
    pageActions());
}

// ---------- fields ----------

const field = (key) => S.fields.find((f) => f.key === key);
const setNum = (obj, key) => (e) => { const n = Number(e.target.value); obj[key] = Number.isInteger(n) ? n : e.target.value; };

// data-field: where a Save error naming this setting puts the focus (Kiso's save()).
function input(f) {
  const v = draft.values[f.key];
  const set = (x) => { draft.values[f.key] = x; };
  const at = { id: f.key, "data-field": f.key };
  if (f.kind === "bool") return h("input", { type: "checkbox", ...at, checked: v, onchange: (e) => set(e.target.checked) });
  if (f.kind === "int" || f.kind === "mib") {
    return h("span", { class: "unit" }, h("input", { type: "number", ...at, min: f.minimum, max: f.maximum,
      value: v, oninput: setNum(draft.values, f.key) }), f.kind === "mib" ? "MiB" : "");
  }
  if (f.kind === "choice") {
    return h("select", { ...at, onchange: (e) => set(e.target.value) },
             f.choices.map((c) => h("option", { value: c, selected: c === v }, c)));
  }
  if (f.kind === "cors_list") return h("textarea", { ...at, spellcheck: "false", value: v, oninput: (e) => set(e.target.value) });
  return h("input", { type: "text", ...at, spellcheck: "false", value: v, oninput: (e) => set(e.target.value) });
}

function row(label, control, help, forId) {
  return h("div", { class: "row" }, h("label", { for: forId }, label),
           h("div", {}, control, help && h("div", { class: "help" }, help)));
}

// ---------- roles ----------

const roleById = (id) => draft.roles.find((r) => r.id === id);
const roleName = (id) => (roleById(id) || { name: id + " (missing)" }).name;
const areaNames = (area) => namesOf(area).map((n) => n.name);
const sameGrants = (a, b) => [...a].sort().join() === [...b].sort().join();
const sameRole = (a, b) => a.name === b.name && sameGrants(a.grants, b.grants);

// ---------- add-on actions ----------

const addonName = (key) => "addon:" + key;
const allActions = () => S.providers.flatMap((p) => p.actions.map((a) => ({ ...a, provider: p.title })));
const approved = (a, d = draft) => d.addon_enabled[a.key] === a.impact;

// A built-in role's defaults. Default also has every action approved as
// undoable, like the server's Settings.role, so approving keeps it unedited.
function defaultOf(r, d = draft) {
  const def = S.roles.find((x) => x.id === r.id)?.default;
  if (!def) return null;
  const extra = r.id !== "default" ? [] : Object.entries(d.addon_enabled)
    .filter(([, impact]) => impact === "undoable").map(([key]) => addonName(key));
  return { name: def.name, grants: [...new Set(def.grants.concat(extra))].sort() };
}

// Approving an undoable action also allows it for Default; destructive ones are
// only in Everything until a role adds them. Withdrawing removes it everywhere.
function setApproval(a, on) {
  const name = addonName(a.key);
  if (on) {
    draft.addon_enabled[a.key] = a.impact;
    const dflt = roleById("default");
    if (a.impact === "undoable" && dflt && !dflt.grants.includes(name)) dflt.grants = [...dflt.grants, name].sort();
  } else {
    delete draft.addon_enabled[a.key];
    for (const r of draft.roles) r.grants = r.grants.filter((g) => g !== name);
  }
}

// The role editor's parts of an area. For add-ons: the approved actions.
function namesOf(area) {
  if (area.area !== "addon") return area.names;
  return allActions().filter((a) => a.impact !== "read" && approved(a))
    .map((a) => ({ name: addonName(a.key), label: a.title, group: a.provider, destructive: a.impact === "destructive" }));
}

const allows = (r, name) => r.grants.includes(name) || r.grants.includes(name.split(":")[0]);
const rowId = (a) => "act_" + a.key.replace("/", "__");
const permId = (a) => "perm_" + addonName(a.key);

// Role names as links to that role's add-on permissions, the action highlighted.
// Add-on text can be any length: long descriptions start folded to two lines,
// with a visible control for the rest. Nothing is cut without one.
const LONG_DESCRIPTION = 200;
const openDescriptions = new Set();
function description(a) {
  if (!a.description) return null;
  const long = a.description.length > LONG_DESCRIPTION;
  const open = openDescriptions.has(a.key);
  return h("div", { class: "desc action-desc" },
    h("div", { class: long && !open ? "folded" : null }, a.description),
    long && link(open ? "Show less" : "Show full description",
                 () => { open ? openDescriptions.delete(a.key) : openDescriptions.add(a.key); changed(true); },
                 { "aria-expanded": String(open), class: "link fold" }));
}

// One action, two table rows: the switch and the name keep their places on
// every row; the add-on's description wraps on the line below. Which roles may
// run it is shown in Roles, not here.
function actionRows(a, shared) {
  const read = a.impact === "read";
  const on = read || approved(a);
  const relabelled = !read && !approved(a) && a.key in draft.addon_enabled;
  const id = "approve_" + a.key.replace("/", "__");
  return [
    h("tr", { class: "action " + a.impact, id: rowId(a), "data-action": a.key },
      h("td", { class: "approve" },
        h("input", { type: "checkbox", id, checked: on, disabled: read, "aria-label": "Enable " + a.title,
                     title: read ? "Reading is always enabled; the app's role decides" : null,
                     onchange: (e) => { setApproval(a, e.target.checked); changed(true); } })),
      h("td", { class: "name" }, h("label", { for: id }, a.title),
        a.impact === "destructive" && h("span", { class: "tag danger" }, "Destructive"),
        a.backup && h("span", { class: "tag" }, "Backs up first"),
        !shared.ui && a.shows_ui && h("span", { class: "tag" }, "Shows windows here"))),
    h("tr", { class: "action-more " + a.impact }, h("td", {}), h("td", {},
      description(a),
      relabelled && h("div", { class: "desc warn-text" }, "The add-on changed this action since you enabled it. Enable it again."))),
  ];
}

function providerCard(p) {
  const acts = p.actions.filter((a) => a.impact !== "read");
  const reads = p.actions.filter((a) => a.impact === "read");
  const ready = acts.filter((a) => a.impact === "undoable" && !approved(a));
  // Said once under the heading when every action shares it, not on each row.
  const shared = { ui: acts.length > 0 && acts.every((a) => a.shows_ui),
                   undoable: acts.length > 0 && acts.every((a) => a.impact === "undoable") };
  const notes = [shared.undoable && `All ${acts.length} change your collection.`,
                 shared.ui && "They show a progress window or message on this computer while running."].filter(Boolean);
  const section = (label) => h("tr", { class: "section" }, h("td", { colspan: 2 }, label));
  return h("section", { class: "card flush addon", "data-provider": p.id },
    h("div", { class: "addon-head" },
      h("h2", {}, p.title),
      acts.length > 0 && h("span", { class: "muted small count" }, `${acts.filter((a) => approved(a)).length} of ${acts.length} enabled`),
      ready.length > 0 && h("button", { type: "button", class: "quiet", "data-approve-all": p.id,
        title: "Enable every action here except destructive ones, which you enable one by one.",
        onclick: () => { ready.forEach((a) => setApproval(a, true)); changed(true); } }, "Enable all")),
    h("div", { class: "addon-status desc" },
      p.unsupported ? h("span", { class: "warn-text" }, "Unavailable: " + p.unsupported + ". Its actions cannot run.")
                    : "Installed and loaded, so its actions can run.",
      notes.length ? " " + notes.join(" ") : ""),
    h("table", { class: "table actions" },
      h("colgroup", {}, h("col", { class: "c-approve" }), h("col", {})),
      h("thead", {}, h("tr", {}, h("th", {}, "Enabled"), h("th", {}, "Action"))),
      h("tbody", {},
        acts.map((a) => actionRows(a, shared)),
        reads.length > 0 && [section("Reading data: always enabled"), reads.map((a) => actionRows(a, shared))])));
}

function areaState(role, area) {
  if (role.grants.includes(area.area)) return { level: "all", count: namesOf(area).length, some: [], whole: true };
  const some = areaNames(area).filter((n) => role.grants.includes(n));
  // Add-ons: allowing every action enabled now is "all". It is not the whole
  // area, which would also cover actions enabled later (Everything has that).
  const all = area.area === "addon" && some.length > 0 && some.length === areaNames(area).length;
  return { level: all ? "all" : some.length ? "some" : "none", count: some.length, some };
}

// One cell per area: filled = all of it, half = some, empty = none.
function strip(role) {
  return h("span", { class: "strip", "aria-hidden": "true" }, S.catalog.map((area) => {
    const st = areaState(role, area);
    const what = st.level === "all" ? "all" : st.level === "some" ? `${st.count} of ${namesOf(area).length}` : "none";
    return h("i", { class: st.level, title: `${area.label}: ${what}` });
  }));
}

function summary(role) {
  const states = S.catalog.map((area) => [area, areaState(role, area)]);
  if (states.every(([, st]) => st.level === "all")) return "Everything";
  const parts = states.filter(([, st]) => st.level !== "none").map(([area, st]) =>
    st.level === "all" ? area.short : `${area.short} (${st.count}/${namesOf(area).length})`);
  return parts.length ? parts.join(", ") : "Nothing";
}

function usersOf(id) {
  const users = draft.apps.filter((a) => a.role === id).map((a) => ({ label: a.name || "(unnamed app)", page: "apps" }));
  for (const r of S.no_key_rows) if (draft[r.setting] === id) users.push({ label: "No key: " + r.short, page: "nokey" });
  return users;
}

function roleSelect(value, onchange, id, label) {
  return h("span", { class: "role-pick" },
    h("select", { id, "aria-label": label, onchange: (e) => { onchange(e.target.value); changed(true); } },
      draft.roles.map((r) => h("option", { value: r.id, selected: r.id === value }, r.name)),
      roleById(value) ? null : h("option", { value, selected: true }, value + " (missing)")),
    link("View", () => go("roles", value), { title: "Open this role" }));
}

const userLinks = (users) => users.map((u, i) => [i ? ", " : "", link(u.label, () => go(u.page))]);

// ---------- pages ----------

const PAGE = {
  server() {
    // One port: a set `port` wins over `prefer_port`, and neither falls back to
    // another port, so the page edits both together.
    const port = draft.values.port || draft.values.prefer_port;
    const setPort = (e) => { setNum(draft.values, "port")(e); setNum(draft.values, "prefer_port")(e); };
    return [
      header("Server", "Whether the API runs and where. Server changes restart it when you save."),
      h("section", { class: "card" },
        h("div", { class: "check" }, input(field("enabled")),
          h("label", { for: "enabled" }, h("b", {}, "Run the Tsunagi server"),
            h("span", { class: "help inline" }, " When off, the API does not start with Anki."))),
        row("Port", h("input", { type: "number", id: "port", "data-field": "port", min: 1, max: 65535, value: port, oninput: setPort }),
          "Must be free: if another program is using it, Tsunagi doesn't start.", "port"),
        row("Host", input(field("host")),
          "127.0.0.1: this computer only. Any other address lets other devices connect; they need a key (see Requests without a key).", "host"),
        row("Other host names", input(field("allowed_hosts")),
          "Names this computer is reached by through a proxy on it, such as Tailscale Serve (pc.tailnet.ts.net). " +
          "One per line, without http:// or a port. Requests through a proxy count as other devices.", "allowed_hosts"),
        S.ankiconnect.installed && ankiConnectRow()),
      h("section", { class: "card" },
        h("h2", {}, "Limits and logging"),
        h("div", { class: "grid4" }, S.fields.filter((f) => f.section === "Advanced").map((f) =>
          h("div", { class: "cell" }, h("label", { for: f.key, title: f.tooltip }, f.label), input(f))))),
    ];
  },

  apps() {
    const rows = draft.apps.map((app, i) => {
      const open = openApps.has(i);
      const toggle = () => { open ? openApps.delete(i) : openApps.add(i); changed(true); };
      const out = [h("tr", { class: app.enabled ? "app" : "app off" },
        h("td", { class: "approve" }, h("input", { type: "checkbox", class: "app-on", checked: app.enabled,
          "aria-label": "Turn " + app.name + " on", title: app.enabled
            ? "On. Untick to turn this app off: requests with its key are refused until you turn it back on"
            : "Off: requests with this key are refused. Tick to turn it back on",
          onchange: (e) => { app.enabled = e.target.checked; changed(true); } })),
        h("td", {}, h("input", { type: "text", class: "app-name", "aria-label": "App name", value: app.name,
                                 oninput: (e) => { app.name = e.target.value; } })),
        h("td", {}, roleSelect(app.role, (v) => { app.role = v; }, null, "Role of " + app.name)),
        h("td", {}, h("span", { class: "key-preview", title: "Key (More shows it in full)" },
                      app.key ? "••••" + app.key.slice(-4) : "no key"),
          link("Copy", (e) => copyKey(app.key, e.currentTarget), { title: "Copy the key" })),
        h("td", { class: "end" }, h("button", { type: "button", class: "disclosure", onclick: toggle, "aria-expanded": String(open),
          "aria-label": (open ? "Hide" : "Show") + " the key and actions for " + app.name,
          title: open ? "Hide the key and actions" : "Show the key, New key and Remove" }, icon("chevron"))))];
      if (open) {
        out.push(h("tr", { class: "app-detail" }, h("td", { colspan: 5 },
          h("div", { class: "detail" },
            h("label", { class: "detail-label" }, "Key"),
            h("input", { type: "text", class: "key", "aria-label": "Key of " + app.name, spellcheck: "false",
                         value: app.key, oninput: (e) => { app.key = e.target.value; } }),
            h("button", { type: "button", title: "Replace with a new random key and copy it. The old key stops working after Save.",
                          onclick: async () => { app.key = await call("new_key"); copyKey(app.key); notify("New key copied. It works once you save; until then the old key stays active."); } }, "New key"),
            h("span", { class: "spacer" }),
            h("button", { type: "button", class: "danger", "aria-label": "Remove " + app.name,
                          onclick: () => { draft.apps.splice(i, 1); openApps.clear(); changed(true); } }, "Remove app")))));
      }
      return out;
    });
    return [
      header("Apps & keys", "Give each tool its own key and role. Tools send the key as the X-Api-Key header, " +
             "or as \"key\" in AnkiConnect requests. Untick an app to turn it off without losing its key or role."),
      h("section", { class: "card flush" },
        draft.apps.length
          ? h("table", { class: "table" },
              h("thead", {}, h("tr", {}, h("th", {}, "On"), h("th", {}, "App"), h("th", {}, "Role"), h("th", {}, "Key"), h("th", {}))),
              h("tbody", {}, rows))
          : h("p", { class: "empty" }, "No apps yet. Tools on this computer work without a key; add an app to give " +
              "one its own role, or to connect from another device."),
        h("div", { class: "card-foot" },
          h("button", { type: "button", id: "addApp", onclick: async () => {
            const key = await call("new_key");
            let n = draft.apps.length + 1;
            while (draft.apps.some((a) => a.name === "New app " + n)) n++;
            draft.apps.push({ name: "New app " + n, key, role: "default", enabled: true });
            openApps.add(draft.apps.length - 1);
            copyKey(key);
            notify("New app added and its key copied. The key works once you save.");
          } }, "Add app"))),
    ];
  },

  nokey() {
    const remoteChanged = draft.no_key_remote_role !== "none" && draft.no_key_remote_role !== saved.no_key_remote_role;
    return [
      header("Requests without a key", "A request with no key, or a key no app has, gets the role of where it comes from."),
      h("section", { class: "card flush" },
        h("table", { class: "table" },
          h("thead", {}, h("tr", {}, h("th", {}, "Source"), h("th", {}, "Role"))),
          h("tbody", {}, S.no_key_rows.map((r) => h("tr", {},
            h("td", {}, h("b", {}, r.label), h("div", { class: "help" }, r.help)),
            h("td", {}, roleSelect(draft[r.setting], (v) => { draft[r.setting] = v; draft.confirm_remote = false; }, r.setting, r.label))))))),
      remoteChanged && h("div", { class: "warn" },
        h("div", { class: "check" },
          h("input", { type: "checkbox", id: "confirmRemote", "data-field": "confirmRemote", checked: draft.confirm_remote,
                       onchange: (e) => { draft.confirm_remote = e.target.checked; } }),
          h("label", { for: "confirmRemote" }, "Anyone who can reach this computer's port gets ",
            h("b", {}, roleName(draft.no_key_remote_role)), " without a key, including every device on your network. I understand."))),
    ];
  },

  web() {
    return [
      header("Websites & Anki pages", "Which web pages may call the API from a browser. Tools outside a browser are not affected."),
      h("section", { class: "card" },
        h("h2", {}, "Allowed website origins"),
        input(field("cors_allowlist")),
        h("div", { class: "help" }, "One per line, with http:// or https:// and any port. \"*\" allows all. " +
          "\"http://localhost\" also covers 127.0.0.1 pages and browser extensions, as in AnkiConnect.")),
      h("section", { class: "card" },
        h("h2", {}, "Anki's own pages"),
        S.gates.map((g) => h("div", { class: "check" },
          h("input", { type: "checkbox", id: "gate_" + g.key, checked: draft.gates[g.key],
                       onchange: (e) => { draft.gates[g.key] = e.target.checked; } }),
          h("label", { for: "gate_" + g.key }, h("b", {}, g.label), h("div", { class: "help" }, g.tooltip))))),
    ];
  },

  addons() {
    const known = new Set(allActions().map((a) => a.key));
    const orphans = Object.keys(draft.addon_enabled).filter((k) => !known.has(k));
    return [
      header("Add-ons", "Actions your add-ons offer to apps."),
      h("p", { class: "rule" }, "An action runs only if it is enabled here and the app's role allows it (Roles). " +
        "Reading data is always enabled; the role decides."),
      S.providers.length ? S.providers.map(providerCard)
        : h("section", { class: "card" }, h("p", { class: "empty" }, "No add-on offers actions.")),
      orphans.length > 0 && h("p", { class: "help", id: "orphanApprovals" },
        `${orphans.length} enabled action${orphans.length === 1 ? " is" : "s are"} kept for add-ons that offer no actions right now ` +
        "(not installed, or Tsunagi's server is off). Restore defaults clears them."),
    ];
  },

  roles() {
    if (editing && roleById(editing)) return roleEditor(roleById(editing));
    return [
      header("Roles", "A role is a set of permissions. Each app, and each source of requests without a key, has one."),
      h("section", { class: "card flush" },
        h("table", { class: "table roles" },
          h("thead", {}, h("tr", {}, h("th", {}, "Role"), h("th", {}, "Allows"), h("th", {}, "Used by"), h("th", {}))),
          h("tbody", {}, draft.roles.map((r) => {
            const def = defaultOf(r);
            const edited = def && !sameRole(def, r);
            const users = usersOf(r.id);
            return h("tr", { "data-role": r.id },
              h("td", {}, h("b", {}, r.name), def ? h("span", { class: "tag" }, edited ? "Built-in, edited" : "Built-in") : null),
              h("td", { class: "summary" }, strip(r), h("div", {}, summary(r))),
              h("td", { class: "users" }, users.length ? users.map((u) => link(u.label, () => go(u.page)))
                                                        : h("span", { class: "muted" }, "Not used")),
              h("td", { class: "end" }, link(r.id === "none" ? "View" : "Edit", () => go("roles", r.id), { "data-edit": r.id })));
          }))),
        h("div", { class: "card-foot" },
          h("button", { type: "button", id: "newRole", onclick: () => {
            let n = 1;
            while (roleById("custom_" + n)) n++;
            draft.roles.push({ id: "custom_" + n, name: "New role " + n, grants: ["read"] });
            go("roles", "custom_" + n);
          } }, "New role"))),
    ];
  },

  requests() {
    return [
      header("Recent requests", "Requests to Tsunagi since Anki started, including ones it refused, kept per client " +
             "so a busy one cannot hide another. Memory only; keys and request contents are never recorded."),
      h("div", { id: "requestsBody" }, requestsBody()),
    ];
  },
};

let requests = null;  // {clients, entries, per_client, max_shown} from the log, while that page is open
const requestFilter = { client: "", failed: false, text: "" };

const clockTime = (t) => new Date(t * 1000).toLocaleTimeString();
const clientLabel = (id) => (requests.clients.find((c) => c.id === id) || { label: id.replace(/^\w+:/, "") }).label;

function clientsCard() {
  const pick = (id) => { requestFilter.client = requestFilter.client === id ? "" : id; refreshRequests(); };
  return h("section", { class: "card flush" },
    h("table", { class: "table clients" },
      h("thead", {}, h("tr", {}, h("th", {}, "Client"), h("th", { class: "num" }, "Requests"),
                        h("th", { class: "num" }, "Failed"), h("th", { class: "num" }, "Last seen"))),
      h("tbody", {}, requests.clients.map((c) =>
        h("tr", { class: "client" + (c.id === requestFilter.client ? " picked" : ""), "data-client": c.id },
          h("td", {}, link(c.label, () => pick(c.id), { title: c.id === requestFilter.client ? "Show every client" : "Show only this client" }),
            c.kind === "website" && h("span", { class: "tag" }, "website, no key"),
            c.kind === "no_key" && h("span", { class: "tag" }, "no key")),
          h("td", { class: "num" }, String(c.requests)),
          h("td", { class: "num" + (c.failed ? " warn-text" : "") }, String(c.failed)),
          h("td", { class: "num muted" }, clockTime(c.last)))))));
}

function requestFilters() {
  return h("div", { class: "filters" },
    h("select", { id: "requestClient", "aria-label": "Client",
                  onchange: (e) => { requestFilter.client = e.target.value; refreshRequests(); } },
      h("option", { value: "" }, "All clients"),
      requests.clients.map((c) => h("option", { value: c.id, selected: c.id === requestFilter.client }, c.label))),
    h("label", { class: "check" }, h("input", { type: "checkbox", id: "requestFailed", checked: requestFilter.failed,
      onchange: (e) => { requestFilter.failed = e.target.checked; refreshRequests(); } }), " Failed only"),
    h("input", { type: "search", id: "requestText", placeholder: "Search path, action, origin, error",
                 value: requestFilter.text, oninput: (e) => { requestFilter.text = e.target.value; refreshRequests(); } }),
    h("button", { type: "button", id: "clearRequests", class: "push-end", title: "Forget every request and total, for all clients", disabled: !requests.clients.length,
                  onclick: async () => { await call("clear_requests"); requestFilter.client = ""; await refreshRequests(); } }, "Clear log"));
}

function requestRows() {
  return requests.entries.map((e) => {
    const what = e.action ? [e.action, h("span", { class: "tag" }, "AnkiConnect")] : [e.method + " " + e.path];
    return [
      h("tr", { class: "request" + (e.status >= 400 || e.error ? " failed" : "") },
        h("td", { class: "muted nowrap" }, clockTime(e.time)),
        h("td", {}, clientLabel(e.client)),
        h("td", { class: "origin" }, e.origin || h("span", { class: "muted" }, "none")),
        h("td", { class: "what" }, ...what),
        h("td", { class: "num status" }, String(e.status)),
        h("td", { class: "num muted" }, e.ms === null ? "open" : e.ms + " ms")),
      e.error && h("tr", { class: "request-more" }, h("td", {}), h("td", { colspan: 5 }, h("div", { class: "desc warn-text" }, e.error))),
    ];
  });
}

function requestsBody() {
  if (!requests) return [h("section", { class: "card" }, h("p", { class: "empty" }, "Loading…"))];
  if (!requests.clients.length) return [h("section", { class: "card flush" }, h("p", { class: "empty" }, "No requests since Anki started."))];
  const filtered = requestFilter.client || requestFilter.failed || requestFilter.text.trim();
  return [
    clientsCard(),
    h("section", { class: "card flush" },
      h("div", { class: "card-head" }, requestFilters()),
      requests.entries.length
        ? h("table", { class: "table requests" },
            h("thead", {}, h("tr", {}, h("th", {}, "Time"), h("th", {}, "Client"), h("th", {}, "Origin"),
                              h("th", {}, "Request"), h("th", { class: "num" }, "Status"), h("th", { class: "num" }, "Time taken"))),
            h("tbody", {}, requestRows()))
        : h("p", { class: "empty" }, filtered ? "No requests match these filters." : "No requests."),
      h("p", { class: "help foot-note" }, `Each client keeps its last ${requests.per_client} requests; ` +
        `up to ${requests.max_shown} are listed, newest first.`)),
  ];
}

// The request log changes on its own, so its page refreshes while shown. Only
// the part below the heading is replaced; the filter box keeps its focus.
async function refreshRequests() {
  requests = await call("requests", requestFilter);
  if (page !== "requests") return;
  const body = document.getElementById("requestsBody");
  if (!body) return render();
  const focused = document.activeElement && document.activeElement.id;
  const caret = focused === "requestText" ? document.activeElement.selectionStart : null;
  body.replaceChildren(...requestsBody().flat(Infinity).filter(Boolean));
  const again = focused && document.getElementById(focused);
  if (again) { again.focus(); if (caret !== null) again.setSelectionRange(caret, caret); }
}

function roleEditor(r) {
  const locked = r.id === "none";
  const def = defaultOf(r);
  const isDefault = def && sameRole(def, r);
  const savedRole = saved.roles.find((x) => x.id === r.id);
  const users = usersOf(r.id);
  const setGrants = (grants) => { r.grants = [...new Set(grants)].sort(); changed(true); };
  const rows = S.catalog.map((area) => {
    const names = areaNames(area);
    const st = areaState(r, area);
    const addons = area.area === "addon";
    const box = h("input", { type: "checkbox", id: "area_" + area.area, checked: st.level === "all", disabled: locked,
      onchange: (e) => setGrants(r.grants.filter((x) => x !== area.area && !names.includes(x))
        .concat(!e.target.checked ? [] : area.area === "addon" ? names : [area.area])) });
    box.indeterminate = st.level === "some";
    const open = openAreas.has(area.area);
    const out = [h("tr", { class: "area" },
      h("td", { class: "area-box" }, box),
      h("td", {}, h("label", { for: "area_" + area.area }, h("b", {}, area.label)), h("div", { class: "help" }, area.description)),
      h("td", { class: "end" }, names.length
        ? [h("span", { class: "muted small" }, st.level !== "all" ? `${st.count} of ${names.length}`
             : addons && st.whole ? "all, including ones enabled later" : "all"), " ",
           link(open ? "Done" : "Choose", () => { open ? openAreas.delete(area.area) : openAreas.add(area.area); changed(true); },
                { "data-area": area.area, disabled: locked })]
        : addons ? [h("span", { class: "muted small" }, "none enabled"), " ", link("Add-ons", () => go("addons"))]
        : null))];
    if (open && addons) {
      out.push(h("tr", { class: "parts" }, h("td", {}), h("td", { colspan: 2 }, addonParts(r, area, st, locked, setGrants))));
    } else if (open && names.length) {
      out.push(h("tr", { class: "parts" }, h("td", {}), h("td", { colspan: 2 }, h("div", { class: "names" }, namesOf(area).map((n) =>
        h("label", { class: "check" },
          h("input", { type: "checkbox", id: "perm_" + n.name, checked: st.level === "all" || st.some.includes(n.name), disabled: locked,
            onchange: (e) => {
              let chosen = st.level === "all" ? names : st.some;
              chosen = e.target.checked ? chosen.concat([n.name]) : chosen.filter((x) => x !== n.name);
              const rest = r.grants.filter((x) => x !== area.area && !names.includes(x));
              setGrants(chosen.length === names.length ? rest.concat([area.area]) : rest.concat(chosen));
            } }),
          n.label))))));
    }
    return out;
  });
  return [
    h("header", { class: "page-head" },
      h("div", {},
        h("nav", { class: "crumbs", "aria-label": "Breadcrumb" }, link("Roles", () => go("roles"), { id: "backToRoles" }), h("span", {}, "/")),
        h("h1", {}, r.name || "(unnamed role)"),
        h("p", { class: "lead" }, users.length ? ["Used by ", userLinks(users)] : "Not used by any app or source yet.")),
      roleActions(savedRole && !sameRole(savedRole, r) && (() => { r.name = savedRole.name; r.grants = [...savedRole.grants]; }),
                  def && !locked && !isDefault && (() => { r.name = def.name; r.grants = [...def.grants]; }))),
    h("section", { class: "card flush" },
      h("div", { class: "role-name" }, h("label", { for: "roleName" }, "Name"),
        h("input", { type: "text", id: "roleName", value: r.name, disabled: locked, oninput: (e) => { r.name = e.target.value; } })),
      locked ? h("p", { class: "empty" }, "No access allows nothing and cannot be changed.")
             : h("table", { class: "table areas" }, h("tbody", {}, rows))),
    !locked && h("div", { class: "object-actions" },
      h("button", { type: "button", id: "copyRole", onclick: () => {
        let n = 1;
        while (roleById("custom_" + n)) n++;
        draft.roles.push({ id: "custom_" + n, name: r.name + " (copy)", grants: [...r.grants] });
        go("roles", "custom_" + n);
      } }, "Duplicate role"),
      !def && h("button", { type: "button", class: "danger", id: "deleteRole", disabled: users.length > 0,
        onclick: () => { draft.roles = draft.roles.filter((x) => x !== r); go("roles"); } }, "Delete role"),
      !def && users.length > 0 && h("span", { class: "help inline" }, "To delete it, give its apps and sources another role first.")),
  ];
}

// Every action by add-on, with the two steps apart: the checkbox is this
// role's permission; the status says whether the action is approved, since
// an action runs only when both are true.
function addonParts(r, area, st, locked, setGrants) {
  const names = areaNames(area);
  const choose = (name, on) => {
    let chosen = st.level === "all" ? names : st.some;
    chosen = on ? chosen.concat([name]) : chosen.filter((x) => x !== name);
    // By name, never collapsed into the whole area: that would also allow
    // actions enabled later.
    setGrants(r.grants.filter((x) => x !== area.area && !names.includes(x)).concat(chosen));
  };
  const intro = h("div", { class: "desc permits-intro" }, "Checked: this role allows the action. It runs only if " +
    "the action is also enabled on the Add-ons page.");
  return [intro, S.providers.map((p) => {
    const acts = allActions().filter((a) => a.provider === p.title && a.impact !== "read");
    return acts.length > 0 && h("div", { class: "addon-parts" },
      h("div", { class: "group" }, p.title),
      h("table", { class: "permits" }, h("tbody", {}, acts.map((a) => {
        const name = addonName(a.key);
        const ok = approved(a);
        const permits = allows(r, name);
        const status = ok ? ["Enabled", permits ? "Runs for this role" : "Not for this role"]
                          : ["Disabled", permits ? "Allowed here; runs once enabled" : "Won't run"];
        return h("tr", { id: "row_" + permId(a), class: ok ? "" : "unapproved" },
          h("td", { class: "area-box" },
            h("input", { type: "checkbox", id: permId(a), checked: permits, disabled: locked || !ok || r.grants.includes(area.area),
                         title: !ok ? "Enable it on the Add-ons page first" : r.grants.includes(area.area) ? "This role allows every enabled action" : null,
                         onchange: (e) => choose(name, e.target.checked) })),
          h("td", {}, h("label", { for: permId(a), class: a.impact === "destructive" ? "destructive" : null }, a.title),
            a.impact === "destructive" && h("span", { class: "tag danger" }, "Destructive")),
          h("td", { class: "status" }, h("span", { class: "tag " + (ok ? "ok" : "off") }, status[0]), " ", status[1],
            !ok && [" ", link("Enable…", () => { go("addons"); const row = document.getElementById(rowId(a));
                                                             if (row) { row.scrollIntoView({ block: "center" }); row.classList.add("flash"); } },
                              { title: "Open this action on the Add-ons page" })]));
      }))));
  })];
}

// ---------- taking over from AnkiConnect ----------

// Server page: AnkiConnect's state and the way to take over from it. The
// takeover saves at once, so it waits until nothing else is unsaved.
function ankiConnectRow() {
  const ac = S.ankiconnect;
  const dirty = anyUnsaved();
  const why = !ac.config_available ? "AnkiConnect has no settings to import."
    : dirty ? "Save or discard your changes first." : null;
  const tookOver = !ac.enabled && ac.imported;
  // Nothing left to do once Tsunagi runs in its place: one sentence, no link or help.
  if (tookOver) return row("AnkiConnect", h("span", { id: "ankiconnectStatus" }, `Turned off. Tsunagi took over on ${ac.history}.`));
  return row("AnkiConnect", [
    h("span", { id: "ankiconnectStatus" }, ac.enabled ? "Turned on" : "Turned off"), " ",
    link("Take over from AnkiConnect…", () => openTakeover(false), { id: "takeoverOpen", disabled: !!why, title: why })],
    "Tsunagi can run in AnkiConnect's place, on its port, so apps built for AnkiConnect keep working.");
}

async function openTakeover(startup) {
  if (!startup && anyUnsaved()) return showError("Save or discard your changes first.");
  const preview = await call("takeover_preview");
  if (preview.error) return showError(preview.error);
  takeover = { startup, preview, busy: false, done: false };
  changed(true);
  document.getElementById("takeoverYes")?.focus();
}

// Not now / Done: at first start the window only opened for this, so it closes.
function endTakeover() {
  const startup = takeover.startup;
  takeover = null;
  if (startup) call("close"); else changed(true);
}

async function applyTakeover() {
  takeover.busy = true;
  changed(true);
  const res = await call("takeover");
  if (res.error) { takeover = null; changed(true); return showError(res.error); }
  takeover.done = true;
  load(res.state);
  changed(true);
  document.getElementById("takeoverDone")?.focus();
}

// Label/value rows, like the settings page's own rows: what the takeover changes, or changed.
const facts = (rows) => h("dl", { class: "facts" }, rows.map(([label, value, muted]) =>
  [h("dt", {}, label), h("dd", { class: muted ? "muted" : null }, value)]));

function takeoverDialog() {
  const p = takeover.preview;
  const dialog = (...kids) => h("div", { class: "overlay", role: "dialog", "aria-modal": "true", "aria-labelledby": "takeoverTitle" },
    h("div", { class: "dialog takeover" }, ...kids));
  if (takeover.done) {
    return dialog(
      h("div", { class: "title" }, icon("done"), h("h2", { id: "takeoverTitle" }, "Tsunagi is now running in place of AnkiConnect")),
      h("p", { class: "lead" }, "Apps that used AnkiConnect keep working without changes."),
      facts([["Port", String(p.port)], ["AnkiConnect", "Turned off"]]),
      h("p", { class: "next" }, link("Recent requests", () => { takeover = null; go("requests"); }, { id: "takeoverRequests" }),
        " shows which apps connect, and anything refused."),
      h("div", { class: "dialog-actions" },
        takeover.startup && h("button", { type: "button", id: "takeoverSettings", onclick: () => { takeover = null; changed(true); } }, "Open settings"),
        h("span", { class: "spacer" }),
        h("button", { type: "button", class: "primary", id: "takeoverDone", onclick: endTakeover }, "Done")));
  }
  const MAX_SITES = 4;
  const sites = p.new_origins.length;
  const siteList = p.new_origins.slice(0, MAX_SITES).map((o) => h("div", {}, o))
    .concat(sites > MAX_SITES ? [h("div", { class: "muted" }, `and ${sites - MAX_SITES} more`)] : []);
  return dialog(
    h("h2", { id: "takeoverTitle" }, "Take over from AnkiConnect?"),
    h("p", { class: "lead" }, (takeover.startup ? "AnkiConnect is installed. " : "") +
      "Tsunagi can run in its place, so apps that use AnkiConnect keep working without changes."),
    facts([
      ["Port", p.port_from !== p.port ? [String(p.port_from), h("span", { class: "muted" }, " → "), String(p.port)] : String(p.port)],
      p.key === "new" ? ["API key", "Added as the app “AnkiConnect key”"]
        : p.key === "same" ? ["API key", "Already imported", true] : ["API key", "None: AnkiConnect has no key", true],
      sites ? ["Websites", [h("div", {}, `${sites} added`), ...siteList]] : ["Websites", "Nothing new to add", true],
      ["AnkiConnect", p.enabled ? "Turned off and its server stopped" : "Already turned off", !p.enabled],
    ]),
    h("div", { class: "dialog-actions" },
      h("span", { class: "spacer" }),
      h("button", { type: "button", id: "takeoverNo", disabled: takeover.busy, onclick: endTakeover }, "Not now"),
      h("button", { type: "button", class: "primary", id: "takeoverYes", disabled: takeover.busy, onclick: applyTakeover },
        takeover.busy ? "Taking over…" : "Take over")));
}

// The takeover dialog draws from its own state on every redraw, in a layer of
// its own under Kiso's #modal, where the close prompt opens over it.
const takeoverLayer = h("div", { id: "takeoverLayer" });
function renderTakeover() {
  takeoverLayer.replaceChildren(...(takeover ? [takeoverDialog()] : []));
}

// Fields update the draft in their own handlers; these run after them.
for (const type of ["input", "change"]) {
  document.getElementById("main").addEventListener(type, () => { if (S) changed(false); });
}
// The sidebar leaves the role editor (Kiso's buttons then set `page` and redraw).
document.getElementById("nav").addEventListener("click", () => { editing = null; }, true);

// A wave from x=-len to past the indicator's right edge: shifting it by one
// wavelength loops seamlessly. amp 0 draws the same commands flat, so the
// browser can ease between the two shapes.
function wave(y, amp, len) {
  let d = `M${-len} ${y} q${len / 4} ${-amp} ${len / 2} 0`;
  for (let x = -len / 2; x < 36; x += len / 2) d += ` t${len / 2} 0`;
  return d;
}

// The server indicator: a small river seen in depth, the near (bottom) line
// fastest. Built once, so stopping the server calms its waves to flat lines.
function streamIndicator() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 22 12");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "indicator");
  for (const [cls, y, amp, len] of [["far", 2.8, 1.2, 8], ["mid", 5.9, 1.8, 10], ["near", 9.2, 2.4, 12]]) {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("class", cls);
    path.setAttribute("d", wave(y, amp, len));
    path.style.setProperty("--wave", `path("${wave(y, amp, len)}")`);
    path.style.setProperty("--flat", `path("${wave(y, 0, len)}")`);
    svg.append(path);
  }
  return svg;
}

// Ease the flow's speed to `to` (1 = full, 0 = paused) over `ms`, alongside
// the waves' CSS transition: the river slows as it calms and picks up as it
// rises. At 0 the animations pause, so a stopped server keeps nothing ticking.
function easeFlow(svg, to, ms, ease) {
  // Only the flow (CSS animations): the waves' shape and colour transitions
  // must run their full course, or the river stops part-way to flat and grey.
  const flows = svg.getAnimations({ subtree: true }).filter((a) => a.animationName);
  if (!flows.length) return;   // reduced motion: there is no flow
  cancelAnimationFrame(svg.flowFrame);
  const from = flows[0].playState === "paused" ? 0 : flows[0].playbackRate;
  if (!ms) {
    flows.forEach((a) => { a.playbackRate = to || 1; if (to) a.play(); else a.pause(); });
    return;
  }
  flows.forEach((a) => { a.playbackRate = from; a.play(); });
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / ms);
    flows.forEach((a) => { a.playbackRate = from + (to - from) * ease(t); });
    if (t < 1) svg.flowFrame = requestAnimationFrame(step);
    else if (!to) flows.forEach((a) => a.pause());
  };
  svg.flowFrame = requestAnimationFrame(step);
}
const easeOut = (t) => 1 - (1 - t) ** 3;
const easeInOut = (t) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2);

// Whether the server is up, polled: saving can restart it, Anki can stop it.
let serverUrl;   // undefined until the first poll, then the URL or null
async function pollServer() {
  const st = await call("server_status");
  const url = st && st.running ? st.url : null;
  if (url === serverUrl) return;
  const el = document.getElementById("server");
  const first = serverUrl === undefined;
  serverUrl = url;
  if (first) el.replaceChildren(streamIndicator(), h("span"));
  // The first state shows at once; later changes ease the waves and their
  // flow up or down together (the durations match settings.css).
  el.classList.toggle("instant", first);
  el.classList.toggle("on", url !== null);
  el.classList.toggle("off", url === null);
  if (first) easeFlow(el.firstChild, url ? 1 : 0, 0);
  else if (url) easeFlow(el.firstChild, 1, 2200, easeInOut);
  else easeFlow(el.firstChild, 0, 2400, easeOut);
  el.lastChild.replaceChildren(...(url ? ["Server running", h("span", { class: "muted" }, " on " + url.replace("http://", ""))]
                                       : ["Server off"]));
  if (first) requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("instant")));
}

let shownPage = null;
Kiso.setup({
  prefix: "tsunagi",
  pages: PAGES.map(([id, title]) => ({
    id, title, icon: id, render: () => PAGE[id](), slice: (d) => sliceOf(id, d),
    revert: REVERT[id], restore: RESTORE[id], restoreLabel: "Restore this page's defaults",
    restoreTitle: "Back to the defaults for this page only. Nothing changes until Save.",
  })),
  footer: () => [h("span", { id: "version", class: "muted" }), h("span", { id: "server", class: "server", role: "status" })],
  onLoad: (state) => {
    document.getElementById("version").textContent = "Tsunagi " + state.version;
    document.getElementById("modal").before(takeoverLayer);
    pollServer();
    setInterval(() => { pollServer(); if (page === "requests") refreshRequests(); }, 2000);
    if (state.offer_takeover) openTakeover(true);
  },
  beforeRender: () => {
    if (page !== shownPage && page === "requests") refreshRequests();
    shownPage = page;
  },
  afterRender: renderTakeover,
  // Cancel drops unsaved edits on every page; what was open for them goes too.
  onCancel: () => {
    openApps.clear();
    if (editing && !saved.roles.some((r) => r.id === editing)) editing = null;
  },
});
