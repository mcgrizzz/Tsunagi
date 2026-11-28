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
  const PHASES = ["Exists?", "Notes", "Add", "Suspend"];
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
      goal: "Which entries already exist?",
      ac: [{ what: "canAddNotesWithErrorDetail", body: AC("canAddNotesWithErrorDetail", { notes: [NOTE("食べ物"), "… 食べる and 食 the same"] }),
             answer: "食べ物 can be added; 食べる and 食: “cannot create note because it is a duplicate”" }],
      ts: [{ what: "POST /v1/notes:check", body: JSON.stringify([{ deck_name: "Mining", note_type_name: "Kiku", fields: { Expression: "食べ物" } }, "… 食べる and 食 the same"]),
             answer: "states: normal, duplicate, duplicate" }],
      explain: "Before it can show its buttons, the popup asks whether each of its three entries could be added. Both APIs do it in one request. AnkiConnect answers with an error message for each duplicate, which Yomitan reads; the Tsunagi API answers each with a state.",
    },
    {
      goal: "Which notes hold them?",
      ac: [{ what: "findNotes", body: AC("findNotes", { query: '("expression:食べる") or ("expression:食")' }), answer: "[1001, 1002, 1003]" },
           { what: "multi", body: AC("multi", { actions: [{ action: "findNotes", params: { query: 'nid:1001,1002,1003 ("expression:食べる")' } }, "… the same for 食"] }),
             answer: "[[1001, 1002], [1003]]" }],
      ts: [{ what: "GET /v1/notes", body: 'where=first_field in ["食べる","食"]\nselect=id,first_field',
             answer: "1001 食べる, 1002 食べる, 1003 食" }],
      explain: "Each entry that exists gets a button that opens its notes in Anki, so the popup needs to know which notes hold each of those words, whatever their note type. Through AnkiConnect that is a search for any of the words, then one search per word inside those results, sent together in a <code>multi</code>. The Tsunagi API reads the notes whose first field is one of the words, with that field, so one answer says which note holds which word.",
    },
    {
      goal: "You add 食べ物, with audio and a picture",
      ac: [{ what: "storeMediaFile", body: AC("storeMediaFile", { filename: "食べ物.mp3", data: "SUQzBAAAAAAA…" }), answer: "\"食べ物.mp3\"" },
           { what: "storeMediaFile", body: AC("storeMediaFile", { filename: "食べ物.jpg", data: "/9j/4AAQSkZJ…" }), answer: "\"食べ物.jpg\"" },
           { what: "addNote", body: AC("addNote", { note: { deckName: "Mining", modelName: "Kiku", fields: { Expression: "食べ物", ExpressionAudio: "[sound:食べ物.mp3]", Picture: "<img src=\"食べ物.jpg\">" } } }),
             answer: "1004" }],
      ts: [{ what: "POST /v1/notes", body: "include=cards\n" + JSON.stringify({ deck_name: "Mining", note_type_name: "Kiku", fields: { Expression: "食べ物" },
             audio: [{ filename: "食べ物.mp3", data: "SUQzBAAAAAAA…", fields: ["ExpressionAudio"] }], picture: [{ filename: "食べ物.jpg", data: "/9j/4AAQSkZJ…", fields: ["Picture"] }] }),
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

  // The popup for one lookup: Yomitan's entries for the text under the cursor, as each step leaves them.
  const ENTRIES = [
    { word: "食べ物", reading: "たべもの", gloss: "food", mine: true },
    { word: "食べる", reading: "たべる", gloss: "to eat", notes: 2 },
    { word: "食", reading: "しょく", gloss: "meal; diet", notes: 1 },
  ];
  function popupMock() {
    const rows = ENTRIES.map(e => {
      const button = h("span", { class: "ybtn" });
      const row = h("li", {}, h("div", { class: "term", lang: "ja" }, h("b", {}, e.word), h("small", {}, e.reading)),
        h("span", { class: "gloss" }, e.gloss), button);
      return { e, row, button };
    });
    const pop = h("div", { class: "ypop" }, h("ul", {}, rows.map(r => r.row)));
    $("p-mock").replaceChildren(h("div", { class: "reader-body" },
      h("p", { class: "passage", lang: "ja" }, "昨日の夜、", h("span", { class: "w now" }, "食べ物", h("span", { class: "rcursor", html: CURSOR })), "の話をした。"),
      pop));
    return step => rows.forEach(({ e, row, button }) => {
      const [text, cls] =
        step === 0 ? ["…", "wait"]
        : e.notes ? (step >= 2 ? [`View ${e.notes > 1 ? `${e.notes} notes` : "note"}`, "view"] : ["Exists", "saved"])
        : step >= 4 ? ["Added · suspended", "added"]
        : step >= 3 ? ["Added", "added"]
        : ["＋ Add", "add"];
      button.textContent = text;
      button.className = `ybtn ${cls}`;
      // What this step changed.
      row.classList.toggle("hit", step === 1 || (step === 2 && Boolean(e.notes)) || (step >= 3 && Boolean(e.mine)));
    });
  }

  function popupSteps(lanes) {
    const showMock = popupMock();
    // Timings from the session's second popup (two existing words, as here), when measured.
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
  const TYPING_DELAY = 2000, OP_DELAY = 500;
  const note = { front: $("e-front").value, back: $("e-back").value, tags: [] };
  const sent = [];   // when the stream told the app: {at, by}
  const changes = [];   // when the note changed in Anki
  const states = [{ at: performance.now(), front: note.front, back: note.back, tags: [] }];   // the note after each change, and its cause
  function changed(cause) {
    const at = performance.now();
    changes.push(at);
    states.push({ at, cause, front: note.front, back: note.back, tags: [...note.tags] });
  }
  let timer = null, deadline = 0, delay = 0, lastCause = null, waitRaf = null;
  const t0 = performance.now();
  const BACKS = ["a dog", "dogs", "dog"];

  function explainEvents() {
    const waiting = timer != null;
    $("e-explain").innerHTML = {
      null: "Change the note. Each change shows below, beside what a tool on AnkiConnect would notice.",
      typing: waiting
        ? `Anki's editor saves as you type, so Tsunagi waits until ${TYPING_DELAY / 1000} s pass without a save, then tells the app once for the whole burst.`
        : `The app was told once for all that typing, ${TYPING_DELAY / 1000} s after the last save, and that the change was made in Anki, not by an app.`,
      tag: `${waiting ? "The app will be told" : "The app was told"} after ${OP_DELAY / 1000} s of quiet. Anki tells Tsunagi that notes changed, not which, so Tsunagi lets the change settle, then finds the notes that changed.`,
      api: "Through the API, the note changes at once and the app is told at once: Tsunagi knows exactly what the request changed, and which app made it.",
    }[lastCause];
  }
  function flush() {
    timer = null;
    sent.push({ at: performance.now(), by: "ui" });
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
      label.textContent = `${lastCause === "typing" ? "Anki saved your typing" : "Changed in Anki"}: telling the app in ${(left / 1000).toFixed(1)} s unless something else changes`;
      waitRaf = requestAnimationFrame(drawWait);
    } else {
      bar.style.setProperty("--p", "0%");
      label.textContent = "";
      waitRaf = null;
    }
  }
  // The tags as the Browser shows them: an × on each, a + when there are none. Clicking them is a Browser change.
  function drawTags() {
    $("e-tags").replaceChildren(...(note.tags.length
      ? note.tags.map(tag => h("span", { class: "chip" }, tag, h("button", { type: "button", class: "x", "aria-label": `Remove the tag ${tag}`, onclick: toggleTag }, "×")))
      : [h("button", { type: "button", class: "plus", "aria-label": "Add the tag mined", onclick: toggleTag }, "+")]));
  }
  function toggleTag() {
    note.tags = note.tags.length ? [] : ["mined"];
    changed("tag");
    drawTags();
    flash($("e-tags"));
    mark("tag", OP_DELAY);
  }
  // The Browser's pointer: from the button to what it clicks, then a click.
  function pointAt(target) {
    const cursor = $("e-cursor");
    if (reducedMotion()) return Promise.resolve();
    const box = cursor.parentElement.getBoundingClientRect();
    const place = r => { cursor.style.left = `${r.left - box.left + r.width / 2}px`; cursor.style.top = `${r.top - box.top + r.height / 2}px`; };
    return new Promise(done => {
      cursor.className = "ui-cursor";
      cursor.innerHTML = CURSOR;
      cursor.hidden = false;
      place($("e-ui").getBoundingClientRect());
      void cursor.offsetWidth;
      cursor.classList.add("moving");
      place(target.getBoundingClientRect());
      setTimeout(() => {
        cursor.classList.add("click");
        setTimeout(() => { done(); setTimeout(() => { cursor.hidden = true; }, 450); }, 200);
      }, 600);
    });
  }
  function typeBack() {
    const word = nextBack(), field = $("e-back");
    field.classList.add("typing");
    note.back = field.value = "";
    let n = 0;
    return new Promise(done => {
      const type = setInterval(() => {
        note.back = field.value = word.slice(0, ++n);
        changed("typing");
        mark("typing", TYPING_DELAY);
        if (n === word.length) { clearInterval(type); field.classList.remove("typing"); done(); }
      }, reducedMotion() ? 0 : 140);
    });
  }
  // A field changing before your eyes: typed letter by letter in the Browser, or all at once by the API.
  function flash(el) {
    el.classList.remove("flash");
    void el.offsetWidth;   // restart the animation
    el.classList.add("flash");
  }
  const nextBack = () => BACKS[(BACKS.indexOf(note.back) + 1) % BACKS.length];
  let uiTurn = 0;
  for (const [id, key] of [["e-front", "front"], ["e-back", "back"]]) {
    $(id).addEventListener("input", e => { note[key] = e.target.value; changed("typing"); mark("typing", TYPING_DELAY); });
  }
  // The Browser takes turns: click the tag's × or the +, then type a new Back.
  $("e-ui").addEventListener("click", async () => {
    const buttons = [$("e-ui"), $("e-api")];
    buttons.forEach(b => { b.disabled = true; });
    if (uiTurn++ % 2 === 0) {
      await pointAt($("e-tags").querySelector("button"));
      toggleTag();
    } else {
      await pointAt($("e-back"));
      await typeBack();
    }
    buttons.forEach(b => { b.disabled = false; });
  });
  $("e-api").addEventListener("click", () => {
    note.back = nextBack();
    $("e-back").value = note.back;
    flash($("e-back"));
    lastCause = "api";
    changed("api");
    sent.push({ at: performance.now(), by: "api" });
    explainEvents();
  });
  race();

  // The same changes seen two ways: a tool polling AnkiConnect (every 10 s is asbplayer's poll,
  // the change_poll benchmark), and the stream. The last 40 s, drawn as they pass.
  function race() {
    // Room above the first lane and below the second for what each one saw.
    const SPAN = 40000, W = 1000, left = 150, right = 220, laneH = 26, top = 24, gap = 14;
    const H = top + 2 * laneH + gap + 22;
    const lanes = [["A tool on AnkiConnect", "var(--api-ac)"], ["Tsunagi's stream", "var(--api-ts)"]];
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Polling AnkiConnect compared with the event stream" });
    // Marks scroll out of the lanes on the left; clip them to the lanes.
    svg.append(s("defs", {}, s("clipPath", { id: "e-clip" }, s("rect", { x: left, y: 0, width: W - left - right, height: H }))));
    const marks = s("g", { "clip-path": "url(#e-clip)" }), stats = [];
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

    // The tool's polls so far; changing the rate takes effect from the last poll.
    let every = 10000, next = t0 + every;
    const polls = [];
    seg($("e-rate"), [[2000, "2 s"], [5000, "5 s"], [10000, "10 s, as asbplayer"], [30000, "30 s"]], every, v => {
      every = v;
      next = Math.max(performance.now(), (polls.at(-1) ?? t0) + v);
      draw();
    });

    // Each poll or message: how long the oldest change it was first to report had waited, and
    // what it saw changed since the one before.
    const stateAt = at => states.filter(st => st.at <= at).at(-1);
    function seen(a, b) {
      const parts = [];
      if (a.front !== b.front) parts.push(`Front “${b.front}”`);
      if (a.back !== b.back) parts.push(`Back “${b.back}”`);
      b.tags.filter(tag => !a.tags.includes(tag)).forEach(tag => parts.push(`+${tag}`));
      a.tags.filter(tag => !b.tags.includes(tag)).forEach(tag => parts.push(`−${tag}`));
      return parts.join(", ") || "back as it was";
    }
    function reports(times) {
      let prev = -Infinity;
      return times.map(at => {
        const caught = changes.filter(c => c > prev && c <= at);
        const r = { at, wait: caught.length ? at - Math.min(...caught) : null };
        if (caught.length) {
          r.label = seen(stateAt(prev === -Infinity ? 0 : prev) ?? states[0], stateAt(at));
          // Caught in the middle of typing: typed just before, and typing went on after.
          const after = states.find(st => st.at > at);
          r.partial = stateAt(at).cause === "typing" && after?.cause === "typing" && after.at - at <= TYPING_DELAY;
        }
        prev = at;
        return r;
      });
    }
    const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
    function draw() {
      const now = performance.now(), from = now - SPAN;
      const x = at => left + (W - left - right) * (at - from) / SPAN;
      for (; next <= now; next += every) polls.push(next);
      const rows = [reports(polls), reports(sent.map(e => e.at))];
      marks.replaceChildren();
      changes.filter(c => c > from).forEach(c => marks.append(s("line", { class: "change", x1: x(c), x2: x(c), y1: top - 4, y2: top + 2 * laneH + gap + 4 })));
      rows.forEach((row, i) => {
        const y = top + i * (laneH + gap), color = lanes[i][1];
        row.filter(r => r.at > from - 2000).forEach(r => {
          if (r.wait != null) marks.append(s("rect", { class: "waited", x: Math.max(left, x(r.at - r.wait)), y: y + laneH / 2 - 2, width: Math.max(0, x(r.at) - Math.max(left, x(r.at - r.wait))), height: 4, fill: color }));
          marks.append(s("rect", { class: r.wait != null ? "req" : "req empty", x: x(r.at) - 3, y: y + 4, width: 6, height: laneH - 8, rx: 2, fill: color, style: r.wait != null ? null : `stroke:${color}` }));
        });
        // What each one saw: edits caught half done first, then newest first, leaving out
        // labels that would overlap; kept inside the lane at its ends.
        const placed = [];
        row.filter(r => r.label && r.at > from).reverse()
          .sort((p, q) => Number(i === 0 && q.partial) - Number(i === 0 && p.partial))
          .forEach(r => {
            const partial = i === 0 && r.partial, text = partial ? `${r.label}, mid-edit` : r.label;
            const width = text.length * 6.3 + 6, mx = x(r.at);
            const [start, anchor] = mx + width / 2 > W - right ? [mx - width, "end"] : mx - width / 2 < left ? [mx, "start"] : [mx - width / 2, "middle"];
            if (placed.some(([a, b]) => start < b + 8 && start + width > a - 8)) return;
            placed.push([start, start + width]);
            marks.append(s("text", { class: partial ? "seen partial" : "seen", x: anchor === "end" ? mx + 3 : anchor === "start" ? mx - 3 : mx,
              y: i === 0 ? y - 7 : y + laneH + 15, "text-anchor": anchor }, text));
          });
        const told = row.filter(r => r.wait != null);
        stats[i].n.textContent = i === 0 ? `${row.length} request${row.length === 1 ? "" : "s"}` : `${row.length} message${row.length === 1 ? "" : "s"}`;
        stats[i].sub.textContent = told.length ? `${told.length} with news, ${(mean(told.map(r => r.wait)) / 1000).toFixed(1)} s after the change` : i === 0 ? "nothing new yet" : "";
      });
      const asked = rows[0].length, empty = rows[0].filter(r => r.wait == null).length;
      note.innerHTML = !changes.length
        ? `The tool on AnkiConnect has asked ${asked} time${asked === 1 ? "" : "s"} since this page opened and found nothing new, because nothing changed. The stream has sent nothing. Change the note above.`
        : `On AnkiConnect, ${asked} requests so far, ${empty} of them for nothing; at this rate a change waits up to ${every / 1000} s to be seen. Asking more often sees changes sooner, with more requests` +
          (rows[0].some(r => r.partial) ? ", and catches more edits half done (“mid-edit”): the tool reads the note as it is at that moment." : ".") +
          ` The stream told the app ${rows[1].length} time${rows[1].length === 1 ? "" : "s"}, each once its change was done, and sent nothing in between.`;
    }
    let timer = null;
    new IntersectionObserver(([entry]) => {
      clearInterval(timer);
      timer = entry.isIntersecting ? setInterval(draw, reducedMotion() ? 1000 : 100) : null;
      draw();
    }).observe(svg);
  }
  drawTags();
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
