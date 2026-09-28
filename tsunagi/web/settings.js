"use strict";
// Tsunagi settings page. Talks to Python only through Anki's pycmd bridge
// (adapters/settings_page.py, SettingsBridge). No build step.

const PAGES = [
  ["server", "Server"],
  ["apps", "Apps & keys"],
  ["nokey", "Requests without a key"],
  ["web", "Websites & Anki pages"],
  ["addons", "Add-ons"],
  ["roles", "Roles"],
  ["ankiconnect", "AnkiConnect"],
];

// Sidebar icons: 24-unit stroke paths drawn in the text colour. They support
// the labels, never replace them (aria-hidden).
const ICONS = {
  server: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  apps: "M14.5 9.5a4 4 0 1 1-1.2-2.8M13.3 10.7 20 17.4V20h-2.6v-2h-2v-2h-2l-.7-.7",
  nokey: "M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M4 12h11M11 8l4 4-4 4",
  web: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z",
  addons: "M5 8h3.5a2 2 0 1 1 3.5-1.5V8H19v4.5a2 2 0 1 0 0 4V20H5z",
  roles: "M4 5h16v14H4zM9 11a2 2 0 1 0 0-.01M6 16c.6-1.7 1.7-2.5 3-2.5s2.4.8 3 2.5M14 10h3M14 13h3",
  ankiconnect: "M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0zM12 16v5",
  chevron: "M9 6l6 6-6 6",
};

function icon(name) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "icon");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

let S = null;          // state from Python: fields, catalog, roles' defaults, defaults...
let draft = null;      // what Save sends
let saved = null;      // the draft as last saved, for "Revert this page"
let preImport = null;  // the draft before a staged AnkiConnect import
let savedRemote = "none";
let page = "server";
let editing = null;    // role id open in the role editor, or null for the list
let pending = null;    // staged AnkiConnect import summary
let closing = false;    // the "unsaved changes" prompt is open (X or Esc)
let reportedDirty = false;
const openApps = new Set();   // app rows showing their detail (full key, New key, Remove)
const openAreas = new Set();

function call(op, arg) {
  return new Promise((resolve) => pycmd("tsunagi:" + JSON.stringify({ op, arg }), resolve));
}

// DOM helper: text always goes through textContent, never innerHTML.
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const link = (label, onclick, attrs) => h("button", { type: "button", class: "link", onclick, ...attrs }, label);
const go = (p, role) => { page = p; editing = role || null; render(); document.getElementById("main").scrollTop = 0; };
const clone = (x) => JSON.parse(JSON.stringify(x));
let notice = "";       // a short footer message, e.g. after a key is copied
let noticeTimer = 0;
function notify(text) {
  notice = text;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice = ""; render(); }, 2500);
  render();
}
function copyKey(key, button) {
  call("copy", key);
  if (button) {
    button.textContent = "Copied";
    button.classList.add("done");
    setTimeout(() => { if (button.isConnected) { button.textContent = "Copy"; button.classList.remove("done"); } }, 1500);
  }
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function draftFrom(state) {
  const d = {
    values: { ...state.values },
    gates: Object.fromEntries(state.gates.map((g) => [g.key, g.on])),
    apps: state.apps.map((a) => ({ ...a })),
    roles: state.roles.map((r) => ({ id: r.id, name: r.name, grants: [...r.grants] })),
    addon_enabled: { ...(state.addon_enabled || {}) },
    confirm_remote: false,
    pending_import: false,
  };
  for (const row of state.no_key_rows) d[row.setting] = row.role;
  return d;
}

function load(state) {
  S = state;
  draft = draftFrom(state);
  saved = draftFrom(state);
  savedRemote = draft.no_key_remote_role;
  document.getElementById("version").textContent = "Tsunagi " + state.version;
  render();
}

// Sidebar dots, footer status and Save/Cancel: cheap, so it also runs on every
// keystroke (see the input listener at the end), without rebuilding the page
// and losing the field's focus.
function renderChrome() {
  document.getElementById("nav").replaceChildren(
    ...PAGES.map(([id, title]) => h("button", { type: "button", "data-page": id,
      "aria-current": String(id === page), onclick: () => go(id) }, icon(id), h("span", { class: "label" }, title),
      changed(id) ? h("span", { class: "dot", title: "Unsaved changes" }, "•") : null)),
  );
  const dirty = PAGES.filter(([id]) => changed(id)).length;
  document.getElementById("status").textContent = notice ||
    (dirty ? `Unsaved changes on ${dirty} page${dirty === 1 ? "" : "s"}` : "");
  // Nothing to save or discard until something differs from what is saved.
  document.getElementById("save").disabled = !dirty;
  document.getElementById("cancel").disabled = !dirty;
  if (!!dirty !== reportedDirty) { reportedDirty = !!dirty; call("dirty", reportedDirty); }
}

function render() {
  renderChrome();
  const main = document.getElementById("main");
  const scroll = main.scrollTop;
  main.replaceChildren(...PAGE[page]().flat(Infinity).filter(Boolean));
  main.scrollTop = scroll;
  document.getElementById("modal").replaceChildren(...(closing ? [closeDialog()] : []));
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
  return d.pending_import;
}
const changed = (p) => !same(sliceOf(p, draft), sliceOf(p, saved));

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
  ankiconnect: (d) => {
    for (const k of ["port", "prefer_port", "enabled", "cors_allowlist"]) d.values[k] = preImport.values[k];
    d.apps = clone(preImport.apps);
    d.pending_import = false;
    pending = null;
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

// Page-state actions share one look on every page, the role editor included.
// Each shows only when it would change something; both wait for Save. The
// labels name their scope; the footer's Cancel covers every page.
function actionBar(revert, restore, ids, what = "page") {
  return h("div", { class: "head-actions" },
    revert && h("button", { type: "button", class: "quiet", id: ids[0], onclick: () => { revert(); render(); },
                            title: `Undo unsaved changes on this ${what} only. Other pages keep theirs.` }, `Revert this ${what}`),
    restore && h("button", { type: "button", class: "quiet", id: ids[1], onclick: () => { restore(); render(); },
                             title: `Back to the defaults for this ${what} only. Nothing changes until Save.` }, `Restore this ${what}'s defaults`));
}

function pageActions(p) {
  const restore = RESTORE[p];
  const noop = !restore || same(sliceOf(p, draft), sliceOf(p, (() => { const d = clone(draft); restore(d); return d; })()));
  return actionBar(changed(p) && (() => REVERT[p](draft)), !noop && (() => restore(draft)), ["revertPage", "restorePage"]);
}

function header(title, lead) {
  return h("header", { class: "page-head" },
    h("div", {}, h("h1", {}, title), lead && h("p", { class: "lead" }, lead)),
    pageActions(page));
}

// ---------- fields ----------

const field = (key) => S.fields.find((f) => f.key === key);
const setNum = (obj, key) => (e) => { const n = Number(e.target.value); obj[key] = Number.isInteger(n) ? n : e.target.value; };

function input(f) {
  const v = draft.values[f.key];
  const set = (x) => { draft.values[f.key] = x; };
  if (f.kind === "bool") return h("input", { type: "checkbox", id: f.key, checked: v, onchange: (e) => set(e.target.checked) });
  if (f.kind === "int" || f.kind === "mib") {
    return h("span", { class: "unit" }, h("input", { type: "number", id: f.key, min: f.minimum, max: f.maximum,
      value: v, oninput: setNum(draft.values, f.key) }), f.kind === "mib" ? "MiB" : "");
  }
  if (f.kind === "choice") {
    return h("select", { id: f.key, onchange: (e) => set(e.target.value) },
             f.choices.map((c) => h("option", { value: c, selected: c === v }, c)));
  }
  if (f.kind === "cors_list") return h("textarea", { id: f.key, spellcheck: "false", value: v, oninput: (e) => set(e.target.value) });
  return h("input", { type: "text", id: f.key, spellcheck: "false", value: v, oninput: (e) => set(e.target.value) });
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
const approved = (a, d = draft) => d.addon_enabled[a.key] === a.level;

// A built-in role's defaults. Default also has every action approved as
// normal, like the server's Settings.role, so approving keeps it unedited.
function defaultOf(r, d = draft) {
  const def = S.roles.find((x) => x.id === r.id)?.default;
  if (!def) return null;
  const extra = r.id !== "default" ? [] : Object.entries(d.addon_enabled)
    .filter(([, level]) => level === "normal").map(([key]) => addonName(key));
  return { name: def.name, grants: [...new Set(def.grants.concat(extra))].sort() };
}

// Approving a normal action also allows it for Default; destructive ones are
// only in Everything until a role adds them. Withdrawing removes it everywhere.
function setApproval(a, on) {
  const name = addonName(a.key);
  if (on) {
    draft.addon_enabled[a.key] = a.level;
    const dflt = roleById("default");
    if (a.level === "normal" && dflt && !dflt.grants.includes(name)) dflt.grants = [...dflt.grants, name].sort();
  } else {
    delete draft.addon_enabled[a.key];
    for (const r of draft.roles) r.grants = r.grants.filter((g) => g !== name);
  }
}

// The role editor's parts of an area. For add-ons: the approved actions.
function namesOf(area) {
  if (area.area !== "addon") return area.names;
  return allActions().filter((a) => a.level !== "read" && approved(a))
    .map((a) => ({ name: addonName(a.key), label: a.title, group: a.provider, destructive: a.level === "destructive" }));
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
                 () => { open ? openDescriptions.delete(a.key) : openDescriptions.add(a.key); render(); },
                 { "aria-expanded": String(open), class: "link fold" }));
}

// One action, two table rows: the switch and the name keep their places on
// every row; the add-on's description wraps on the line below. Which roles may
// run it is shown in Roles, not here.
function actionRows(a, shared) {
  const read = a.level === "read";
  const on = read || approved(a);
  const relabelled = !read && !approved(a) && a.key in draft.addon_enabled;
  const id = "approve_" + a.key.replace("/", "__");
  return [
    h("tr", { class: "action " + a.level, id: rowId(a), "data-action": a.key },
      h("td", { class: "approve" },
        h("input", { type: "checkbox", id, checked: on, disabled: read, "aria-label": "Enable " + a.title,
                     title: read ? "Reading is always enabled; the app's role decides" : null,
                     onchange: (e) => { setApproval(a, e.target.checked); render(); } })),
      h("td", { class: "name" }, h("label", { for: id }, a.title),
        a.level === "destructive" && h("span", { class: "tag danger" }, "Destructive: backup first"),
        !shared.ui && a.shows_ui && h("span", { class: "tag" }, "Shows windows here"))),
    h("tr", { class: "action-more " + a.level }, h("td", {}), h("td", {},
      description(a),
      relabelled && h("div", { class: "desc warn-text" }, "The add-on changed this action since you enabled it. Enable it again."))),
  ];
}

function providerCard(p) {
  const acts = p.actions.filter((a) => a.level !== "read");
  const reads = p.actions.filter((a) => a.level === "read");
  const ready = acts.filter((a) => a.level === "normal" && !approved(a));
  // Said once under the heading when every action shares it, not on each row.
  const shared = { ui: acts.length > 0 && acts.every((a) => a.shows_ui),
                   normal: acts.length > 0 && acts.every((a) => a.level === "normal") };
  const notes = [shared.normal && `All ${acts.length} change your collection.`,
                 shared.ui && "They show a progress window or message on this computer while running."].filter(Boolean);
  const section = (label) => h("tr", { class: "section" }, h("td", { colspan: 2 }, label));
  return h("section", { class: "card flush addon", "data-provider": p.id },
    h("div", { class: "addon-head" },
      h("h2", {}, p.title),
      acts.length > 0 && h("span", { class: "muted small count" }, `${acts.filter((a) => approved(a)).length} of ${acts.length} enabled`),
      ready.length > 0 && h("button", { type: "button", class: "quiet", "data-approve-all": p.id,
        title: "Enable every action here except destructive ones, which you enable one by one.",
        onclick: () => { ready.forEach((a) => setApproval(a, true)); render(); } }, "Enable all")),
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
    h("select", { id, "aria-label": label, onchange: (e) => { onchange(e.target.value); render(); } },
      draft.roles.map((r) => h("option", { value: r.id, selected: r.id === value }, r.name)),
      roleById(value) ? null : h("option", { value, selected: true }, value + " (missing)")),
    link("View", () => go("roles", value), { title: "Open this role" }));
}

const userLinks = (users) => users.map((u, i) => [i ? ", " : "", link(u.label, () => go(u.page))]);

// ---------- pages ----------

const PAGE = {
  server() {
    const fixed = draft.values.port !== 0;
    const portKey = fixed ? "port" : "prefer_port";
    return [
      header("Server", "Whether the API runs and where. Server changes restart it when you save."),
      h("section", { class: "card" },
        h("div", { class: "check" }, input(field("enabled")),
          h("label", { for: "enabled" }, h("b", {}, "Run the Tsunagi server"),
            h("span", { class: "help inline" }, " When off, the API does not start with Anki."))),
        row("Port", h("span", { class: "inline-controls" },
          h("select", { id: "portMode", onchange: (e) => { draft.values.port = e.target.value === "fixed" ? draft.values.prefer_port : 0; render(); } },
            h("option", { value: "preferred", selected: !fixed }, "Preferred port"),
            h("option", { value: "fixed", selected: fixed }, "Fixed port")),
          h("input", { type: "number", id: portKey, min: 1, max: 65535, value: draft.values[portKey], oninput: setNum(draft.values, portKey) })),
          "Must be free; Tsunagi does not pick another port.", "portMode"),
        row("Host", input(field("host")),
          "127.0.0.1: this computer only. Any other address lets other devices connect; they need a key (see Requests without a key).", "host")),
      h("section", { class: "card" },
        h("h2", {}, "Limits and logging"),
        h("div", { class: "grid4" }, S.fields.filter((f) => f.section === "Advanced").map((f) =>
          h("div", { class: "cell" }, h("label", { for: f.key, title: f.tooltip }, f.label), input(f))))),
    ];
  },

  apps() {
    const rows = draft.apps.map((app, i) => {
      const open = openApps.has(i);
      const toggle = () => { open ? openApps.delete(i) : openApps.add(i); render(); };
      const out = [h("tr", { class: "app" },
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
        out.push(h("tr", { class: "app-detail" }, h("td", { colspan: 4 },
          h("div", { class: "detail" },
            h("label", { class: "detail-label" }, "Key"),
            h("input", { type: "text", class: "key", "aria-label": "Key of " + app.name, spellcheck: "false",
                         value: app.key, oninput: (e) => { app.key = e.target.value; } }),
            h("button", { type: "button", title: "Replace with a new random key and copy it. The old key stops working after Save.",
                          onclick: async () => { app.key = await call("new_key"); copyKey(app.key); notify("New key copied. It works once you save; until then the old key stays active."); } }, "New key"),
            h("span", { class: "spacer" }),
            h("button", { type: "button", class: "danger", "aria-label": "Remove " + app.name,
                          onclick: () => { draft.apps.splice(i, 1); openApps.clear(); render(); } }, "Remove app")))));
      }
      return out;
    });
    return [
      header("Apps & keys", "Give each tool its own key and role. Tools send the key as the X-Api-Key header, " +
             "or as \"key\" in AnkiConnect requests."),
      h("section", { class: "card flush" },
        draft.apps.length
          ? h("table", { class: "table" },
              h("thead", {}, h("tr", {}, h("th", {}, "App"), h("th", {}, "Role"), h("th", {}, "Key"), h("th", {}))),
              h("tbody", {}, rows))
          : h("p", { class: "empty" }, "No apps yet. Tools on this computer work without a key; add an app to give " +
              "one its own role, or to connect from another device."),
        h("div", { class: "card-foot" },
          h("button", { type: "button", id: "addApp", onclick: async () => {
            const key = await call("new_key");
            let n = draft.apps.length + 1;
            while (draft.apps.some((a) => a.name === "New app " + n)) n++;
            draft.apps.push({ name: "New app " + n, key, role: "default" });
            openApps.add(draft.apps.length - 1);
            copyKey(key);
            notify("New app added and its key copied. The key works once you save.");
          } }, "Add app"))),
    ];
  },

  nokey() {
    const remoteChanged = draft.no_key_remote_role !== "none" && draft.no_key_remote_role !== savedRemote;
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
          h("input", { type: "checkbox", id: "confirmRemote", checked: draft.confirm_remote,
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

  ankiconnect() {
    const ac = S.ankiconnect;
    const status = !ac.installed ? "Not installed" : ac.enabled ? "Installed and enabled" : "Installed, disabled";
    return [
      header("AnkiConnect", "Tsunagi answers AnkiConnect requests, so tools built for it keep working."),
      h("section", { class: "card" },
        row("Add-on", h("span", { id: "ankiconnectStatus" }, status)),
        row("Last import", ac.history),
        pending
          ? h("div", { id: "pendingImport", class: "pending" },
              h("h2", {}, "Ready to import"),
              row("Port", String(pending.port)), row("Key", pending.key), row("Website origins", pending.origins),
              h("p", { class: "help" }, ac.enabled ? "Save to apply these settings and disable AnkiConnect." : "Save to apply these settings."))
          : h("div", { class: "import" },
              h("p", { class: "help" }, !ac.config_available ? "No AnkiConnect settings to import."
                : "Copies its port and key (as the app \"AnkiConnect key\") and merges its website origins. Nothing changes until Save."),
              h("button", { type: "button", id: "importAnkiConnect", disabled: !ac.config_available, onclick: async () => {
                const res = await call("import_ankiconnect", draft);
                if (res.error) return showErrors([res.error]);
                preImport = clone(draft);
                draft.values = res.values;
                draft.apps = res.apps;
                draft.pending_import = true;
                pending = res.pending;
                render();
              } }, ac.imported ? "Import settings again" : "Import AnkiConnect settings"))),
    ];
  },
};

function roleEditor(r) {
  const locked = r.id === "none";
  const def = defaultOf(r);
  const isDefault = def && sameRole(def, r);
  const savedRole = saved.roles.find((x) => x.id === r.id);
  const users = usersOf(r.id);
  const setGrants = (grants) => { r.grants = [...new Set(grants)].sort(); render(); };
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
           link(open ? "Done" : "Choose", () => { open ? openAreas.delete(area.area) : openAreas.add(area.area); render(); },
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
      actionBar(savedRole && !sameRole(savedRole, r) && (() => { r.name = savedRole.name; r.grants = [...savedRole.grants]; }),
                def && !locked && !isDefault && (() => { r.name = def.name; r.grants = [...def.grants]; }),
                ["revertRole", "resetRole"], "role")),
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
    const acts = allActions().filter((a) => a.provider === p.title && a.level !== "read");
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
          h("td", {}, h("label", { for: permId(a), class: a.level === "destructive" ? "destructive" : null }, a.title),
            a.level === "destructive" && h("span", { class: "tag danger" }, "Destructive")),
          h("td", { class: "status" }, h("span", { class: "tag " + (ok ? "ok" : "off") }, status[0]), " ", status[1],
            !ok && [" ", link("Enable…", () => { go("addons"); const row = document.getElementById(rowId(a));
                                                             if (row) { row.scrollIntoView({ block: "center" }); row.classList.add("flash"); } },
                              { title: "Open this action on the Add-ons page" })]));
      }))));
  })];
}

// X or Esc with unsaved changes (Python calls askClose instead of closing).
function closeDialog() {
  const dirty = PAGES.filter(([id]) => changed(id)).map(([, title]) => title);
  return h("div", { class: "overlay", role: "dialog", "aria-modal": "true", "aria-labelledby": "closeTitle" },
    h("div", { class: "dialog" },
      h("h2", { id: "closeTitle" }, "Save your changes?"),
      h("p", {}, "You have unsaved changes on: " + dirty.join(", ") + "."),
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", id: "keepEditing", onclick: () => { closing = false; render(); } }, "Keep editing"),
        h("span", { class: "spacer" }),
        h("button", { type: "button", id: "discardClose", onclick: () => call("close") }, "Discard"),
        h("button", { type: "button", class: "primary", id: "saveClose", onclick: () => { closing = false; save(true); } }, "Save"))));
}
window.askClose = () => { closing = true; render(); document.getElementById("saveClose")?.focus(); };

function showErrors(errors) {
  const box = document.getElementById("errors");
  box.hidden = !errors.length;
  box.replaceChildren(h("ul", {}, errors.map((e) => h("li", {}, typeof e === "string" ? e : e.message))));
}

// Neither Save nor Cancel closes the window; only X/Esc does (asking first
// when there are unsaved changes, and that prompt's Save also closes).
// Save validates every page. On a problem it goes to the page that has it,
// with the field focused; otherwise the saved state is the new baseline.
async function save(close = false) {
  showErrors([]);
  const res = await call("save", { ...draft, close });
  const errors = (res && res.errors) || (res && res.error ? [res.error] : []);
  if (!errors.length) {
    if (res && res.state) { load(res.state); discardDraft(); notify("Saved"); }
    return;
  }
  showErrors(errors);
  const first = errors.find((e) => e.page);
  if (!first) return;
  if (first.page !== page) go(first.page);
  const el = first.field && document.getElementById(first.field);
  if (el) { el.scrollIntoView({ block: "center" }); el.focus(); el.classList.add("flash"); }
}

// Cancel: throw away unsaved changes on every page (Revert this page is the
// per-page version).
function discardDraft() {
  draft = draftFrom(S);
  pending = null; preImport = null;
  openApps.clear();
  if (editing && !roleById(editing)) editing = null;
  showErrors([]);
}

document.getElementById("save").addEventListener("click", () => save());
// Fields update the draft in their own handlers; these run after them.
for (const type of ["input", "change"]) {
  document.getElementById("main").addEventListener(type, () => { if (S) renderChrome(); });
}
document.getElementById("cancel").addEventListener("click", () => {
  discardDraft();
  notify("Unsaved changes on every page discarded");
});

// Whether the server is up, polled: saving can restart it, Anki can stop it.
async function pollServer() {
  const st = await call("server_status");
  const el = document.getElementById("server");
  el.className = "server " + (st && st.running ? "on" : "off");
  el.replaceChildren(h("span", { class: "indicator", "aria-hidden": "true" }),
    ...(st && st.running ? ["Server running", h("span", { class: "muted" }, " on " + st.url.replace("http://", ""))]
                         : ["Server off"]));
}

(function start() {
  // pycmd exists once Anki's web channel is ready.
  if (typeof pycmd !== "function") return setTimeout(start, 20);
  call("state").then((state) => { load(state); window.tsunagiReady = true; });
  pollServer();
  setInterval(pollServer, 2000);
})();
