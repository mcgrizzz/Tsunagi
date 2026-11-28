// Shared by every page: the theme, data loading, formatting, building elements and the hover tooltip.
(() => {
  "use strict";
  const root = document.documentElement;

  function store(key, value) {
    try { return value === undefined ? localStorage.getItem(key) : localStorage.setItem(key, value); }
    catch { return null; }
  }
  const saved = store("tsunagi-theme");
  if (saved) root.dataset.theme = saved;

  const themeListeners = [];
  document.getElementById("theme")?.addEventListener("click", () => {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    const next = (root.dataset.theme || (dark ? "dark" : "light")) === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    store("tsunagi-theme", next);
    themeListeners.forEach(f => f());
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => themeListeners.forEach(f => f()));

  async function load(name) {
    const response = await fetch(`data/${name}.json`, { cache: "no-cache" });
    if (!response.ok) throw new Error(`data/${name}.json: ${response.status}`);
    return response.json();
  }

  const esc = text => String(text).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  // The docs' and release notes' inline Markdown: code, bold, italics and links.
  const prose = text => esc(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2">$1</a>');
  const fmt = {
    int: n => Math.round(n).toLocaleString("en-US"),
    ms: n => n >= 100 ? `${Math.round(n).toLocaleString("en-US")} ms` : `${n.toFixed(1)} ms`,
    x: n => `${n >= 10 ? Math.round(n) : n.toFixed(1)}×`,
    bytes: n => n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${Math.round(n / 1e3)} kB` : `${n} B`,
    date: iso => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }),
  };
  const css = name => getComputedStyle(root).getPropertyValue(name).trim();

  // h("div", {class: "x", style: {"--fc": "red"}}, child, ...) and s(...) for SVG.
  function build(el, attrs, kids) {
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "style" && typeof v === "object") Object.entries(v).forEach(([p, val]) => el.style.setProperty(p, val));
      else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    kids.flat().forEach(c => c != null && c !== false && el.append(c));
    return el;
  }
  const h = (tag, attrs, ...kids) => build(document.createElement(tag), attrs, kids);
  const s = (tag, attrs, ...kids) => build(document.createElementNS("http://www.w3.org/2000/svg", tag), attrs, kids);

  // A segmented control: options [[value, label]], calls pick(value).
  function seg(el, options, value, pick) {
    el.replaceChildren(...options.map(([v, label]) => h("button", {
      type: "button", "aria-pressed": String(v === value),
      onclick: ev => { [...el.children].forEach(b => b.setAttribute("aria-pressed", String(b === ev.currentTarget))); pick(v); },
    }, label)));
  }

  const tip = h("div", { class: "tip", role: "tooltip" });
  document.body.append(tip);
  function place(x, y) {
    const pad = 14, w = tip.offsetWidth, ht = tip.offsetHeight;
    tip.style.left = `${Math.max(8, x + pad + w > innerWidth - 8 ? x - w - pad : x + pad)}px`;
    tip.style.top = `${Math.max(8, y + pad + ht > innerHeight - 8 ? y - ht - pad : y + pad)}px`;
  }
  function showTip(html, ev) { tip.innerHTML = html; tip.classList.add("on"); place(ev.clientX, ev.clientY); }
  function hideTip() { tip.classList.remove("on"); }
  // Hover, or keyboard focus, shows html (a string or a function returning one).
  function bindTip(el, html) {
    const text = () => (typeof html === "function" ? html() : html);
    el.addEventListener("pointerenter", ev => showTip(text(), ev));
    el.addEventListener("pointermove", ev => place(ev.clientX, ev.clientY));
    el.addEventListener("pointerleave", hideTip);
    el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); showTip(text(), { clientX: r.right, clientY: r.bottom }); });
    el.addEventListener("blur", hideTip);
  }

  const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  window.UI = { load, esc, prose, fmt, css, h, s, seg, bindTip, showTip, hideTip, reducedMotion,
                onTheme: f => themeListeners.push(f) };
})();
