// Home page: the hub's figures and four explainers (a mining session replayed, one popup request by
// request, the event stream, roles).
(() => {
  "use strict";
  const { load, esc, fmt, h, s, seg, bindTip, reducedMotion } = window.UI;
  const $ = id => document.getElementById(id);
  const API = [["AnkiConnect", "var(--api-ac)"], ["AnkiConnect Shim", "var(--api-shim)"], ["Tsunagi API", "var(--api-ts)"]];

  // ---------- Hub figures ----------
  Promise.all([load("summary"), load("roadmap")]).then(([sum, road]) => {
    const m = sum.mine_session, now = road.items.find(i => i.state === "now");
    $("hub-parity").innerHTML = `${sum.parity.implemented} <small>of ${sum.parity.actions} actions</small>`;
    $("hub-tools").innerHTML = `${sum.tools.count} <small>tools · ${fmt.int(sum.tools.requests)} requests checked</small>`;
    $("hub-bench").innerHTML = `${fmt.x(m.AnkiConnect.median_ms / m["Tsunagi API"].median_ms)} <small>faster mining session through the Tsunagi API</small>`;
    $("hub-roadmap").innerHTML = `${esc(sum.version)} <small>released ${fmt.date(sum.released)}${now ? ` · now: ${esc(now.title)}` : ""}</small>`;
  });

  // =====================================================================
  // 1. A mining session, three ways
  // =====================================================================
  const POPUP_START = new Set(["canAddNotesWithErrorDetail", "POST /v1/notes:check"]);
  let session = null;   // set once the benchmark data is in; 2. reads its timings
  load("benchmarks").then(({ runs: [bench] }) => {   // the newest run
    const w = bench.workloads.find(x => x.name === "mine_session");
    const lanes = API.map(([label, color]) => ({ label, color, r: w.results[label] }));
    const when = `Measured ${fmt.date(bench.measured)} with Tsunagi ${esc(bench.tsunagi)}, Anki ${esc(bench.anki)}${bench.ankiconnect ? ` and AnkiConnect (${esc(bench.ankiconnect)})` : ""}, on one computer; the middle of ${w.results.AnkiConnect.trials_ms.length} runs.`;
    if (!lanes.every(l => l.r.log)) {
      // Reports from before per-request timing: totals only.
      $("s-play").disabled = $("s-reset").disabled = true;
      $("s-speed").hidden = true;
      $("s-replay").append(h("div", { class: "replay-empty" },
        "Each request's timing comes with the next measurement. Until then, the whole session's time: ",
        ...lanes.map((l, i) => [i ? ", " : "", h("strong", {}, l.label), ` ${fmt.ms(l.r.median_ms)} (${l.r.requests} requests)`]), "."));
      $("s-explain").textContent = when;
      popupSteps(null);
      return;
    }
    lanes.forEach(l => {
      let popup = 0;
      l.reqs = l.r.log.map(q => ({ ...q, popup: POPUP_START.has(q.what) ? ++popup : popup }));
      l.end = l.reqs[l.reqs.length - 1].end_ms;
    });
    session = lanes;
    replay(lanes, when);
    popupSteps(lanes);
  }).catch(err => { $("s-replay").textContent = `The benchmark data didn't load: ${err.message}`; popupSteps(null); });

  function replay(lanes, when) {
    const W = 1000, left = 150, right = 150, top = 26, laneH = 30, gap = 16;
    const T = Math.max(...lanes.map(l => l.end));
    const x = t => left + (W - left - right) * t / T;
    const H = top + lanes.length * (laneH + gap);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Each API's requests over time" });
    const clip = s("rect", { x: 0, y: 0, width: left, height: H });
    svg.append(s("defs", {}, s("clipPath", { id: "s-clip" }, clip)));
    const axis = s("g", { class: "axis" });
    const step = T > 2000 ? 500 : T > 800 ? 200 : 100;
    for (let t = 0; t <= T; t += step) {
      axis.append(s("line", { x1: x(t), x2: x(t), y1: top - 6, y2: H - gap + 4 }));
      axis.append(s("text", { x: x(t), y: 12, "text-anchor": "middle" }, t === 0 ? "0" : t >= 1000 ? `${t / 1000} s` : `${t} ms`));
    }
    svg.append(axis);
    const counters = lanes.map((l, i) => {
      const y = top + i * (laneH + gap);
      svg.append(s("rect", { class: "lane", x: left, y, width: W - left - right, height: laneH, rx: 5 }));
      svg.append(s("text", { class: "lbl", x: 0, y: y + 13 }, l.label));
      svg.append(s("text", { x: 0, y: y + 28 }, `${l.reqs.length} requests`));
      const g = s("g", { "clip-path": "url(#s-clip)" });
      let lastTick = -Infinity;
      l.reqs.forEach(q => {
        const r = s("rect", { class: "req", x: x(q.start_ms), y: y + 4, width: Math.max(1.2, x(q.end_ms) - x(q.start_ms)), height: laneH - 8, rx: 2, fill: l.color });
        bindTip(r, `<b>${esc(q.what)}</b>${esc(l.label)}, popup ${q.popup}<div class="m">${fmt.ms(q.end_ms - q.start_ms)} · ${fmt.bytes(q.bytes)} answered</div>`);
        g.append(r);
        if (POPUP_START.has(q.what)) {
          g.append(s("line", { class: "tick", x1: x(q.start_ms), x2: x(q.start_ms), y1: y - 4, y2: y }));
          if (x(q.start_ms) - lastTick > 18) { g.append(s("text", { x: x(q.start_ms) + 2, y: y - 4, style: "font-size:10.5px" }, q.popup)); lastTick = x(q.start_ms); }
        }
      });
      svg.append(g);
      const n = s("text", { class: "num", x: W - right + 12, y: y + 13 });
      const sub = s("text", { x: W - right + 12, y: y + 28 });
      svg.append(n, sub);
      return { n, sub };
    });
    const head = s("line", { class: "head", x1: left, x2: left, y1: top - 6, y2: H - gap + 4 });
    svg.append(head);
    $("s-replay").append(svg);

    let t = 0, speed = 1, raf = null, last = 0;
    const [ac, shim, ts] = lanes;
    function draw() {
      clip.setAttribute("width", x(t));
      head.setAttribute("x1", x(t)); head.setAttribute("x2", x(t));
      lanes.forEach((l, i) => {
        const done = l.reqs.filter(q => q.end_ms <= t).length;
        counters[i].n.textContent = t >= l.end ? fmt.ms(l.end) : `${done} of ${l.reqs.length}`;
        counters[i].sub.textContent = t >= l.end ? "done" : t > 0 ? `popup ${l.reqs[Math.max(0, done - 1)].popup} of 10` : "";
      });
      let msg;
      if (t === 0) msg = `Press <strong>Play</strong>. At real time, this takes as long as it did: ${fmt.ms(ac.end)} through AnkiConnect.`;
      else if (t < ts.end) msg = "All three start the first popup together.";
      else if (t < shim.end) msg = `The Tsunagi API finished all ten popups in <strong>${fmt.ms(ts.end)}</strong>. AnkiConnect is on popup ${ac.reqs.filter(q => q.end_ms <= t).slice(-1)[0]?.popup ?? 1}.`;
      else if (t < ac.end) msg = `The shim is done too, in <strong>${fmt.ms(shim.end)}</strong>: the same ${shim.reqs.length} requests as AnkiConnect, from the same tool, answered faster. AnkiConnect is still going.`;
      else msg = `Done. AnkiConnect: ${ac.reqs.length} requests, ${fmt.ms(ac.end)}. Tsunagi's shim answers the same requests ${fmt.x(ac.end / shim.end)} faster, with no change to the tool. ` +
        `The Tsunagi API needs ${ts.reqs.length} requests and is ${fmt.x(ac.end / ts.end)} faster: each popup asks for what it needs in fewer requests (see 2). Hover a block for its request.`;
      $("s-explain").innerHTML = `${msg}<br><span class="muted">${when}</span>`;
    }
    function frame(now) {
      t = Math.min(T, t + (now - last) * speed);
      last = now;
      draw();
      if (t < T) raf = requestAnimationFrame(frame); else stop();
    }
    function stop() { cancelAnimationFrame(raf); raf = null; $("s-play").textContent = t >= T ? "Play again" : "Play"; }
    $("s-play").addEventListener("click", () => {
      if (raf) return stop();
      if (t >= T) t = 0;
      if (reducedMotion()) { t = T; draw(); return stop(); }
      $("s-play").textContent = "Pause";
      last = performance.now();
      raf = requestAnimationFrame(frame);
    });
    $("s-reset").addEventListener("click", () => { stop(); t = 0; draw(); $("s-play").textContent = "Play"; });
    seg($("s-speed"), [[1, "Real time"], [0.1, "10× slower"]], 1, v => { speed = v; });
    draw();
  }

  // =====================================================================
  // 2. One popup, request by request
  // =====================================================================
  const AC = (action, params) => JSON.stringify({ action, version: 6, params });
  const NOTE = w => ({ deckName: "Mining", modelName: "Kiku", fields: { Expression: w }, options: { allowDuplicate: false, duplicateScope: "collection" } });
  const STEPS = [
    {
      goal: "Which of its words are saved?",
      ac: [{ what: "canAddNotesWithErrorDetail", body: AC("canAddNotesWithErrorDetail", { notes: [NOTE("猫"), "… 犬, 鳥 and 空 the same"] }),
             answer: "猫 and 犬: “cannot create note because it is a duplicate”; 鳥 and 空 can be added" }],
      ts: [{ what: "POST /v1/notes:check", body: JSON.stringify([{ deck_name: "Mining", note_type_name: "Kiku", fields: { Expression: "猫" } }, "… 犬, 鳥 and 空 the same"]),
             answer: "states: duplicate, duplicate, normal, normal" }],
      explain: "Both ask one question in one request: could these four notes be added? AnkiConnect answers with an error message for each duplicate, which Yomitan reads; the Tsunagi API answers each with a state.",
    },
    {
      goal: "Which notes hold them?",
      ac: [{ what: "findNotes", body: AC("findNotes", { query: '("expression:猫") or ("expression:犬")' }), answer: "[1001, 1002, 1003]" },
           { what: "multi", body: AC("multi", { actions: [{ action: "findNotes", params: { query: 'nid:1001,1002,1003 ("expression:猫")' } }, "… the same for 犬"] }),
             answer: "[[1001], [1002, 1003]]" }],
      ts: [{ what: "GET /v1/notes", body: 'where=first_field in ["猫","犬"]\nselect=id,first_field',
             answer: "1001 猫, 1002 犬, 1003 犬" }],
      explain: "The popup shows which notes hold each saved word, whatever their note type. Through AnkiConnect that is a search for any of the words, then one search per word inside those results, sent together in a <code>multi</code>. The Tsunagi API reads the notes whose first field is one of the words, with that field, so one answer says which note holds which word.",
    },
    {
      goal: "Add 空 with its audio and picture",
      ac: [{ what: "storeMediaFile", body: AC("storeMediaFile", { filename: "空.mp3", data: "SUQzBAAAAAAA…" }), answer: "\"空.mp3\"" },
           { what: "storeMediaFile", body: AC("storeMediaFile", { filename: "空.jpg", data: "/9j/4AAQSkZJ…" }), answer: "\"空.jpg\"" },
           { what: "addNote", body: AC("addNote", { note: { deckName: "Mining", modelName: "Kiku", fields: { Expression: "空", ExpressionAudio: "[sound:空.mp3]", Picture: "<img src=\"空.jpg\">" } } }),
             answer: "1004" }],
      ts: [{ what: "POST /v1/notes", body: "include=cards\n" + JSON.stringify({ deck_name: "Mining", note_type_name: "Kiku", fields: { Expression: "空" },
             audio: [{ filename: "空.mp3", data: "SUQzBAAAAAAA…", fields: ["ExpressionAudio"] }], picture: [{ filename: "空.jpg", data: "/9j/4AAQSkZJ…", fields: ["Picture"] }] }),
             answer: "created: note 1004, cards [2001]" }],
      explain: "AnkiConnect stores each file first, then adds the note that refers to them: three requests. The Tsunagi API takes the files with the note and puts their references in the fields named, in one request. With <code>include=cards</code> it also answers with the new card's ID.",
    },
    {
      goal: "Suspend its card",
      ac: [{ what: "findCards", body: AC("findCards", { query: "nid:1004" }), answer: "[2001]" },
           { what: "suspend", body: AC("suspend", { cards: [2001] }), answer: "true" }],
      ts: [{ what: "POST /v1/cards:suspend", body: JSON.stringify({ card_ids: [2001] }), answer: "affected: 1" }],
      explain: "To suspend the new card, AnkiConnect has to find it first. The Tsunagi API already answered with its ID, so suspending is the only request.",
    },
  ];

  function popupSteps(lanes) {
    // Timings from the session's second popup (two saved words, as here), when measured.
    const timed = {};
    if (lanes) for (const [key, label] of [["ac", "AnkiConnect"], ["ts", "Tsunagi API"]]) {
      timed[key] = lanes.find(l => l.label === label).reqs.filter(q => q.popup === 2);
    }
    $("p-goals").replaceChildren(...STEPS.map(st => h("li", {}, st.goal)));
    let step = 0;
    const counts = { ac: 0, ts: 0 }, ms = { ac: 0, ts: 0 };
    function card(q, key, index) {
      const t = timed[key]?.[index];
      if (t) ms[key] += t.end_ms - t.start_ms;
      return h("div", { class: "req-card new", style: { "--fc": key === "ac" ? "var(--api-ac)" : "var(--api-ts)" } },
        h("div", { class: "t" }, h("b", {}, q.what), h("span", {}, t ? fmt.ms(t.end_ms - t.start_ms) : "")),
        h("pre", { class: "json" }, q.body),
        h("div", { class: "ans" }, "→ ", q.answer));
    }
    function render() {
      [...$("p-goals").children].forEach((li, i) => li.className = i === step - 1 ? "now" : i < step - 1 ? "done" : "");
      const timing = key => (timed[key] && counts[key] ? `, ${fmt.ms(ms[key])}` : "");
      $("p-count").textContent = step ? `AnkiConnect: ${counts.ac} requests${timing("ac")} · Tsunagi API: ${counts.ts}${timing("ts")}` : "";
      $("p-next").disabled = step === STEPS.length;
      $("p-explain").innerHTML = step === 0
        ? "Press <strong>Next step</strong>. The popup needs four things done; each step shows the requests for one of them."
        : step < STEPS.length ? STEPS[step - 1].explain
        : `${STEPS[step - 1].explain}<br>In all, ${counts.ac} requests through AnkiConnect and ${counts.ts} through the Tsunagi API, for the same result: the benchmark checks both leave the same notes, files and suspended card.`;
    }
    $("p-next").addEventListener("click", () => {
      if (step === STEPS.length) return;
      document.querySelectorAll("#popup .req-card").forEach(c => c.classList.replace("new", "old") || c.classList.add("old"));
      const st = STEPS[step];
      for (const key of ["ac", "ts"]) {
        $(`p-${key}`).append(...st[key].map(q => card(q, key, counts[key]++)));
      }
      step++;
      render();
    });
    $("p-reset").addEventListener("click", () => {
      step = 0; counts.ac = counts.ts = ms.ac = ms.ts = 0;
      $("p-ac").replaceChildren(); $("p-ts").replaceChildren();
      render();
    });
    render();
  }

  // =====================================================================
  // 3. Changes, as they happen
  // =====================================================================
  // Tsunagi's own delays (tsunagi/adapters/change_scan.py): editor saves restart a 2 s wait, other
  // changes made in Anki a 0.5 s one; when the wait runs out, one scan finds what changed.
  const TYPING_DELAY = 2000, OP_DELAY = 500, NOTE_ID = 1790000000123;
  const SELECTS = [
    ["ids", "resources=notes"],
    ["rows", "select=notes:fields,tags"],
    ["front", 'select=notes:fields[name in ["Front"]].value,tags'],
  ];
  const note = { front: $("e-front").value, back: $("e-back").value, tags: [] };
  const sent = [];   // {at, by, note snapshot}
  let mode = "ids", seq = 0, timer = null, deadline = 0, delay = 0, lastCause = null, waitRaf = null;
  const t0 = performance.now();
  const BACKS = ["a dog", "dogs", "dog"];

  function message(ev) {
    const data = { type: "notes.updated", ids: [NOTE_ID], by: ev.by };
    if (ev.app) data.app = ev.app;
    if (mode === "rows") data.notes = [{ id: NOTE_ID, fields: [{ name: "Front", value: ev.note.front, index: 0 }, { name: "Back", value: ev.note.back, index: 1 }], tags: ev.note.tags }];
    if (mode === "front") data.notes = [{ id: NOTE_ID, fields: [ev.note.front], tags: ev.note.tags }];
    data.seq = ev.seq;
    return JSON.stringify(data);
  }
  function renderStream(fresh) {
    $("e-stream").replaceChildren(...(sent.length ? sent.slice().reverse().map((ev, i) => {
      const text = message(ev);
      return h("div", { class: `ev${fresh && i === 0 ? " new" : ""}` },
        h("div", { class: "t" }, h("b", {}, "notes.updated"),
          h("span", {}, `${((ev.at - t0) / 1000).toFixed(1)} s · ${ev.by === "api" ? "sent at once" : `after ${ev.delay / 1000} s of quiet`} · ${new TextEncoder().encode(text).length} bytes`)),
        h("pre", { class: "json" }, text));
    }) : [h("div", { class: "none" }, "Nothing yet. The stream is connected and waiting.")]));
  }
  function explainEvents() {
    const why = {
      null: `Type in Front or Back. Anki's editor saves as you type, so Tsunagi waits until ${TYPING_DELAY / 1000} s pass without a save, then sends one message for the whole burst.`,
      typing: `One message for all that typing, ${TYPING_DELAY / 1000} s after the last save. <code>by: "ui"</code>: it was made in Anki, not by an app.`,
      tag: `Other changes made in Anki go out after ${OP_DELAY / 1000} s of quiet. Anki tells Tsunagi that notes changed, not which, so Tsunagi lets the change settle, then finds the notes that changed.`,
      api: "A write through the API goes out at once: Tsunagi knows exactly what the request changed, and names the app that made it.",
    }[lastCause];
    const how = {
      ids: "The app asked for note changes only, so each message carries the note's ID; the app then reads the note itself.",
      rows: "With <code>select</code>, the note comes with the message, so the app doesn't have to read it.",
      front: "Naming only the field it uses, the app gets just that field's value, and the message stays small.",
    }[mode];
    $("e-explain").innerHTML = `${why} ${how}`;
  }
  function flush() {
    timer = null;
    sent.push({ at: performance.now(), by: "ui", delay, seq: ++seq, note: { ...note, tags: [...note.tags] } });
    renderStream(true);
    explainEvents();
  }
  function mark(cause, ms) {
    lastCause = cause;
    delay = ms;
    clearTimeout(timer);
    timer = setTimeout(flush, ms);
    deadline = performance.now() + ms;
    if (!waitRaf) waitRaf = requestAnimationFrame(drawWait);
    explainEvents();
  }
  function drawWait() {
    const left = deadline - performance.now();
    const bar = $("e-wait").firstElementChild, label = $("e-wait").lastElementChild;
    if (timer && left > 0) {
      bar.style.setProperty("--p", `${100 * (1 - left / delay)}%`);
      label.textContent = `${lastCause === "typing" ? "Anki saved your typing" : "Changed in Anki"}: sending in ${(left / 1000).toFixed(1)} s unless something else changes`;
      waitRaf = requestAnimationFrame(drawWait);
    } else {
      bar.style.setProperty("--p", "0%");
      label.textContent = "";
      waitRaf = null;
    }
  }
  function drawTags() {
    $("e-tags").replaceChildren(...note.tags.map(t => h("span", {}, t)));
    $("e-tag").textContent = note.tags.length ? "Remove the tag “mined” in the Browser" : "Add the tag “mined” in the Browser";
  }
  for (const [id, key] of [["e-front", "front"], ["e-back", "back"]]) {
    $(id).addEventListener("input", e => { note[key] = e.target.value; mark("typing", TYPING_DELAY); });
  }
  $("e-tag").addEventListener("click", () => {
    note.tags = note.tags.length ? [] : ["mined"];
    drawTags();
    mark("tag", OP_DELAY);
  });
  $("e-api").addEventListener("click", () => {
    note.back = BACKS[(BACKS.indexOf(note.back) + 1) % BACKS.length];
    $("e-back").value = note.back;
    lastCause = "api";
    sent.push({ at: performance.now(), by: "api", app: "Your app", seq: ++seq, note: { ...note, tags: [...note.tags] } });
    renderStream(true);
    explainEvents();
  });
  seg($("e-select"), SELECTS, mode, v => { mode = v; renderStream(false); explainEvents(); });
  drawTags();
  renderStream(false);
  explainEvents();

  // =====================================================================
  // 4. Who may do what
  // =====================================================================
  // tsunagi/shared/permissions.py's built-in roles, and who gets which without a key (docs/security.md).
  const ROLES = {
    default: { name: "Default", grants: ["read", "write", "gui", "sync", "manage", "events:changes"] },
    read_only: { name: "Read-only", grants: ["read", "events:changes"] },
    everything: { name: "Everything", grants: ["read", "write", "gui", "sync", "manage", "memory_state", "addon", "local_files", "events"] },
    none: { name: "No access", grants: [] },
  };
  const CALLERS = {
    program: { label: "A program on this computer", keyless: "default", paths: true,
               about: "A program on this computer (a script, a desktop tool) without a key gets the Default role. It already runs as you, so it may name files on this computer by their path." },
    browser: { label: "A browser extension", keyless: "default", paths: false,
               about: "Browser extensions, and pages served from this computer, get the Default role without a key, as in AnkiConnect, so Yomitan works with no setup. They may not name files on this computer by their path: they send the file's contents instead." },
    website: { label: "A website you allowed", keyless: "default", paths: false,
               about: "A website is refused before anything runs unless you allow it. Allowed through the Tsunagi API's access request, it gets its own app, key and role; allowed the AnkiConnect way, it gets the role for keyless requests from this computer." },
    device: { label: "Another device", keyless: "none", paths: false,
              about: "Another device on your network gets No access without a key, unless you change that under Requests without a key. With an app's key, it gets that app's role." },
  };
  const PATHS = new Set(["storeMediaFile", "addNote", "addNotes"]);   // take a file `path`: local_files
  load("parity").then(({ actions }) => {
    let caller = "program", role = "default";
    const groups = [...new Set(actions.map(a => a.group))];
    const cells = new Map();
    $("r-waffle").replaceChildren(...groups.map(g => {
      const mine = actions.filter(a => a.group === g);
      const count = h("span");
      const box = h("div", { class: "wgroup" }, h("h4", {}, `${g}`, count),
        h("div", { class: "wcells" }, mine.map(a => {
          const b = h("button", { type: "button", "aria-label": a.name });
          bindTip(b, () => tipFor(a));
          cells.set(a.name, b);
          return b;
        })));
      box.count = count; box.mine = mine;
      return box;
    }));
    const allows = (grants, p) => p === "public" || grants.includes(p) || grants.includes(p.split(":")[0]);
    function state(a) {
      const grants = ROLES[role].grants;
      if (role === "none") return a.name === "requestPermission" ? "on" : "off";   // even version needs a key then
      if (a.name === "multi") return "on";
      if (!allows(grants, a.permission)) return "off";
      if (PATHS.has(a.name) && !CALLERS[caller].paths && !grants.includes("local_files")) return "half";
      return "on";
    }
    function tipFor(a) {
      const st = state(a);
      const need = a.name === "multi" ? "checks each action it carries" : `needs <code>${esc(a.permission)}</code>`;
      const verdict = st === "on" ? "Allowed" : st === "half" ? "Allowed, but not with a file's path: that needs <code>local_files</code>" : "Refused";
      return `<b>${esc(a.name)}</b>${need}<div class="m">${verdict}</div>`;
    }
    function draw() {
      let on = 0;
      for (const a of actions) {
        const st = state(a);
        cells.get(a.name).className = st === "off" ? "" : st;
        if (st !== "off") on++;
      }
      [...$("r-waffle").children].forEach(box => {
        box.count.textContent = `${box.mine.filter(a => state(a) !== "off").length} of ${box.mine.length}`;
      });
      const c = CALLERS[caller], keyless = c.keyless === role;
      $("r-explain").innerHTML = `${c.about} ${keyless ? "That's the role shown." : `This is the role <strong>${ROLES[role].name}</strong>, given to its key.`} ` +
        `<strong>${ROLES[role].name}</strong> allows ${on} of ${actions.length} actions.` +
        (role === "default" ? " It is everything AnkiConnect allows, except reading files on this computer from a browser or another device." : "") +
        (role === "none" ? " Only <code>requestPermission</code> answers: an app without access can ask for it." : "");
    }
    seg($("r-caller"), Object.entries(CALLERS).map(([k, v]) => [k, v.label]), caller, v => {
      caller = v; role = CALLERS[v].keyless;
      seg($("r-role"), Object.entries(ROLES).map(([k, r]) => [k, r.name]), role, pickRole);
      draw();
    });
    function pickRole(v) { role = v; draw(); }
    seg($("r-role"), Object.entries(ROLES).map(([k, r]) => [k, r.name]), role, pickRole);
    $("r-keys").innerHTML = '<span><i style="background:var(--accent)"></i>Allowed</span>' +
      '<span><i style="background:repeating-linear-gradient(135deg,var(--accent) 0 3px,var(--cell-empty) 3px 6px)"></i>Allowed without a file path</span>' +
      '<span><i style="background:var(--cell-empty)"></i>Refused</span>';
    draw();
  });
})();
