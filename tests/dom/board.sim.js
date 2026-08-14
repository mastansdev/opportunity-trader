/*
==========================================================
 The board actually re-parents
==========================================================

     "before sending me to verify have u cheked?"
                                    -- operator, 2 August 2026

 tests/test_board_layout.py reads the page as TEXT and proves the code
 is written. It cannot prove the code RUNS -- and the three blank pages
 of 29-30 July were all valid-looking source that threw on load.

 This runs the real layout pass over a real element tree and checks
 where the panels ended up. No dependencies, same reason as
 qty_box.sim.js: jsdom's install here is incomplete and a check that
 needs an optional package is a check that does not run.

 Author : H&M Opportunity Trader
==========================================================
*/
const fs = require("fs");
const path = require("path");

const PAGE = path.join(__dirname, "..", "..", "dashboard", "static",
                       "index.html");
const page = fs.readFileSync(PAGE, "utf8");

let failed = 0;
function check(what, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${what}` +
              (ok ? "" : `\n          got ${JSON.stringify(got)}` +
                         ` want ${JSON.stringify(want)}`));
}

// ---- the smallest element tree the layout pass can tell apart -------
function El(tag, id) {
  return {
    tagName: (tag || "DIV").toUpperCase(), id: id || "",
    children: [], parentElement: null, classList: {
      _s: new Set(),
      add(c) { this._s.add(c); }, contains(c) { return this._s.has(c); },
    },
    dataset: {}, style: {setProperty() {}}, textContent: "", type: "",
    open: false,
    appendChild(c) {
      if (c.parentElement) {
        const kids = c.parentElement.children;
        const at = kids.indexOf(c);
        if (at >= 0) kids.splice(at, 1);
      }
      c.parentElement = this; this.children.push(c); return c;
    },
    insertBefore(c, ref) {
      if (c.parentElement) {
        const kids = c.parentElement.children;
        const at = kids.indexOf(c);
        if (at >= 0) kids.splice(at, 1);
      }
      c.parentElement = this;
      const at = ref ? this.children.indexOf(ref) : 0;
      this.children.splice(at < 0 ? this.children.length : at, 0, c);
      return c;
    },
    insertAdjacentElement(where, c) {
      const parent = this.parentElement;
      if (!parent) return c;
      if (c.parentElement) {
        const kids = c.parentElement.children;
        const at = kids.indexOf(c);
        if (at >= 0) kids.splice(at, 1);
      }
      c.parentElement = parent;
      const at = parent.children.indexOf(this);
      parent.children.splice(where === "afterend" ? at + 1 : at, 0, c);
      return c;
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    addEventListener() {},
    setAttribute() {},
    getBoundingClientRect() { return {height: 56}; },
    scrollIntoView() {},
    get firstChild() { return this.children[0] || null; },
  };
}

const NODES = {};
["otReadLine", "otTopStrip", "tabNav", "otCalls", "otCause", "otBook", "otOrders",
 "otReversal", "otMoving", "statCards", "mktGrid", "tabLive"]
  .forEach((id) => { NODES[id] = El("div", id); });
NODES.tabNav.tagName = "NAV";

const main = El("main");
const header = El("header");
[NODES.otReadLine, NODES.otTopStrip, NODES.otCalls, NODES.otCause, NODES.otBook,
 NODES.otOrders, NODES.tabNav, NODES.tabLive].forEach((n) => main.appendChild(n));

const document = {
  body: El("body"),
  documentElement: {style: {setProperty() {}}},
  getElementById: (id) => NODES[id] || null,
  querySelector: (sel) => (sel === "main" ? main
                         : sel === "header" ? header : null),
  querySelectorAll: () => [],
  createElement: (tag) => El(tag),
  addEventListener() {},
};
const window = {addEventListener() {}, ResizeObserver: null, console};

// ---- the real code, lifted out of the page -------------------------
const start = page.indexOf("THE BOARD, LAID OUT TO ORDER");
if (start < 0) { console.log("\nlayout pass not found in index.html\n"); process.exit(1); }
const from = page.lastIndexOf("/* ====", start);
const to = page.indexOf("  } catch (err) {", start);
const body = page.slice(from, to);

const panelTitled = () => null;
new Function("document", "window", "panelTitled", "console", body)(
  document, window, panelTitled, console);

// ---- where did everything land -------------------------------------
const idsOf = (n) => n.children.map((c) => c.id || c.tagName);
const pinned = NODES.otTopStrip.parentElement;
const board = document.getElementById  // resolve by walking main
  && main.children.filter((c) => c.id === "otBoard")[0];

console.log("\nthe feed line, the tabs AND the chips are pinned together");
check("pinned block holds read line, tiles, tabs, chips",
      idsOf(pinned), ["otReadLine", "otTopStrip", "tabNav", "otChips"]);
check("the pinned block is first in main", main.children[0].id, "otPinned");
check("the chip menu travels with him, it does not scroll away",
      document.getElementById("otChips") ? true
        : pinned.children.some((c) => c.id === "otChips"), true);

console.log("\nthe board follows the pinned block");
check("order under main",
      main.children.slice(0, 3).map((c) => c.id),
      ["otPinned", "otBoard", "otCause"]);

console.log("\nwhat to trade now is the centre, positions directly under it");
const left = board.children[0], right = board.children[1];
check("left column", idsOf(left), ["otCalls", "otBook"]);
check("tradebook is the right column", idsOf(right), ["otOrders"]);

console.log("\nnothing was duplicated");
const seen = {};
(function walk(n) {
  if (n.id) seen[n.id] = (seen[n.id] || 0) + 1;
  n.children.forEach(walk);
})(main);
check("otCalls appears once", seen.otCalls, 1);
check("otOrders appears once", seen.otOrders, 1);
check("otTopStrip appears once", seen.otTopStrip, 1);

console.log(failed ? `\n${failed} FAILED\n` : "\nall ok\n");
process.exit(failed ? 1 : 0);
