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

  // What the person mining sees, one reader per API: the word looked up, its popup's step, the words mined so far.
  const PASSAGE = [["今朝", "けさ"], "、", ["猫", "ねこ"], "が", ["窓", "まど"], "の", ["外", "そと"], "で", ["鳥", "とり"], "を見ていた。",
    ["犬", "いぬ"], "は", ["庭", "にわ"], "で眠り、", ["空", "そら"], "は青く、", ["風", "かぜ"], "が静かに", ["木", "き"], "を揺らしていた。"];
  // Which of the popup's four steps each request is.
  const PHASE = { canAddNotesWithErrorDetail: 0, "POST /v1/notes:check": 0, findNotes: 1, multi: 1, "GET /v1/notes": 1,
    storeMediaFile: 2, addNote: 2, "POST /v1/notes": 2, findCards: 3, suspend: 3, "POST /v1/cards:suspend": 3 };
  const PHASES = ["Saved?", "Notes", "Add", "Suspend"];
  const CURSOR = '<svg class="cursor" width="14" height="20" viewBox="0 0 14 20" aria-hidden="true"><path d="M1 1v15l4-4 3 7 3-1.3-3-6.7h5.5z" fill="var(--ink)" stroke="var(--surface)" stroke-width="1.2" stroke-linejoin="round"/></svg>';

  function readers(lanes) {
    const views = lanes.map(l => {
      const ends = [];
      l.reqs.forEach(q => { ends[q.popup - 1] = Math.max(ends[q.popup - 1] ?? 0, q.end_ms); });
      const words = [];
      const passage = h("p", { class: "passage", lang: "ja" }, PASSAGE.map(part => {
        if (typeof part === "string") return part;
        const w = h("span", { class: "w" }, part[0]);
        words.push(w);
        return w;
      }));
      const count = h("span", { class: "count" });
      const word = h("div", { class: "rpop-word", lang: "ja" });
      const steps = PHASES.map(name => h("li", {}, name));
      const req = h("code", { class: "rpop-req" });
      const pop = h("div", { class: "rpop", hidden: true }, word, h("ol", { class: "rpop-steps" }, steps), req);
      const cursor = h("span", { class: "rcursor", hidden: true, html: CURSOR });
      const box = h("div", { class: "reader", style: { "--fc": l.color } },
        h("div", { class: "reader-bar" }, h("b", {}, h("i", { class: "api", style: { "--fc": l.color } }), l.label), count),
        h("div", { class: "reader-body" }, passage, pop, cursor));
      return { l, ends, words, count, word, steps, req, pop, cursor, box };
    });
    $("s-readers").replaceChildren(...views.map(v => v.box));
    return t => views.forEach(v => {
      const mined = v.ends.filter(e => e <= t).length;
      v.words.forEach((w, i) => w.className = i < mined ? "w mined" : "w");
      v.count.textContent = t >= v.l.end ? `10 mined in ${fmt.ms(v.l.end)}` : `${mined} of 10 mined`;
      const active = t > 0 && t < v.l.end ? mined : -1;
      v.pop.hidden = v.cursor.hidden = active < 0;
      if (active < 0) return;
      const w = v.words[active];
      w.className = "w now";
      // The request in flight, or the last one answered while the tool works between requests.
      const mine = v.l.reqs.filter(q => q.popup === active + 1);
      const q = mine.filter(r => r.start_ms <= t).at(-1);
      const phase = q ? PHASE[q.what] ?? 0 : -1;
      v.word.innerHTML = `<b>${esc(PASSAGE.filter(x => typeof x !== "string")[active][0])}</b> <span>${esc(PASSAGE.filter(x => typeof x !== "string")[active][1])}</span>`;
      v.steps.forEach((li, i) => li.className = i < phase || (q && t >= q.end_ms && i === phase) ? "done" : i === phase ? "now" : "");
      v.req.textContent = q ? q.what : "looking up";
      // Under the word, kept inside the reader.
      const body = v.pop.parentElement, maxLeft = body.clientWidth - v.pop.offsetWidth - 4;
      v.pop.style.left = `${Math.max(4, Math.min(maxLeft, w.offsetLeft - 8))}px`;
      v.pop.style.top = `${w.offsetTop + w.offsetHeight + 6}px`;
      v.cursor.style.left = `${w.offsetLeft + w.offsetWidth * 0.6}px`;
      v.cursor.style.top = `${w.offsetTop + w.offsetHeight * 0.5}px`;
    });
  }

  function replay(lanes, when) {
    const showReaders = readers(lanes);
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
      showReaders(t);
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

  // The popup itself: its four entries, as each step leaves them.
  const ENTRIES = [
    { word: "猫", reading: "ねこ", gloss: "cat", saved: "note 1001" },
    { word: "犬", reading: "いぬ", gloss: "dog", saved: "notes 1002, 1003" },
    { word: "鳥", reading: "とり", gloss: "bird" },
    { word: "空", reading: "そら", gloss: "sky", mine: true },
  ];
  function popupMock() {
    const rows = ENTRIES.map(e => {
      const state = h("span", { class: "state" });
      const row = h("li", {}, h("span", { class: "term", lang: "ja" }, h("b", {}, e.word), " ", h("small", {}, e.reading)),
        h("span", { class: "gloss" }, e.gloss), state);
      return { e, row, state };
    });
    $("p-mock").replaceChildren(
      h("p", { class: "passage", lang: "ja" }, "…猫と犬が、", h("span", { class: "w now" }, "空"), "を飛ぶ鳥を見ていた…"),
      h("div", { class: "ypop" }, h("div", { class: "ypop-bar" }, "Popup"), h("ul", {}, rows.map(r => r.row))));
    return step => rows.forEach(({ e, row, state }) => {
      let text = "", cls = "state";
      if (step === 0) text = "";
      else if (e.saved) { text = step >= 2 ? `Saved · ${e.saved}` : "Saved"; cls += " saved"; }
      else if (e.mine && step >= 3) { text = step >= 4 ? "Added · suspended" : "Added, with audio and picture"; cls += " added"; }
      else { text = "+ Add"; cls += " add"; }
      state.className = cls;
      state.textContent = text;
      // The entries this step changed.
      row.classList.toggle("hit", step > 0 && (step <= 2 ? Boolean(e.saved) || step === 1 : Boolean(e.mine)));
    });
  }

  function popupSteps(lanes) {
    const showMock = popupMock();
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
      showMock(step);
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
  const changes = [];   // when the note changed in Anki, for the polling comparison
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
    $(id).addEventListener("input", e => { note[key] = e.target.value; changes.push(performance.now()); mark("typing", TYPING_DELAY); });
  }
  $("e-tag").addEventListener("click", () => {
    note.tags = note.tags.length ? [] : ["mined"];
    changes.push(performance.now());
    drawTags();
    mark("tag", OP_DELAY);
  });
  $("e-api").addEventListener("click", () => {
    note.back = BACKS[(BACKS.indexOf(note.back) + 1) % BACKS.length];
    $("e-back").value = note.back;
    lastCause = "api";
    changes.push(performance.now());
    sent.push({ at: performance.now(), by: "api", app: "Your app", seq: ++seq, note: { ...note, tags: [...note.tags] } });
    renderStream(true);
    explainEvents();
  });
  seg($("e-select"), SELECTS, mode, v => { mode = v; renderStream(false); explainEvents(); });
  race();

  // The same changes seen two ways: a tool polling AnkiConnect every 10 s (asbplayer's poll,
  // the change_poll benchmark), and the stream above. The last 40 s, drawn as they pass.
  function race() {
    const POLL = 10000, SPAN = 40000, W = 1000, left = 150, right = 220, laneH = 26, top = 8, gap = 14;
    const H = top + 2 * (laneH + gap);
    const lanes = [["A tool on AnkiConnect", "var(--api-ac)"], ["Tsunagi's stream", "var(--api-ts)"]];
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Polling every 10 seconds compared with the event stream" });
    const marks = s("g"), stats = [];
    lanes.forEach(([label, color], i) => {
      const y = top + i * (laneH + gap);
      svg.append(s("rect", { class: "lane", x: left, y, width: W - left - right, height: laneH, rx: 5 }));
      svg.append(s("text", { class: "lbl", x: 0, y: y + 17 }, label));
      const n = s("text", { class: "num", x: W - right + 12, y: y + 11 }), sub = s("text", { x: W - right + 12, y: y + 25 });
      svg.append(n, sub);
      stats.push({ n, sub });
    });
    svg.append(marks);
    $("e-race").append(h("div", { class: "replay" }, svg));
    const note = h("div", { class: "explain" });
    $("e-race").append(note);

    // Each poll or message, with how long the oldest change it was first to report had waited.
    function reports(times) {
      let prev = -Infinity;
      return times.map(at => {
        const caught = changes.filter(c => c > prev && c <= at);
        prev = at;
        return { at, wait: caught.length ? at - Math.min(...caught) : null };
      });
    }
    const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
    function draw() {
      const now = performance.now(), from = now - SPAN;
      const x = at => left + (W - left - right) * (at - from) / SPAN;
      const polls = [];
      for (let at = t0 + POLL; at <= now; at += POLL) polls.push(at);
      const rows = [reports(polls), reports(sent.map(e => e.at))];
      marks.replaceChildren();
      changes.filter(c => c > from).forEach(c => marks.append(s("line", { class: "change", x1: x(c), x2: x(c), y1: top - 4, y2: H - gap + 4 })));
      rows.forEach((row, i) => {
        const y = top + i * (laneH + gap), color = lanes[i][1];
        row.filter(r => r.at > from - 2000).forEach(r => {
          if (r.wait != null) marks.append(s("rect", { class: "waited", x: Math.max(left, x(r.at - r.wait)), y: y + laneH / 2 - 2, width: Math.max(0, x(r.at) - Math.max(left, x(r.at - r.wait))), height: 4, fill: color }));
          marks.append(s("rect", { class: r.wait != null ? "req" : "req empty", x: x(r.at) - 3, y: y + 4, width: 6, height: laneH - 8, rx: 2, fill: color, style: r.wait != null ? null : `stroke:${color}` }));
        });
        const told = row.filter(r => r.wait != null);
        stats[i].n.textContent = i === 0 ? `${row.length} request${row.length === 1 ? "" : "s"}` : `${row.length} message${row.length === 1 ? "" : "s"}`;
        stats[i].sub.textContent = told.length ? `${told.length} with news, ${(mean(told.map(r => r.wait)) / 1000).toFixed(1)} s after the change` : i === 0 ? "nothing new yet" : "";
      });
      const asked = rows[0].length, empty = rows[0].filter(r => r.wait == null).length;
      note.innerHTML = !changes.length
        ? `The tool on AnkiConnect has asked ${asked} time${asked === 1 ? "" : "s"} since this page opened, and found nothing new: nothing changed. The stream has sent nothing. Change the note above.`
        : `On AnkiConnect, ${asked} requests so far, ${empty} of them for nothing; a change waits up to 10 s to be seen. The stream sent ${rows[1].length} message${rows[1].length === 1 ? "" : "s"}, each once its change was done.`;
    }
    let timer = null;
    new IntersectionObserver(([entry]) => {
      clearInterval(timer);
      timer = entry.isIntersecting ? setInterval(draw, reducedMotion() ? 1000 : 100) : null;
      draw();
    }).observe(svg);
  }
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
  // Permissions no AnkiConnect action needs: Everything grants them, Default doesn't (docs/api_design.md).
  const EXTRAS = [
    ["local_files", "Name files on this computer by path", "From a browser, a website or another device. A program on this computer may anyway: it already runs as you."],
    ["memory_state", "Rewrite FSRS memory state", "Set a card's stability and difficulty directly, as an import from another scheduler would."],
    ["addon", "Run other add-ons' actions", "Actions other add-ons offer through Tsunagi; each one also has to be turned on in Tsunagi's settings."],
    ["events:reviews", "Hear each answer live", "One message on the event stream for every card answered, with its rating and new schedule."],
  ];
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
    const extras = EXTRAS.map(([perm, label, about]) => {
      const pill = h("button", { type: "button", class: "extra" }, label);
      bindTip(pill, () => `<b>${esc(label)}</b>needs <code>${esc(perm)}</code><div class="m">${esc(about)}</div><div class="m">${extraOn(perm) ? "Allowed" : "Refused"}</div>`);
      return [perm, pill];
    });
    $("r-extras").replaceChildren(h("h4", {}, "Only in the Tsunagi API"), h("div", { class: "pills" }, extras.map(([, pill]) => pill)));
    function extraOn(perm) {
      if (role === "none") return false;
      return ROLES[role].grants.some(g => g === perm || g === perm.split(":")[0]) || (perm === "local_files" && CALLERS[caller].paths);
    }
    function draw() {
      let on = 0;
      extras.forEach(([perm, pill]) => pill.classList.toggle("on", extraOn(perm)));
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
        (role === "default" ? " That's everything AnkiConnect allows. Everything allows the same actions, plus what only the Tsunagi API has, below." : "") +
        (role === "everything" ? " The same actions as Default, plus what only the Tsunagi API has, below." : "") +
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
