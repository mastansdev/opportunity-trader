/*
==========================================================
 The size box, driven like a real keyboard
==========================================================

     "while i try to keep some number 55 or 48 its not working, &
      got struck"                    -- operator, 2 August 2026
     "qty box is not working smoothly yes i too observed"
                                     -- operator, 3 August 2026

 Every other test in this project reads the page as TEXT and asserts a
 line is present. That caught nothing here, because the bug was never a
 missing line. Twice now it has been correct code pointed at the wrong
 element.

 So this one runs the real functions -- lifted verbatim out of
 index.html so it cannot drift from what ships -- and types into them,
 with a full panel rebuild after every keystroke, which is what the
 live dashboard does every second.

     node tests/dom/qty_box.sim.js

 NO DEPENDENCIES. 3 August 2026.
 -------------------------------
 This used to need jsdom, and jsdom's install here is incomplete, so
 the script hung on require() and was killed by the timeout -- silently,
 for days, while the bug it guards was live on the operator's screen.
 A safety check that needs an optional package is a safety check that
 does not run. The few DOM pieces these three functions touch are
 written out below instead: about forty lines, no install, works on any
 machine with node.

 Author : H&M Opportunity Trader
==========================================================
*/
const fs = require("fs");
const path = require("path");

// ---------------------------------------------------------------
// The smallest DOM these functions can tell apart from a real one
// ---------------------------------------------------------------
const listeners = {};
const doc = {
  activeElement: null,
  body: null,
  addEventListener(type, fn) {
    (listeners[type] = listeners[type] || []).push(fn);
  },
  querySelectorAll(sel) {
    const want = /^\[data-qtyfor="(.+)"\]$/.exec(sel);
    const out = [];
    (function walk(node) {
      (node.children || []).forEach(function (child) {
        const tag = child.getAttribute("data-qtyfor");
        if (tag !== null && (!want || want[1] === tag)) out.push(child);
        walk(child);
      });
    })(doc.body);
    return out;
  },
  querySelector(sel) { return doc.querySelectorAll(sel)[0] || null; },
};

let FOCUS_OPTS = null;

function makeEl(id) {
  return {
    id: id || "",
    parentElement: null,
    children: [],
    _attrs: {},
    value: "",
    selectionStart: 0,
    getAttribute(name) {
      return name in this._attrs ? this._attrs[name] : null;
    },
    setAttribute(name, val) { this._attrs[name] = String(val); },
    // The browser scrolls a focused element into view unless told not
    // to. With a rebuild every second that is a page that jumps while
    // he types, so the shipped code passes {preventScroll:true} -- and
    // this records the argument so the test can insist on it.
    focus(opts) { doc.activeElement = this; FOCUS_OPTS = opts || null; },
    setSelectionRange(at) { this.selectionStart = at; },
    dispatchEvent(ev) {
      ev.target = this;
      (listeners[ev.type] || []).forEach(function (fn) { fn(ev); });
    },
    append(child) {
      child.parentElement = this;
      this.children.push(child);
      return child;
    },
    // What innerHTML = "..." really does: every old node is destroyed.
    // The browser then moves focus to <body>, which is the detail the
    // 2 August bug was built on top of.
    clear() {
      const self = this;
      (function drop(node) {
        (node.children || []).forEach(drop);
        if (doc.activeElement && node === doc.activeElement) {
          doc.activeElement = doc.body;
        }
      })(self);
      self.children = [];
    },
  };
}

// ---------------------------------------------------------------
// The functions under test, taken out of the shipped page
// ---------------------------------------------------------------
const PAGE = path.join(__dirname, "..", "..", "dashboard", "static",
                       "index.html");
const page = fs.readFileSync(PAGE, "utf8");

const grab = (from, to) => {
  const s = page.indexOf(from);
  if (s < 0) throw new Error(`not found in index.html: ${from}`);
  const e = page.indexOf(to, s);
  if (e < 0) throw new Error(`end marker not found after: ${from}`);
  return page.slice(s, e);
};

const source = [
  "const QTY_BY_SYMBOL = {};",
  "let QTY_FOCUS = null;",
  grab("function qtyScopeOf(el)", 'document.addEventListener("input"'),
  grab('document.addEventListener("input"', "// Enter sends"),
  "module.exports = {QTY_BY_SYMBOL, rememberQtyFocus, restoreQtyBoxes," +
  " qtyScopeOf, focusOf: () => QTY_FOCUS};",
].join("\n");

const shipped = new Function("document", "Array", "module",
                             source + "\nreturn module.exports;")(
  doc, Array, {exports: {}});

// ---------------------------------------------------------------
// The page he actually looks at: one stock, several boxes
// ---------------------------------------------------------------
//
// This is the whole point of the 3 August fix. TITAN can sit in WHAT
// TO TRADE NOW, in the gainers table and in the watchlist at the same
// moment, and every one of those boxes carries data-qtyfor="TITAN".
// The old restore called querySelector() and always got the FIRST one
// in document order -- so typing into the gainers table threw focus up
// to the calls panel a second later.
let ORDER = ["TITAN", "CGPOWER", "SATIN"];

doc.body = makeEl("");
const PANELS = ["otCalls", "glGainers", "watchlist"].map(function (id) {
  return doc.body.append(makeEl(id));
});

function fill() {
  PANELS.forEach(function (panel) {
    panel.clear();
    ORDER.forEach(function (symbol) {
      const row = panel.append(makeEl(""));
      const input = row.append(makeEl(""));
      input.setAttribute("data-qtyfor", symbol);
    });
  });
}

// Exactly what render() does: capture, tear down, restore.
function redraw() {
  shipped.rememberQtyFocus();
  fill();
  shipped.restoreQtyBoxes();
}

function boxIn(panelId, symbol) {
  const panel = PANELS.filter((p) => p.id === panelId)[0];
  let hit = null;
  (function walk(node) {
    node.children.forEach(function (child) {
      if (child.getAttribute("data-qtyfor") === symbol) hit = hit || child;
      walk(child);
    });
  })(panel);
  return hit;
}

function whereIsFocus() {
  const el = doc.activeElement;
  if (!el || !el.getAttribute) return null;
  const symbol = el.getAttribute("data-qtyfor");
  if (!symbol) return null;
  return shipped.qtyScopeOf(el) + "/" + symbol;
}

function type(panelId, symbol, ch) {
  const el = boxIn(panelId, symbol);
  el.focus();
  el.value = el.value + ch;
  el.selectionStart = el.value.length;
  el.dispatchEvent({type: "input"});
}

let failed = 0;
function check(what, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${what}` +
              (ok ? "" : `\n          got ${JSON.stringify(got)}` +
                         ` want ${JSON.stringify(want)}`));
}

fill();

console.log("\ntyping into the GAINERS box for a stock that is also in " +
            "WHAT TO TRADE NOW");
type("glGainers", "TITAN", "5"); redraw();
check("the digit stuck", boxIn("glGainers", "TITAN").value, "5");
check("focus stayed in the gainers table, not the calls panel",
      whereIsFocus(), "glGainers/TITAN");
type("glGainers", "TITAN", "5"); redraw();
check("second digit landed in the same box",
      boxIn("glGainers", "TITAN").value, "55");
check("focus still in the gainers table", whereIsFocus(), "glGainers/TITAN");

console.log("\nthe page does not jump while he types");
check("focus asked the browser not to scroll",
      FOCUS_OPTS && FOCUS_OPTS.preventScroll === true, true);

console.log("\none stock, one number -- every box for TITAN agrees");
check("the calls panel shows the same 55",
      boxIn("otCalls", "TITAN").value, "55");
check("the watchlist shows the same 55",
      boxIn("watchlist", "TITAN").value, "55");

console.log("\nthe table re-sorts under him -- TITAN drops to last");
ORDER = ["SATIN", "CGPOWER", "TITAN"];
redraw();
check("the number followed the STOCK",
      boxIn("glGainers", "TITAN").value, "55");
check("it did not land on the row above",
      boxIn("glGainers", "SATIN").value, "");
check("focus still on the same stock in the same panel",
      whereIsFocus(), "glGainers/TITAN");

console.log("\ntyping 48 into another stock, 30 redraws while typing");
type("watchlist", "SATIN", "4");
for (let i = 0; i < 15; i++) redraw();
type("watchlist", "SATIN", "8");
for (let i = 0; i < 15; i++) redraw();
check("SATIN kept its number", boxIn("watchlist", "SATIN").value, "48");
check("TITAN untouched", boxIn("glGainers", "TITAN").value, "55");
check("focus followed him to the watchlist",
      whereIsFocus(), "watchlist/SATIN");

console.log("\nonly digits reach the API");
type("otCalls", "CGPOWER", "a");
type("otCalls", "CGPOWER", "1");
type("otCalls", "CGPOWER", "2");
redraw();
check("letters stripped as typed", boxIn("otCalls", "CGPOWER").value, "12");

console.log("\nthe panel he was in disappears mid-type");
type("glGainers", "TITAN", "0");
PANELS[1].clear();
shipped.restoreQtyBoxes();
check("it fell back to another box rather than throwing",
      boxIn("otCalls", "TITAN").value, "550");

console.log(failed ? `\n${failed} FAILED\n` : "\nall ok\n");
process.exit(failed ? 1 : 0);
