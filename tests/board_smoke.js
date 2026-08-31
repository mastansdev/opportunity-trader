/*
==========================================================
board_smoke.js -- actually RUN the page, do not just parse it
==========================================================

    "still UI is worst [qty] is not working ."
    "u made live tab that too errors?"
                                -- operator, 11 August 2026

TWICE IN ONE AFTERNOON I SHIPPED A PAGE THAT COULD NOT RUN
----------------------------------------------------------
  1. `const held` declared twice in one scope. The whole script failed
     to define anything and his board sat on "waiting for the first
     snapshot" with no visible error.
  2. `capOf is not defined` -- I replaced a block of the file and took
     two helper functions out with it. Syntax perfect. Threw the
     instant a row was drawn.

Every test in tests/test_live_tab_is_not_blank.py greps the page as
TEXT. Not one of them can catch either fault, and `node --check` only
proves the file parses -- it says nothing about whether a function the
code calls actually exists.

So this loads the real script into a minimal DOM and calls draw() with
a realistic snapshot. If any identifier is missing, any function was
deleted, or any row throws, this fails loudly. It is the only test in
the project that executes his screen.

Run:  node tests/board_smoke.js
==========================================================
*/

const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(
  path.join(__dirname, "..", "dashboard", "static", "board.html"), "utf8");
const js = (html.match(/<script[^>]*>([\s\S]*?)<\/script>/g) || [])
  .map(b => b.replace(/<script[^>]*>/, "").replace(/<\/script>/, ""))
  .join("\n");

if (!js.trim()){ console.error("FAIL: no script block in board.html"); process.exit(1); }

// ---- the smallest DOM that lets the page run ----
function el(id){
  return {
    id, _html: "", _text: "", style: {}, _on: {}, dataset: {}, _cls: {},
    classList: {
      contains: function(c){ return false; },
      toggle: () => {}, add: () => {}, remove: () => {} },
    addEventListener: function(kind, fn){ (this._on[kind] = this._on[kind] || []).push(fn); },
    click: function(){ (this._on.click || []).forEach(fn => fn.call(this, {target: this})); },
    set innerHTML(v){ this._html = String(v); },
    get innerHTML(){ return this._html; },
    set textContent(v){ this._text = String(v); },
    get textContent(){ return this._text; },
    getAttribute: () => null,
    setAttribute: function(k, v){ this["_attr_" + k] = v; },
    removeAttribute: function(k){ delete this["_attr_" + k]; },
    closest: function(sel){ return sel === "#" + this.id ? this : null; },
    // The switch reaches into its own children to paint them. A stub
    // that cannot do that hides the very fault it exists to catch.
    querySelector: function(sel){
      const key = this.id + sel;
      return (NODES[key] = NODES[key] || el(key));
    },
    querySelectorAll: () => [],
    dispatchEvent: () => {},
    focus: () => {},
    appendChild: () => {},
  };
}
const NODES = {};

// The real controls on the page. If board.html grows a button, add it
// here -- a control this file does not know about is a control nobody
// has ever clicked.
function control(sel, data){
  const e = el(sel);
  e.dataset = data;
  e.getAttribute = (k) => (k === "data-sort" ? data.sort
                        : k === "data-tab" ? data.tab
                        : k === "data-buy" ? data.buy : null);
  return e;
}
function armBtn(id, arm){
  const e = el(id);
  e.getAttribute = (k) => (k === "data-arm" ? arm : null);
  return e;
}
const CONTROLS = [
  armBtn("btn-on",  "on"),
  armBtn("btn-off", "off"),
  control("tab-pre",   {tab: "pre"}),
  control("tab-live",  {tab: "live"}),
  control("tab-post",  {tab: "post"}),
  // 16 August 2026: Watch and Brain were in the markup and were never
  // clicked here. The coverage check below counts controls in the HTML
  // and compares -- it caught the omission the moment Brain landed.
  control("tab-watch", {tab: "watch"}),
  control("tab-brain", {tab: "brain"}),
  control("sort-activity", {sort: "activity"}),
  control("sort-change",   {sort: "change"}),
  control("sort-turnover", {sort: "turnover"}),
];
// The arm/disarm switch is an id, not a data- attribute.
const SWITCH = el("switch");
SWITCH.id = "switch";
const DOCLICK = [];
const document = {
  getElementById: (id) => {
    const found = CONTROLS.find(c => c.id === id);
    if (found) return (NODES[id] = found);
    return (NODES[id] = NODES[id] || el(id));
  },
  querySelector: () => null,
  querySelectorAll: (sel) => {
    if (sel === ".tabs [data-tab]") return CONTROLS.filter(c => c.dataset.tab);
    if (sel === ".sortb" || sel === "[data-sort]")
      return CONTROLS.filter(c => c.dataset.sort);
    if (sel === ".tab") return CONTROLS;
    return [];
  },
  addEventListener: (kind, fn) => { if (kind === "click") DOCLICK.push(fn); },
  activeElement: null,
  body: el("body"),
};
const window = { __OPERATOR_TOKEN__: "",
  matchMedia: () => ({matches: false}) };
global.document = document;
global.window = window;
global.fetch = async () => ({ ok: false, json: async () => ({}) });
global.setInterval = () => 0;
global.setTimeout = (fn) => { return 0; };
global.confirm = () => false;
global.alert = () => {};
global.location = { href: "http://127.0.0.1:8000/board" };

const SNAP = {
  // The real key. dashboard/state.py publishes bot_trading:{on}.
  // The fixture said bot_enabled for a day and hid the fact that
  // the page was reading a key nobody publishes.
  bot_trading: {on: false, known: true},
  universe_size: 1315,
  as_of: "15:52",
  open_positions: [{ symbol: "KOLTEPATIL", qty: 60 }],
  gainers_losers: {
    gainers: [
      { symbol: "LUMAXTECH", ltp: 2065, open: 1795, high: 2085.8, low: 1795,
        prev_close: 1738.2, volume: 4485000, change_pct: 18.8 },
      { symbol: "KOLTEPATIL", ltp: 549.5, open: 490.2, high: 554.6, low: 490.2,
        prev_close: 462.2, volume: 9059000, change_pct: 18.89 },
      { symbol: "TINY", ltp: 10.4, open: 10.0, high: 10.5, low: 9.9,
        prev_close: 10.0, volume: 900, change_pct: 4.0 },
    ],
    losers: [
      { symbol: "HLEGLAS", ltp: 379.6, open: 379.6, high: 385, low: 375,
        prev_close: 474.5, volume: 489047, change_pct: -20.0 },
    ],
  },
  ranked: {
    available: true,
    graded: { KOLTEPATIL: "EXCELLENT", LUMAXTECH: "GOOD" },
    reasons: { LUMAXTECH: "reported results yesterday -- Outcome of Board Meeting" },
    rows: [
      { symbol: "KOLTEPATIL", ltp: 549.5, open: 490.2, high: 554.6, low: 490.2,
        prev_close: 462.2, volume: 9059000, change_pct: 18.89, grade: "EXCELLENT",
        mechanism: "EXCELLENT result", volume_x: 4.2, sector: "REAL ESTATE",
        excess_pct: 16.1, headroom_pct: 1.0 },
    ],
    refused_rows: [
      { symbol: "TINY", ltp: 10.4, open: 10.0, high: 10.5, low: 9.9,
        prev_close: 10.0, volume: 900, change_pct: 4.0, display_only: true,
        blocking: ["too thin to trade our size"] },
    ],
  },
  closed_positions: [],
};

let failed = false;
function check(name, fn){
  try { fn(); console.log("  ok    " + name); }
  catch (e){ failed = true; console.error("  FAIL  " + name + "\n        " + e.message); }
}

console.log("\n  board.html -- executed, not just parsed");
console.log("  " + "=".repeat(56));

// dashboard/server.py replaces this exact line before serving. The
// test has to do the same or it is testing a page nobody is served.
const PLACEHOLDER = 'window.__OPERATOR_TOKEN__ = "";';
function load(token){
  if (!js.includes(PLACEHOLDER))
    throw new Error("the token placeholder server.py rewrites is gone");
  const src = js.replace(PLACEHOLDER,
    'window.__OPERATOR_TOKEN__ = ' + JSON.stringify(token) + ';');
  const fn = new Function("document", "window", "fetch", "setInterval",
                          "setTimeout", "confirm", "location",
                          src + "\nreturn {draw: draw};");
  return fn(document, window, global.fetch, global.setInterval,
            global.setTimeout, global.confirm, global.location);
}

let page;
try { page = load(""); }
catch (e){
  console.error("  FAIL  the script could not even load: " + e.message);
  process.exit(1);
}
const draw = page.draw;

check("draw() runs without throwing", () => {
  draw(SNAP);
});

check("rows actually reached the table", () => {
  const body = NODES["body"]._html;
  if (!body || /waiting for the first snapshot/.test(body))
    throw new Error("body still empty after draw()");
  if (!/LUMAXTECH/.test(body)) throw new Error("the top gainer is not on the table");
});

check("the held position is drawn", () => {
  if (!/KOLTEPATIL/.test(NODES["body"]._html))
    throw new Error("a held stock vanished from the board");
});

check("the faller was filtered out", () => {
  if (/HLEGLAS/.test(NODES["body"]._html))
    throw new Error("a -20% stock reached a long-only table");
});

check("reason chips rendered", () => {
  if (!/class="chip rc"/.test(NODES["body"]._html))
    throw new Error("no reason chips in the row");
});

check("BUY is absent on a view-only link", () => {
  if (/data-buy=/.test(NODES["body"]._html))
    throw new Error("BUY drawn without an operator token");
});

check("BUY appears for the operator", () => {
  load("a-real-token").draw(SNAP);
  const body = NODES["body"]._html;
  if (!/data-buy=/.test(body)) throw new Error("no BUY button for the operator");
  if (!/data-qtyfor=/.test(body)) throw new Error("no qty box for the operator");
});

check("qty and BUY sit inside the symbol cell", () => {
  const body = NODES["body"]._html;
  const cell = body.slice(body.indexOf('class="sym"'), body.indexOf("</td>"));
  if (!/data-buy=/.test(cell))
    throw new Error("BUY is not in the stock cell");
});

// ---------------------------------------------------------------
// 11 August: "activity change% Turonver are tabs ? i clicked on them
//             = empty page ."
// The sort buttons carried class="tab" to borrow the styling, and the
// tab handler was bound to every .tab. Clicking Activity ran the pane
// switcher with dataset.tab undefined, so all three panes went to
// display:none. A blank page from a button meant only to reorder rows.
//
// The smoke test above never CLICKED anything. That was the hole.
// ---------------------------------------------------------------

// Every pane the switcher knows about. Kept in step with the
// [data-tab] buttons above -- if this list is short, clicking a tab it
// does not know about looks like "blanked every pane" when the page is
// working perfectly. That is exactly what happened when Watch and
// Brain were added: 16 August 2026.
const PANES = ["pre", "live", "post", "watch", "brain"];

function paneState(){
  return PANES.map(n => NODES[n + "-pane"]
    ? NODES[n + "-pane"].style.display : "?");
}

check("a sort button never hides the panes", () => {
  draw(SNAP);
  for (const b of CONTROLS.filter(c => c.dataset.sort)){
    b.click();
    DOCLICK.forEach(fn => fn({target: b}));
    const panes = paneState();
    if (panes.every(d => d === "none"))
      throw new Error(b.dataset.sort + " blanked every pane");
  }
});

check("each tab still shows exactly one pane", () => {
  for (const b of CONTROLS.filter(c => c.dataset.tab)){
    b.click();
    const shown = paneState().filter(d => d !== "none").length;
    if (shown !== 1)
      throw new Error("tab " + b.dataset.tab + " showed " + shown + " panes");
  }
});

check("every control on the page is exercised", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "dashboard",
    "static", "board.html"), "utf8");
  // ---- COUNT THE MARKUP, NOT THE SCRIPT. 16 August 2026. ----
  // This read the whole file, so
  //     document.querySelector('[data-tab="brain"]')
  // -- a SELECTOR, not a control -- counted as a ninth button and the
  // check failed with nothing wrong. Controls live above <script>.
  const markup = html.split("<script")[0];
  const found = (markup.match(/data-(tab|sort)="[a-z%]+"/g) || []).length;
  if (found > CONTROLS.length)
    throw new Error("board.html has " + found + " controls, this test clicks "
      + CONTROLS.length + " -- add the new one here");
});

// ---------------------------------------------------------------
// "where is the on/off button to switch trading . ON = Bot trading /
//  OFF = Bot Observing. no trades by bot"   -- 11 August 2026
// The chip was a LABEL. /api/bot_trading has existed since 5 August;
// this page never called it, so /board could not arm the bot at all.
// ---------------------------------------------------------------

check("both commands post to the real endpoint, after a confirm", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "dashboard",
    "static", "board.html"), "utf8");
  if (!/\/api\/bot_trading\/\$\{arm\}/.test(html))
    throw new Error("does not call /api/bot_trading");
  if (!/confirm\(ask\)/.test(html))
    throw new Error("arms or disarms without confirming");
  if (!/bot_trading\/on\?force=1/.test(html))
    throw new Error("no override when the morning is not ready");
});

check("there are TWO buttons, ON and OFF", () => {
  // "if i click ON = bot trading & if i click OFF = Bot Observing."
  // A toggle has to infer which command to send. Two buttons cannot.
  const html = fs.readFileSync(path.join(__dirname, "..", "dashboard",
    "static", "board.html"), "utf8");
  if (!/data-arm="on"/.test(html))  throw new Error("no ON button");
  if (!/data-arm="off"/.test(html)) throw new Error("no OFF button");
});

check("the command comes from the button, never from a variable", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "dashboard",
    "static", "board.html"), "utf8");
  if (/const want = BOT_ON/.test(html))
    throw new Error("the command is still inferred from state");
  if (!/getAttribute\("data-arm"\)/.test(html))
    throw new Error("the handler does not read the command off the button");
  if (!/\/api\/bot_trading\/\$\{arm\}/.test(html))
    throw new Error("the button's own command is not what gets sent");
});

check("ON lights GREEN, OFF lights YELLOW, and there is only ONE label", () => {
  // "show ON = BOT TRADING (FILL GREEN LIGHT IN ON) & OFF = BOT
  //  OBSERVING (FILL YELLOW LIGHT IN OFF)"    -- 11 August
  //
  // ---- ONE LABEL, NOT TWO. 31 August 2026. ----
  //
  //   "on dashboard just show as this by default OFF PAPER TRADE .
  //    after i click ON then REAL TRADE . thats it no explanation or
  //    nothing required"
  //
  // There were two labels for one fact -- switchlabel said BOT
  // TRADING / BOT OBSERVING and the chip beside it said PAPER / REAL
  // MONEY. Two labels for one fact is how they end up disagreeing,
  // which is what happened on 21 August. switchlabel is empty now and
  // the mode chip carries the whole answer. The COLOURS stay: they
  // are the same information, not an explanation.
  const html = fs.readFileSync(path.join(__dirname, "..", "dashboard",
    "static", "board.html"), "utf8");
  if (!/\.segb\.live-on \{background:#e1f5ee/.test(html))
    throw new Error("ON is not filled green");
  if (!/\.segb\.live-off\{background:#faeeda/.test(html))
    throw new Error("OFF is not filled yellow");

  draw(Object.assign({}, SNAP, {bot_trading: {on: true, known: true}}));
  if (NODES["switchlabel"]._text !== "")
    throw new Error("a second label is back: '"
                    + NODES["switchlabel"]._text + "'");
});

check("the board says whose money this is", () => {
  // "now bot is in paper mode or real trading with dhan? & still why
  //  can't i get the difference while ttrading"   -- operator, 24 Aug
  //
  // The page never showed the mode at all. PAPER appeared only in
  // comments and a tooltip, while the console announced "Orders
  // placed from here are REAL" during a PAPER session.
  // 31 August: two words, his words. And driven by
  // placing_real_orders -- the truth about where an order would go --
  // never by the position of the button.
  draw(Object.assign({}, SNAP, {
    mode: "PAPER",
    bot_trading: {on: true, known: true, placing_real_orders: false}}));
  if (NODES["mode"]._text !== "PAPER TRADE")
    throw new Error("PAPER session shows '" + NODES["mode"]._text + "'");

  draw(Object.assign({}, SNAP, {
    mode: "LIVE",
    bot_trading: {on: true, known: true, placing_real_orders: true}}));
  if (NODES["mode"]._text !== "REAL TRADE")
    throw new Error("LIVE session shows '" + NODES["mode"]._text + "'");

  // Silence is the one answer it must never give. An unknown mode
  // reads as real money, not as nothing.
  draw(Object.assign({}, SNAP, {bot_trading: {on: false, known: true}}));
  if (NODES["mode"]._text !== "MODE UNKNOWN")
    throw new Error("unknown mode shows '" + NODES["mode"]._text + "'");
});

check("the lit button and the words can never disagree", () => {
  // They were set in two different places, which is how BOT TRADING
  // ended up beside a bot that was observing.
  const html = fs.readFileSync(path.join(__dirname, "..", "dashboard",
    "static", "board.html"), "utf8");
  const fn = html.split("function paintState(on)")[1];
  if (!fn) throw new Error("there is no single place that paints the state");
  const body = fn.slice(0, fn.indexOf("\n}"));
  // The words moved to paintMode() on 31 August; the LIGHTS still
  // belong here, and one place must own each.
  for (const part of ["live-on", "live-off"])
    if (!body.includes(part))
      throw new Error(part + " is painted somewhere else");
  if (!body.includes('lab.textContent = ""'))
    throw new Error("paintState is writing words again -- there must be "
                    + "exactly one label, and paintMode owns it");
});

check("the screen answers the click immediately", () => {
  // A control that waits three seconds to admit it heard you is a
  // control you press twice -- which is how four OFF requests happened.
  const html = fs.readFileSync(path.join(__dirname, "..", "dashboard",
    "static", "board.html"), "utf8");
  if (!/paintState\(arm === "on"\);/.test(html))
    throw new Error("the label waits for the next poll before it changes");
});

check("the live state only decides which button is lit", () => {
  draw(Object.assign({}, SNAP, {bot_trading: {on: true, known: true}}));
  const onLit  = NODES["btn-on"].className;
  const offLit = NODES["btn-off"].className;
  if (!/live-on/.test(onLit) || /live/.test(offLit))
    throw new Error("ON not lit when the bot is on: " + onLit + " / " + offLit);
  draw(Object.assign({}, SNAP, {bot_trading: {on: false, known: true}}));
  if (!/live-off/.test(NODES["btn-off"].className))
    throw new Error("OFF not lit when the bot is off");
  if (/live/.test(NODES["btn-on"].className))
    throw new Error("ON still lit when the bot is off");
});

check("one click cannot fire two requests", () => {
  // Four identical "Bot trading OFF" lines in his terminal. A control
  // that fires more than once on a live account is not a control.
  const html = fs.readFileSync(path.join(__dirname, "..", "dashboard",
    "static", "board.html"), "utf8");
  if (!/if \(sw_busy\) return;/.test(html))
    throw new Error("the switch has no in-flight guard");
  if (!/finally \{ sw_busy = false; \}/.test(html))
    throw new Error("the guard is never released -- the switch would jam");
});

check("draw() survives an empty snapshot", () => {
  draw({});
});

check("draw() survives a snapshot with no gainers", () => {
  draw({ universe_size: 10, ranked: { rows: [], refused_rows: [] } });
});

console.log("");
process.exit(failed ? 1 : 0);
