"use strict";
// Tsunagi settings page. Talks to Python only through Anki's pycmd bridge
// (adapters/settings_page.py, SettingsBridge). No build step.

const SECTIONS = [
  ["connection", "Connection"],
  ["access", "Apps & access"],
  ["groups", "Groups"],
  ["advanced", "Advanced"],
  ["ankiconnect", "AnkiConnect"],
];

let S = null;          // state from Python (fields, catalog, groups' defaults...)
let draft = null;      // what Save sends
let savedRemote = "none";
let section = "connection";
let selectedGroup = "default";
let pending = null;    // staged AnkiConnect import summary
const shownKeys = new Set();
const openAreas = new Set();

function call(op, arg) {
  return new Promise((resolve) => {
    pycmd("tsunagi:" + JSON.stringify({ op, arg }), resolve);
  });
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
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function load(state, restoring) {
  S = state;
  draft = {
    values: { ...state.values },
    gates: Object.fromEntries(state.gates.map((g) => [g.key, g.on])),
    apps: state.apps.map((a) => ({ ...a })),
    groups: state.groups.map((g) => ({ id: g.id, name: g.name, grants: [...g.grants] })),
    confirm_remote: false,
    pending_import: false,
  };
  for (const row of state.no_key_rows) draft[row.setting] = row.group;
  if (!restoring) savedRemote = draft.no_key_remote_group;
  pending = null;
  shownKeys.clear();
  if (!draft.groups.some((g) => g.id === selectedGroup)) selectedGroup = "default";
  document.getElementById("version").textContent = "Tsunagi " + state.version;
  render();
}

function render() {
  const nav = document.getElementById("nav");
  nav.replaceChildren(...SECTIONS.map(([id, title]) =>
    h("button", { type: "button", "data-section": id, "aria-current": String(id === section),
                  onclick: () => { section = id; render(); } }, title)));
  const main = document.getElementById("main");
  const scroll = main.scrollTop;
  main.replaceChildren(...RENDER[section]());
  main.scrollTop = scroll;
}

// ---------- fields ----------

const field = (key) => S.fields.find((f) => f.key === key);

function fieldInput(f) {
  const set = (v) => { draft.values[f.key] = v; };
  const v = draft.values[f.key];
  if (f.kind === "bool") {
    return h("input", { type: "checkbox", id: f.key, checked: v,
                        onchange: (e) => set(e.target.checked) });
  }
  if (f.kind === "int" || f.kind === "mib") {
    const num = (e) => { const n = Number(e.target.value); set(Number.isInteger(n) ? n : e.target.value); };
    return h("span", {}, h("input", { type: "number", id: f.key, min: f.minimum, max: f.maximum,
                                      value: v, oninput: num }),
             f.kind === "mib" ? " MiB" : "");
  }
  if (f.kind === "choice") {
    return h("select", { id: f.key, onchange: (e) => set(e.target.value) },
             f.choices.map((c) => h("option", { value: c, selected: c === v }, c)));
  }
  if (f.kind === "cors_list") {
    return h("textarea", { id: f.key, spellcheck: "false", value: v,
                           oninput: (e) => set(e.target.value) });
  }
  return h("input", { type: "text", id: f.key, spellcheck: "false", value: v,
                      oninput: (e) => set(e.target.value) });
}

function fieldRow(key, help) {
  const f = field(key);
  if (f.kind === "bool") {
    return h("div", { class: "check" }, fieldInput(f),
             h("label", { for: f.key }, h("b", {}, f.label), h("div", { class: "help" }, help || f.tooltip)));
  }
  return h("div", { class: "row" }, h("label", { for: f.key }, f.label),
           h("div", {}, fieldInput(f), h("div", { class: "help" }, help || f.tooltip)));
}

function portRow() {
  const fixed = draft.values.port !== 0;
  const mode = h("select", { id: "portMode", onchange: (e) => {
    draft.values.port = e.target.value === "fixed" ? draft.values.prefer_port : 0;
    render();
  } }, h("option", { value: "preferred", selected: !fixed }, "Use preferred port"),
       h("option", { value: "fixed", selected: fixed }, "Use a fixed port"));
  const key = fixed ? "port" : "prefer_port";
  const input = h("input", { type: "number", id: key, min: 1, max: 65535, value: draft.values[key],
                             oninput: (e) => { const n = Number(e.target.value);
                                               draft.values[key] = Number.isInteger(n) ? n : e.target.value; } });
  return h("div", { class: "row" }, h("label", { for: "portMode" }, "Port"),
           h("div", {}, mode, " ", input,
             h("div", { class: "help" }, "The port must be free. Tsunagi does not pick another one if it is busy.")));
}

// ---------- groups ----------

const groupById = (id) => draft.groups.find((g) => g.id === id);
const groupName = (id) => (groupById(id) || { name: id + " (missing)" }).name;

function groupSelect(value, onchange, id) {
  return h("select", { id, onchange: (e) => onchange(e.target.value) },
           draft.groups.map((g) => h("option", { value: g.id, selected: g.id === value }, g.name)),
           groupById(value) ? null : h("option", { value, selected: true }, value + " (missing)"));
}

function usersOf(id) {
  const users = draft.apps.filter((a) => a.group === id).map((a) => a.name || "(unnamed app)");
  for (const row of S.no_key_rows) if (draft[row.setting] === id) users.push("No key: " + row.label);
  return users;
}

// ---------- sections ----------

const RENDER = {
  connection() {
    return [
      h("h1", {}, "Connection"),
      h("p", { class: "lead" }, "Whether the API runs, and where. Changes here restart the server when you save."),
      h("div", { class: "card" },
        fieldRow("enabled"),
        portRow(),
        fieldRow("host", "127.0.0.1 accepts connections from this computer only. Any other address lets other " +
                         "devices connect; without a key they get the group set under Apps & access (No access by default).")),
    ];
  },

  access() {
    const remoteChanged = draft.no_key_remote_group !== "none" && draft.no_key_remote_group !== savedRemote;
    const noKey = h("div", { class: "card" },
      h("h2", {}, "Without a key"),
      h("p", { class: "help" }, "Requests that send no key, or a key no app has, get the group of the row they come from."),
      S.no_key_rows.map((row) => h("div", { class: "row" },
        h("label", { for: row.setting }, row.label),
        h("div", {}, groupSelect(draft[row.setting], (v) => { draft[row.setting] = v; draft.confirm_remote = false; render(); }, row.setting),
          h("div", { class: "help" }, row.help)))),
      remoteChanged && h("div", { class: "warn" },
        h("div", { class: "check" },
          h("input", { type: "checkbox", id: "confirmRemote", checked: draft.confirm_remote,
                       onchange: (e) => { draft.confirm_remote = e.target.checked; } }),
          h("label", { for: "confirmRemote" },
            "Anyone who can reach this computer's port gets ", h("b", {}, groupName(draft.no_key_remote_group)),
            " without a key, including every device on your network. I understand."))));

    const rows = draft.apps.map((app, i) => {
      const shown = shownKeys.has(i);
      return h("div", { class: "app" },
        h("div", { class: "app-line" },
          h("input", { type: "text", class: "app-name", "aria-label": "App name", value: app.name,
                       oninput: (e) => { app.name = e.target.value; } }),
          groupSelect(app.group, (v) => { app.group = v; render(); }),
          h("span", { class: "spacer" }),
          h("button", { type: "button", class: "link danger", "aria-label": "Remove " + app.name,
                        onclick: () => { draft.apps.splice(i, 1); shownKeys.clear(); render(); } }, "Remove")),
        h("div", { class: "app-line" },
          h("input", { type: shown ? "text" : "password", class: "key", "aria-label": "Key", spellcheck: "false",
                       value: app.key, oninput: (e) => { app.key = e.target.value; } }),
          h("button", { type: "button", class: "link", onclick: () => { shown ? shownKeys.delete(i) : shownKeys.add(i); render(); } },
            shown ? "Hide" : "Show"),
          h("button", { type: "button", class: "link", onclick: () => call("copy", app.key) }, "Copy"),
          h("button", { type: "button", class: "link", title: "Replace with a new random key and copy it. Apps using the old key stop working after Save.",
                        onclick: async () => { app.key = await call("new_key"); shownKeys.add(i); call("copy", app.key); render(); } },
            "New key")));
    });
    const apps = h("div", { class: "card" },
      h("h2", {}, "Apps"),
      h("p", { class: "help" }, "Give each tool its own key to choose what it may do. A tool sends its key as the " +
        "X-Api-Key header, or as \"key\" in AnkiConnect requests."),
      draft.apps.length ? h("div", { class: "apps" }, rows) : h("p", { class: "muted" }, "No apps yet."),
      h("button", { type: "button", id: "addApp", onclick: async () => {
        const key = await call("new_key");
        let n = draft.apps.length + 1;
        while (draft.apps.some((a) => a.name === "New app " + n)) n++;
        draft.apps.push({ name: "New app " + n, key, group: "default" });
        shownKeys.add(draft.apps.length - 1);
        call("copy", key);
        render();
      } }, "Add app"),
      h("span", { class: "help" }, "  A new key is copied to the clipboard."));

    const sites = h("div", { class: "card" },
      h("h2", {}, "Websites and Anki's pages"),
      fieldRow("cors_allowlist", "Browser origins allowed to call the API, one per line (\"*\" allows all). " +
               "\"http://localhost\" also covers 127.0.0.1 pages and browser extensions, as in AnkiConnect."),
      S.gates.map((g) => h("div", { class: "check" },
        h("input", { type: "checkbox", id: "gate_" + g.key, checked: draft.gates[g.key],
                     onchange: (e) => { draft.gates[g.key] = e.target.checked; } }),
        h("label", { for: "gate_" + g.key }, h("b", {}, g.label), h("div", { class: "help" }, g.tooltip)))));

    return [h("h1", {}, "Apps & access"),
            h("p", { class: "lead" }, "Who may use the API and what they may do. Each app and each row below is in a group; " +
              "groups are defined under Groups."),
            noKey, apps, sites];
  },

  groups() {
    const g = groupById(selectedGroup);
    const list = h("div", { class: "grouplist" },
      draft.groups.map((grp) => h("button", { type: "button", "aria-current": String(grp.id === selectedGroup),
                                              "data-group": grp.id,
                                              onclick: () => { selectedGroup = grp.id; render(); } },
        h("span", {}, grp.name),
        h("span", { class: "muted small" }, usersOf(grp.id).length ? "used by " + usersOf(grp.id).length : "unused"))),
      h("button", { type: "button", id: "newGroup", onclick: () => {
        let n = 1;
        while (groupById("custom_" + n)) n++;
        draft.groups.push({ id: "custom_" + n, name: "New group " + n, grants: [...g.grants] });
        selectedGroup = "custom_" + n;
        render();
      } }, "+ New group"));
    return [h("h1", {}, "Groups"),
            h("p", { class: "lead" }, "A group lists what its apps may do. Tick a whole area, or choose parts of it. " +
              "+ New group starts as a copy of the selected one."),
            list, groupEditor(g)];
  },

  advanced() {
    return [h("h1", {}, "Advanced"),
            h("div", { class: "card" }, S.fields.filter((f) => f.section === "Advanced").map((f) => fieldRow(f.key)))];
  },

  ankiconnect() {
    const ac = S.ankiconnect;
    const status = !ac.installed ? "Not installed" : ac.enabled ? "Enabled" : "Disabled";
    const body = pending
      ? h("div", { class: "card", id: "pendingImport" },
          h("h2", {}, "Ready to import"),
          h("div", { class: "row" }, h("label", {}, "Port"), h("div", {}, String(pending.port))),
          h("div", { class: "row" }, h("label", {}, "API key"), h("div", {}, pending.key)),
          h("div", { class: "row" }, h("label", {}, "Website origins"), h("div", {}, pending.origins)),
          h("p", { class: "help" }, ac.enabled ? "Save to apply these settings and disable AnkiConnect."
                                                : "Save to apply these settings."))
      : h("div", { class: "card" },
          h("p", {}, !ac.config_available ? "No AnkiConnect settings are available to import."
                   : ac.imported ? "Import again if you've changed your AnkiConnect settings."
                   : "Copy AnkiConnect's port and key (as the app \"AnkiConnect key\"), and merge its allowed website origins."),
          h("button", { type: "button", id: "importAnkiConnect", disabled: !ac.config_available, onclick: async () => {
            const res = await call("import_ankiconnect", draft);
            if (res.error) return showErrors([res.error]);
            draft.values = res.values;
            draft.apps = res.apps;
            draft.pending_import = true;
            pending = res.pending;
            render();
          } }, ac.imported ? "Import settings again" : "Import AnkiConnect settings"));
    return [h("h1", {}, "AnkiConnect"),
            h("p", { class: "lead" }, "Tsunagi answers AnkiConnect requests, so tools built for it keep working."),
            h("div", { class: "card" },
              h("div", { class: "row" }, h("label", {}, "Add-on"), h("div", { id: "ankiconnectStatus" }, status)),
              h("div", { class: "row" }, h("label", {}, "Last import"), h("div", {}, ac.history))),
            body];
  },
};

function groupEditor(g) {
  const locked = g.id === "none";
  const def = S.groups.find((x) => x.id === g.id)?.default;
  const same = def && def.name === g.name && [...g.grants].sort().join() === [...def.grants].sort().join();
  const users = usersOf(g.id);
  const setGrants = (grants) => { g.grants = [...new Set(grants)].sort(); render(); };
  const areas = S.catalog.map((area) => {
    const names = area.names.map((n) => n.name);
    const all = g.grants.includes(area.area);
    const some = names.filter((n) => g.grants.includes(n));
    const head = h("input", { type: "checkbox", id: "area_" + area.area, checked: all, disabled: locked,
      onchange: (e) => setGrants(g.grants.filter((x) => x !== area.area && !names.includes(x))
                                          .concat(e.target.checked ? [area.area] : [])) });
    head.indeterminate = !all && some.length > 0;
    const open = openAreas.has(area.area) || (!all && some.length > 0);
    return h("div", { class: "area" },
      h("div", { class: "area-head" },
        h("div", { class: "check" }, head,
          h("label", { for: "area_" + area.area }, h("b", {}, area.label), h("div", { class: "help" }, area.description))),
        names.length > 0 && h("button", { type: "button", class: "link", onclick: () => {
          openAreas.has(area.area) ? openAreas.delete(area.area) : openAreas.add(area.area); render(); } },
          open ? "Hide parts" : "Choose parts…")),
      open && names.length > 0 && h("div", { class: "names" }, area.names.map((n) =>
        h("div", { class: "check" },
          h("input", { type: "checkbox", id: "perm_" + n.name, checked: all || some.includes(n.name), disabled: locked,
            onchange: (e) => {
              let chosen = all ? names : some;
              chosen = e.target.checked ? chosen.concat([n.name]) : chosen.filter((x) => x !== n.name);
              const rest = g.grants.filter((x) => x !== area.area && !names.includes(x));
              setGrants(chosen.length === names.length ? rest.concat([area.area]) : rest.concat(chosen));
            } }),
          h("label", { for: "perm_" + n.name }, n.label)))));
  });
  return h("div", { class: "card", id: "groupEditor" },
    h("div", { class: "row" }, h("label", { for: "groupName" }, "Name"),
      h("div", {}, h("input", { type: "text", id: "groupName", value: g.name, disabled: locked,
                                oninput: (e) => { g.name = e.target.value; } }),
        def ? h("span", { class: "tag" }, "Built-in") : null,
        h("div", { class: "help" }, users.length ? "Used by: " + users.join(", ") : "Not used by any app yet."))),
    locked ? h("p", { class: "muted" }, "No access grants nothing and cannot be changed.") : areas,
    h("div", {},
      def && !locked && h("button", { type: "button", id: "resetGroup", disabled: same, onclick: () => {
        g.name = def.name; g.grants = [...def.grants]; render(); } }, "Reset to default"),
      !def && h("button", { type: "button", class: "danger", id: "deleteGroup", disabled: users.length > 0,
        title: users.length ? "Move its apps to another group first." : "",
        onclick: () => { draft.groups = draft.groups.filter((x) => x !== g); selectedGroup = "default"; render(); } },
        "Delete group")));
}

function showErrors(errors) {
  const box = document.getElementById("errors");
  box.hidden = !errors.length;
  box.replaceChildren(h("ul", {}, errors.map((e) => h("li", {}, e))));
}

document.getElementById("save").addEventListener("click", async () => {
  showErrors([]);
  const res = await call("save", draft);
  if (res && res.errors) showErrors(res.errors);
  else if (res && res.error) showErrors([res.error]);
});
document.getElementById("cancel").addEventListener("click", () => call("cancel"));
document.getElementById("restore").addEventListener("click", async () => {
  showErrors([]);
  load(await call("defaults"), true);
});

(function start() {
  // pycmd exists once Anki's web channel is ready.
  if (typeof pycmd !== "function") return setTimeout(start, 20);
  call("state").then((state) => { load(state); window.tsunagiReady = true; });
})();
