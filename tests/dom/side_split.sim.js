/* =====================================================================
   Two screens, one at a time -- exercised, not grepped
   =====================================================================

     "i want every tab working smoothly & divide LIVE MARKET TAB into 2
      Gainers & Losers ... today in this clumsy ness i never saw atleast
      one loser stocks. today 71/100 market breadth is positive . still
      i can't check gainers."
                                    -- operator, 3 August 2026

   WHY THIS IS A SIMULATION
   ------------------------
   On 2 August the quantity box was broken in the browser and every
   text-matching test passed on it, because searching source for the
   right words proves the words are there and nothing else. That cost
   an evening and shipped a broken control.

   So this pulls the REAL functions out of index.html and runs them
   against a DOM stub, clicking through both sides.

   A hand-rolled stub rather than jsdom: it needs no install, starts
   instantly, and implements exactly the four things these functions
   touch -- querySelectorAll, style.display, classList and dataset.
   A dependency that takes a minute to boot is a test nobody runs.

   Run:  node tests/dom/side_split.sim.js
   ===================================================================== */

const fs = require("fs");
const path = require("path");

const HTML = fs.readFileSync(
  path.join(__dirname, "..", "..", "dashboard", "static", "index.html"), "utf8");

function grab(name) {
  const start = HTML.indexOf("function " + name + "(");
  if (start < 0) throw new Error("cannot find function " + name);
  // Walk braces from the first { after the signature.
  let i = HTML.indexOf("{", start), depth = 0;
  for (let j = i; j < HTML.length; j++) {
    if (HTML[j] === "{") depth++;
    else if (HTML[j] === "}") { depth--; if (!depth) return HTML.slice(start, j + 1); }
  }
  throw new Error("unbalanced braces in " + name);
}

// ---- the stub -------------------------------------------------------
class Node {
  constructor(tag, attrs = {}, text = "") {
    this.tag = tag;
    this.attrs = attrs;
    // A real DOM STRINGIFIES whatever you assign here. The stub caught
    // itself out on that: renderReversals assigns a number and the
    // first run of this file reported 1 !== "1", which is a bug in the
    // stub and would have been a false alarm about the page.
    this._text = String(text == null ? "" : text);
    Object.defineProperty(this, "textContent", {
      get: () => this._text,
      set: (v) => { this._text = String(v == null ? "" : v); },
    });
    this.innerHTML = "";
    this.style = { display: "" };
    this.children = [];
    this._classes = new Set();
    this.dataset = {};
    for (const [k, v] of Object.entries(attrs)) {
      if (k.startsWith("data-")) this.dataset[k.slice(5).replace(/-(\w)/g,
        (_, c) => c.toUpperCase())] = v;
    }
    this.classList = {
      add: (c) => this._classes.add(c),
      remove: (c) => this._classes.delete(c),
      contains: (c) => this._classes.has(c),
      toggle: (c, on) => on ? this._classes.add(c) : this._classes.delete(c),
    };
  }
  getAttribute(name) { return this.attrs[name] ?? null; }
  setAttribute(name, v) { this.attrs[name] = v; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const out = [];
    const want = parse(sel);
    (function walk(node) {
      for (const kid of node.children) { if (match(kid, want)) out.push(kid); walk(kid); }
    })(this);
    return out;
  }
  append(...kids) { for (const k of kids) this.children.push(k); return this; }
}
function parse(sel) {
  // Only the shapes these functions actually use.
  const parts = sel.trim().split(/\s+/);
  return parts.map((p) => {
    const m = { tag: null, id: null, attr: null, val: null, cls: null };
    let rest = p;
    const a = rest.match(/\[([^\]=]+)(?:="([^"]*)")?\]/);
    if (a) { m.attr = a[1]; m.val = a[2] ?? null; rest = rest.replace(a[0], ""); }
    if (rest.startsWith("#")) m.id = rest.slice(1);
    else if (rest.startsWith(".")) m.cls = rest.slice(1);
    else if (rest) m.tag = rest;
    return m;
  });
}
function match(node, want) {
  const last = want[want.length - 1];
  if (last.id && node.attrs.id !== last.id) return false;
  if (last.tag && node.tag !== last.tag) return false;
  if (last.cls && !(node.attrs.class || "").split(/\s+/).includes(last.cls)) return false;
  if (last.attr) {
    const has = Object.prototype.hasOwnProperty.call(node.attrs, last.attr);
    if (!has) return false;
    if (last.val !== null && node.attrs[last.attr] !== last.val) return false;
  }
  if (want.length > 1) {           // ancestor required, e.g. "#x tbody tr"
    let up = node.parent, ok = false;
    while (up) { if (match(up, want.slice(0, -1))) { ok = true; break; } up = up.parent; }
    if (!ok) return false;
  }
  return true;
}
function el(tag, attrs, text, kids = []) {
  const n = new Node(tag, attrs || {}, text || "");
  for (const k of kids) { k.parent = n; n.children.push(k); }
  return n;
}

// ---- the page, as the browser would have it ------------------------
function row(sym, id) {
  return el("tr", id ? { id } : {}, "", [el("td", {}, sym)]);
}
const gainersPanel = el("div", { class: "panel", "data-otside": "gainers" }, "", [
  el("table", {}, "", [el("tbody", {}, "", [row("UPONE"), row("UPTWO")])])]);
const losersPanel = el("div", { class: "panel", "data-otside": "losers" }, "", [
  el("table", {}, "", [el("tbody", {}, "", [row("DOWNONE")])])]);
const newsPanel = el("div", { class: "panel", "data-otfilter": "1" }, "", [
  el("table", {}, "", [el("tbody", {}, "", [
    row("UPONE", "nUp"), row("DOWNONE", "nDown"), row("MYSTERY", "nUnknown")])])]);
const btnG = el("button", { "data-side": "gainers" }, "GAINERS");
const btnL = el("button", { "data-side": "losers" }, "LOSERS");
const nav = el("nav", { id: "otSideNav" }, "", [btnG, btnL]);
const hint = el("span", { id: "otSideHint" });
const revBody = el("div", { id: "otReversalBody" });
const revBadge = el("span", { id: "otReversalBadge" });
const document = el("html", {}, "", [
  gainersPanel, losersPanel, newsPanel, nav, hint, revBody, revBadge]);
(function link(n) { for (const k of n.children) { k.parent = n; link(k); } })(document);
document.getElementById = (id) => document.querySelector("#" + id);

const store = {};
const sandbox = {
  document,
  localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } },
  escapeHtml: (s) => String(s == null ? "" : s).replace(/&/g, "&amp;")
                       .replace(/</g, "&lt;").replace(/>/g, "&gt;"),
  Set, Number, String, Array, JSON, console,
  OT_SIDE: "gainers",
  OT_SYMS: { gainers: new Set(), losers: new Set() },
};
require("vm").createContext(sandbox);
require("vm").runInContext(
  [grab("otSideOf"), grab("otSetSide"), grab("otApplySide"),
   grab("renderReversals")].join("\n"), sandbox);

sandbox.OT_SYMS.gainers = new Set(["UPONE", "UPTWO"]);
sandbox.OT_SYMS.losers = new Set(["DOWNONE"]);

let bad = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) bad++;
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${label}` +
    (ok ? "" : `\n          got ${JSON.stringify(got)} want ${JSON.stringify(want)}`));
};
const vis = (id) => document.querySelector("#" + id).style.display !== "none";
const panelVis = (side) =>
  document.querySelector(`[data-otside="${side}"]`).style.display !== "none";

console.log("\n--- GAINERS side ---");
sandbox.otSetSide("gainers");
check("gainers table visible", panelVis("gainers"), true);
check("losers table hidden", panelVis("losers"), false);
check("news about a gainer shown", vis("nUp"), true);
check("news about a loser hidden", vis("nDown"), false);
check("news about an UNKNOWN symbol never hidden", vis("nUnknown"), true);

console.log("\n--- LOSERS side (what he could not reach) ---");
sandbox.otSetSide("losers");
check("losers table visible", panelVis("losers"), true);
check("gainers table hidden", panelVis("gainers"), false);
check("news about a loser now shown", vis("nDown"), true);
check("news about a gainer now hidden", vis("nUp"), false);
check("unknown symbol survives both sides", vis("nUnknown"), true);

console.log("\n--- the choice sticks ---");
check("side remembered", store["otside"], "losers");
check("chosen button marked", btnL.classList.contains("ot-side-on"), true);
check("other button not marked", btnG.classList.contains("ot-side-on"), false);

console.log("\n--- reversals follow the side they head towards ---");
const gl = { reversals: {
  up:   [{ symbol: "TURNUP",   change_pct: -1.0, from_pct: -6.2, travelled: 5.2, turn: "UP" }],
  down: [{ symbol: "TURNDOWN", change_pct:  1.5, from_pct:  7.0, travelled: 5.5, turn: "DOWN" }],
} };
sandbox.OT_SIDE = "gainers"; sandbox.renderReversals(gl);
check("gainers side shows the one turning UP", /TURNUP/.test(revBody.innerHTML), true);
check("...and not the one turning down", /TURNDOWN/.test(revBody.innerHTML), false);
sandbox.OT_SIDE = "losers"; sandbox.renderReversals(gl);
check("losers side shows the one turning DOWN", /TURNDOWN/.test(revBody.innerHTML), true);
check("badge counts this side only", revBadge.textContent, "1");
sandbox.renderReversals({});
check("empty says so rather than an empty table",
      /nothing has turned/.test(revBody.innerHTML), true);

console.log(bad ? `\n${bad} FAILURE(S)\n` : "\nALL PASS\n");
process.exit(bad ? 1 : 0);
