"use strict";
/* Editor: Layout, Modul-Einstellungen, Deck, globale Settings.
 *
 * Zeichnet Topbar und Spalten des aktiven Profils als beschriftete Kaesten in
 * echter Proportion, laesst sie verschieben und skalieren, baut aus dem
 * Schema jedes Moduls ein Formular und schickt Layout, Settings und Apps
 * per postMessage an Python zurueck.
 *
 * Bewusst kein Framework und kein Build-Schritt: die Seite wird von
 * editor/__init__.py in eine Datei eingebettet und muss nur hier laufen.
 */

const P = window.__PAYLOAD__ || {};
const FLEX = P.flex || "flex";
const STAGE = P.stage || { width: 2560, height: 720, connector: "" };
const CATALOGUE = P.catalogue || [];
const TOPBAR_CATALOGUE = P.topbar_catalogue || [];
const SLOTS = P.topbar_slots || ["left", "center", "right"];
const DECK = P.deck || { cols: 3, rows: 6, slots: 18 };
const SETTINGS_SCHEMA = P.settings_schema || [];

/* Arbeitskopien. Das Original bleibt fuer "Verwerfen" liegen und wird nach
 * jedem erfolgreichen Speichern nachgezogen. */
let ORIGINAL = JSON.stringify({ layout: P.layout || {}, settings: P.settings || {}, apps: P.apps || {} });
let layout, settings, apps;
let selected = null;   // {kind:"module",col,mod} | {kind:"column",col}
                       // | {kind:"topbar",slot,index} | {kind:"settings"}
let deckSlot = 0;      // im Deck-Editor ausgewaehlter Platz
let dirty = false;

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const clone = (v) => JSON.parse(JSON.stringify(v));

function loadWorking() {
  const o = JSON.parse(ORIGINAL);
  layout = o.layout; settings = o.settings; apps = o.apps;
  apps.apps = apps.apps || []; apps.macros = apps.macros || [];
}

/* ---------- Palette ---------- */

function applyPalette() {
  const p = P.palette || {};
  const root = document.documentElement.style;
  const map = {
    bg: "--bg", panel: "--panel", raised: "--raised", line: "--line",
    text: "--text", muted: "--muted", label: "--label",
    accent: "--accent", warm: "--warm", hot: "--hot", on_accent: "--on-accent",
  };
  for (const [key, name] of Object.entries(map)) {
    if (p[key]) root.setProperty(name, p[key]);
  }
}

/* ---------- Zugriff auf das aktive Profil ---------- */

const profile = () => layout.profiles[layout.active_profile];
const columns = () => profile().columns;
function topbar() {
  const prof = profile();
  if (!prof.topbar || !SLOTS.every((s) => Array.isArray(prof.topbar[s]))) {
    prof.topbar = Object.fromEntries(SLOTS.map((s) => [s, (prof.topbar && prof.topbar[s]) || []]));
  }
  return prof.topbar;
}

const specFor = (type) => CATALOGUE.find((c) => c.type === type) || null;
const topbarSpecFor = (type) => TOPBAR_CATALOGUE.find((c) => c.type === type) || null;
const labelFor = (type) => { const s = specFor(type); return s ? s.label : type; };
const topbarLabelFor = (type) => { const s = topbarSpecFor(type); return s ? s.label : type; };

function markDirty() {
  dirty = true;
  setStatus("", "");
  $("save").disabled = false;
  $("revert").disabled = false;
}

function setStatus(text, kind) {
  const s = $("status");
  s.textContent = text;
  s.className = "status" + (kind ? " " + kind : "");
}

/* ---------- Breiten ---------- */

function fixedTotal() {
  return columns().reduce((sum, c) => sum + (c.width === FLEX ? 0 : c.width), 0);
}
const flexWidth = () => Math.max(0, STAGE.width - fixedTotal());
const renderedWidth = (col) => (col.width === FLEX ? flexWidth() : col.width);

/* ---------- Zeichnen ---------- */

function render() {
  renderStageMeta();
  renderStage();
  renderProfiles();
  renderInspector();
}

function renderStageMeta() {
  const conn = STAGE.connector ? STAGE.connector + " — " : "";
  $("stage-label").textContent = `${conn}${STAGE.width}×${STAGE.height}`;
  const warn = $("stage-warning");
  const left = flexWidth();
  if (left <= 0) {
    warn.hidden = false;
    warn.textContent = `Fixed columns take ${fixedTotal()} px of ${STAGE.width} px — ` +
                       `nothing is left for the flex column.`;
  } else if (left < 120) {
    warn.hidden = false;
    warn.textContent = `Only ${left} px left for the flex column.`;
  } else {
    warn.hidden = true;
  }
}

function renderStage() {
  $("stage").style.aspectRatio = `${STAGE.width} / ${STAGE.height}`;
  renderTopbar();
  renderColumns();
}

/* ---- Topbar ---- */

function renderTopbar() {
  const tb = $("topbar");
  tb.innerHTML = "";
  const data = topbar();
  for (const slot of SLOTS) {
    const node = el("div", "tb-slot " + slot);
    node.dataset.slot = slot;
    data[slot].forEach((w, i) => node.appendChild(makeChip(w, slot, i)));
    if (slot === "right") {
      // Zahnrad, FS, X sind nicht Teil des Layouts — das Zahnrad ist der Weg
      // hierher, ohne es kaeme man nicht mehr in den Editor.
      node.appendChild(el("div", "chip fixed", "⚙ FS X"));
    }
    tb.appendChild(node);
  }
}

function makeChip(w, slot, i) {
  const node = el("div", "chip", topbarLabelFor(w.type).toUpperCase());
  node.dataset.slot = slot;
  node.dataset.index = String(i);
  if (selected && selected.kind === "topbar" && selected.slot === slot && selected.index === i) {
    node.classList.add("selected");
  }
  const x = el("button", "module-x", "×");
  x.title = "Remove widget";
  x.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  x.addEventListener("click", (ev) => { ev.stopPropagation(); removeTopbar(slot, i); });
  node.appendChild(x);
  node.addEventListener("pointerdown", (ev) => startChipDrag(ev, slot, i));
  return node;
}

function removeTopbar(slot, i) {
  topbar()[slot].splice(i, 1);
  selected = null;
  markDirty();
  render();
}

/* ---- Spalten ---- */

function renderColumns() {
  const host = $("columns");
  host.innerHTML = "";
  const cols = columns();
  /* Proportionale Spuren: 460fr 1250fr … — das Grid zieht die Luecken ab,
   * bevor es verteilt, deshalb passt die Summe immer in den Rahmen. */
  host.style.gridTemplateColumns = cols.map((c) => `${renderedWidth(c)}fr`).join(" ");
  cols.forEach((col, ci) => host.appendChild(makeColumn(col, ci)));
  placeGrips(host);
}

/* Greifkanten als Overlay auf die gemessene rechte Kante jeder Spalte legen.
 * Die Spalten stehen zu diesem Zeitpunkt schon im Dokument, die Rechtecke
 * sind also echt — kein Nachrechnen von Prozenten und Luecken. */
function placeGrips(host) {
  host.querySelectorAll(".grip").forEach((g) => g.remove());
  const hostRect = host.getBoundingClientRect();
  const gap = parseFloat(getComputedStyle(host).columnGap) || 0;
  const colNodes = [...host.querySelectorAll(".column")];
  colNodes.slice(0, -1).forEach((node, i) => {
    const r = node.getBoundingClientRect();
    const grip = el("div", "grip");
    grip.addEventListener("pointerdown", (ev) => startResize(ev, i));
    grip.style.left = `${r.right - hostRect.left + gap / 2}px`;
    host.appendChild(grip);
  });
}

function makeColumn(col, ci) {
  const node = el("div", "column");
  node.dataset.col = String(ci);

  const head = el("div", "column-head");
  const width = el("button", "column-width" + (col.width === FLEX ? " is-flex" : ""));
  width.textContent = col.width === FLEX ? `flex · ${flexWidth()} px` : `${col.width} px`;
  width.title = col.width === FLEX
    ? "Takes the rest. Click to set a fixed width."
    : "Click for an exact width, or make this column flex.";
  width.addEventListener("click", () => selectColumn(ci));
  head.appendChild(width);
  node.appendChild(head);

  if (!col.modules.length) {
    node.appendChild(el("div", "column-empty", "empty — will be dropped"));
  }
  const hs = heights(col);
  col.modules.forEach((mod, mi) => {
    if (mi > 0) node.appendChild(makeHGrip(ci, mi - 1));
    const m = makeModule(mod, ci, mi);
    m.style.flex = `${hs[mi]} 1 0`;
    node.appendChild(m);
  });
  return node;
}

function makeHGrip(ci, upperIndex) {
  const grip = el("div", "hgrip");
  grip.title = "Drag: height share of the two modules";
  grip.addEventListener("pointerdown", (ev) => startHResize(ev, ci, upperIndex));
  return grip;
}

/* Kante zwischen zwei gestapelten Modulen ziehen: der Anteil wandert vom
 * einen zum anderen, die uebrigen Module der Spalte bleiben, wie sie sind. */
function startHResize(ev, ci, upperIndex) {
  ev.preventDefault();
  ev.stopPropagation();
  const col = columns()[ci];
  const upper = col.modules[upperIndex], lower = col.modules[upperIndex + 1];
  if (!upper || !lower) return;
  const colNode = ev.currentTarget.parentNode;
  const inner = colNode.getBoundingClientRect().height;
  const start = heights(col);
  col.modules.forEach((m, i) => { m.height = start[i]; });
  const startUpper = start[upperIndex], startLower = start[upperIndex + 1];
  const startY = ev.clientY;
  const grip = ev.currentTarget;
  grip.classList.add("active");

  function onMove(e) {
    const deltaPct = (e.clientY - startY) / inner * 100;
    const u = startUpper + deltaPct, l = startLower - deltaPct;
    if (u < 8 || l < 8) return;
    upper.height = u; lower.height = l;
    markDirty();
    const mods = colNode.querySelectorAll(".module");
    mods[upperIndex].style.flex = `${u} 1 0`;
    mods[upperIndex + 1].style.flex = `${l} 1 0`;
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
    grip.classList.remove("active");
    renderColumns();
  }
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp, { once: true });
}

function makeModule(mod, ci, mi) {
  const node = el("div", "module");
  node.dataset.col = String(ci);
  node.dataset.mod = String(mi);
  if (selected && selected.kind === "module" && selected.col === ci && selected.mod === mi) {
    node.classList.add("selected");
  }
  node.appendChild(el("div", "module-label", labelFor(mod.type).toUpperCase()));
  const sub = describeConfig(mod);
  if (sub) node.appendChild(el("div", "module-sub", sub));

  const x = el("button", "module-x", "×");
  x.title = "Remove module";
  x.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  x.addEventListener("click", (ev) => { ev.stopPropagation(); removeModule(ci, mi); });
  node.appendChild(x);

  node.addEventListener("pointerdown", (ev) => startDrag(ev, ci, mi));
  return node;
}

function removeModule(ci, mi) {
  const col = columns()[ci];
  if (!col || !col.modules[mi]) return;
  col.modules.splice(mi, 1);
  selected = null;
  markDirty();
  render();
}

/* Eine Zeile Kontext im Kasten — bei mehreren Web-Panels ist sonst nicht zu
 * sehen, welches welches ist. */
function describeConfig(mod) {
  const cfg = mod.config || {};
  if (mod.type === "web") {
    if (!cfg.url) return "no address";
    try { return new URL(cfg.url).hostname; } catch { return cfg.url.slice(0, 30); }
  }
  if (mod.type === "tradingview") {
    if ((cfg.mode || "widget") === "account") return cfg.url ? "own chart" : "not signed in";
    return cfg.symbol || "BINANCE:BTCUSDT";
  }
  if (mod.type === "openmarket") return cfg.url ? "own chart" : "not signed in";
  if (mod.type === "media" && cfg.music_dir) {
    return cfg.music_dir.split("/").filter(Boolean).pop() || cfg.music_dir;
  }
  if (mod.type === "sensors") {
    /* Immer zeigen, welche Sensoren drin sind — auch mit Default-Auswahl. */
    const field = (specFor("sensors") || { schema: [] }).schema.find((f) => f.key === "metrics");
    const names = Object.fromEntries((field && field.options) || []);
    const chosen = Array.isArray(cfg.metrics) && cfg.metrics.length
      ? cfg.metrics : (field && field.default) || [];
    return chosen.map((m) => names[m] || m).join(" · ");
  }
  if (mod.type === "processes" && cfg.count) return `${cfg.count} rows`;
  return "";
}

/* ---------- Hoehenanteile gestapelter Module ---------- */

/* Prozentanteile der Module einer Spalte; ohne Angaben gleich verteilt.
 *
 * Der Ersatzwert fuer ein Modul ohne eigenen Anteil muss *vor* dem Normieren
 * in die Summe: sonst wird durch eine zu kleine Summe geteilt. Ein Modul mit
 * height 25 neben einem ohne ergab so 200 und -100 — und layout_store lehnte
 * das Layout beim Speichern ab ("height 200 liegt nicht in 5..95"). Genau das
 * passiert beim Verschieben eines Moduls in eine Spalte, deren Module noch
 * keine Anteile haben. */
function heights(col) {
  const n = col.modules.length;
  if (!n) return [];
  const even = 100 / n;
  const raw = col.modules.map((m) => {
    const h = Number(m.height);
    return Number.isFinite(h) && h > 0 ? h : even;
  });
  const sum = raw.reduce((a, b) => a + b, 0) || 1;
  return raw.map((h) => h * 100 / sum);
}

/* Was layout_store durchlaesst. */
const clampPct = (h) => Math.max(5, Math.min(95, Math.round(h)));

/* Beim Speichern: Anteile als ganze Prozent, Summe 100; Einzelmodule ohne.
 * Der Rundungsrest wandert von hinten nach vorn zum ersten Modul, bei dem er
 * noch in 5..95 passt — ihn stur dem letzten aufzuschlagen konnte es aus dem
 * erlaubten Bereich schieben. */
function normaliseHeights(col) {
  if (col.modules.length < 2) { col.modules.forEach((m) => delete m.height); return; }
  const hs = heights(col).map(clampPct);
  let rest = 100 - hs.reduce((a, b) => a + b, 0);
  for (let i = hs.length - 1; i >= 0 && rest !== 0; i--) {
    const next = clampPct(hs[i] + rest);
    rest -= next - hs[i];
    hs[i] = next;
  }
  col.modules.forEach((m, i) => { m.height = hs[i]; });
}

/* ---------- Breite aendern ---------- */

function selectColumn(ci) {
  selected = { kind: "column", col: ci };
  renderStage();
  renderInspector();
}

/* Feste Breite setzen. Die einzige Flex-Spalte darf nicht einfach fest werden
 * — sonst hat das Layout keine mehr und fuellt den Bildschirm nicht. */
function setColumnWidth(ci, px) {
  const cols = columns();
  const col = cols[ci];
  if (!Number.isFinite(px) || px < 80) {
    setStatus("Width must be at least 80 px", "bad");
    return false;
  }
  if (col.width === FLEX) {
    const next = cols.findIndex((c, i) => i !== ci);
    if (next === -1) {
      setStatus("One column has to stay flex", "bad");
      return false;
    }
    cols[next].width = FLEX;
  }
  col.width = px;
  markDirty();
  render();
  return true;
}

/* Genau eine Flex-Spalte: setzen heisst verschieben. Die bisherige bekommt
 * die Breite, die sie gerade tatsaechlich hatte — so springt nichts. */
function setFlexColumn(ci) {
  const cols = columns();
  const old = cols.findIndex((c) => c.width === FLEX);
  if (old === ci) return;
  if (old !== -1) cols[old].width = Math.max(80, flexWidth());
  cols[ci].width = FLEX;
}

/* ---------- Ziehen: Spaltenbreite ---------- */

/* Beim Ziehen rastet die Breite in 10-px-Schritten. Pixelgenau war beim
 * Ziehen unbrauchbar: eine Spalte auf einem 2560er Streifen ist im Editor
 * gut vier Mal kleiner gezeichnet, ein Bildschirmpixel also mehrere echte —
 * runde Zahlen kamen nur mit Glueck heraus. Ueber das Zahlenfeld im
 * Inspektor bleibt jeder Wert eingebbar. */
const SNAP_PX = 10;
const snapPx = (v) => Math.round(v / SNAP_PX) * SNAP_PX;

function startResize(ev, leftIndex) {
  ev.preventDefault();
  const host = $("columns");
  const cols = columns();
  const left = cols[leftIndex];
  const right = cols[leftIndex + 1];
  if (!left || !right) return;

  const pxPerScreenPx = STAGE.width / host.getBoundingClientRect().width;
  const startX = ev.clientX;
  const startLeft = renderedWidth(left);
  const startRight = renderedWidth(right);
  const grip = ev.currentTarget;
  grip.classList.add("active");

  /* Die Flex-Spalte hat keine eigene Zahl — sie ergibt sich aus dem Rest.
   * Beim Ziehen wird deshalb immer die *feste* der beiden veraendert; sind
   * beide fest, wandert die Breite von einer zur anderen. */
  function onMove(e) {
    const delta = Math.round((e.clientX - startX) * pxPerScreenPx);
    if (left.width !== FLEX && right.width !== FLEX) {
      /* Beide fest: die Breite wandert nur von einer zur anderen, die Summe
       * bleibt — sonst ruecken alle uebrigen Spalten mit. Deshalb rastet die
       * linke, und die rechte ergibt sich daraus. */
      const l = snapPx(startLeft + delta), r = startLeft + startRight - l;
      if (l < 80 || r < 80) return;
      left.width = l; right.width = r;
    } else if (left.width !== FLEX) {
      const l = snapPx(startLeft + delta);
      if (l < 80 || STAGE.width - (fixedTotal() - left.width + l) < 80) return;
      left.width = l;
    } else {
      const r = snapPx(startRight - delta);
      if (r < 80 || STAGE.width - (fixedTotal() - right.width + r) < 80) return;
      right.width = r;
    }
    markDirty();
    renderStageMeta();
    renderColumns();
    if (selected && selected.kind === "column") renderInspector();
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
  }
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp, { once: true });
}

/* ---------- Ziehen: Modul verschieben ---------- */

function startDrag(ev, ci, mi) {
  ev.preventDefault();
  select(ci, mi);

  const source = ev.currentTarget;
  let moved = false;
  let marker = null;
  let target = null;   // {col, index}

  function clearMarker() {
    if (marker && marker.parentNode) marker.parentNode.removeChild(marker);
    document.querySelectorAll(".column.drop-target").forEach((n) => n.classList.remove("drop-target"));
    marker = null;
  }
  function onMove(e) {
    if (!moved && Math.abs(e.clientY - ev.clientY) < 3 && Math.abs(e.clientX - ev.clientX) < 3) return;
    if (!moved) { moved = true; source.classList.add("dragging"); }
    const colNode = columnUnder(e.clientX);
    clearMarker();
    if (!colNode) { target = null; return; }
    colNode.classList.add("drop-target");
    const index = insertIndexIn(colNode, e.clientY);
    target = { col: Number(colNode.dataset.col), index };
    marker = el("div", "drop-line");
    const mods = [...colNode.querySelectorAll(".module")];
    if (index >= mods.length) colNode.appendChild(marker);
    else colNode.insertBefore(marker, mods[index]);
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
    source.classList.remove("dragging");
    clearMarker();
    if (moved && target) {
      moveModule(ci, mi, target.col, target.index);
      markDirty();
    }
    render();
  }
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp, { once: true });
}

function columnUnder(clientX) {
  for (const node of document.querySelectorAll(".column")) {
    const r = node.getBoundingClientRect();
    if (clientX >= r.left && clientX <= r.right) return node;
  }
  return null;
}

/* Einfuegeposition: vor dem ersten Modul, dessen Mitte unter dem Zeiger liegt. */
function insertIndexIn(colNode, clientY) {
  const mods = [...colNode.querySelectorAll(".module")];
  for (let i = 0; i < mods.length; i++) {
    const r = mods[i].getBoundingClientRect();
    if (clientY < r.top + r.height / 2) return i;
  }
  return mods.length;
}

function moveModule(fromCol, fromMod, toCol, toIndex) {
  const cols = columns();
  const [mod] = cols[fromCol].modules.splice(fromMod, 1);
  if (!mod) return;
  if (fromCol === toCol && fromMod < toIndex) toIndex--;
  cols[toCol].modules.splice(toIndex, 0, mod);
  selected = { kind: "module", col: toCol, mod: Math.min(toIndex, cols[toCol].modules.length - 1) };
}

/* ---------- Ziehen: Topbar-Widget ---------- */

function startChipDrag(ev, slot, index) {
  ev.preventDefault();
  selected = { kind: "topbar", slot, index };
  renderTopbar();
  renderInspector();

  const source = ev.currentTarget;
  let moved = false;
  let marker = null;
  let target = null;   // {slot, index}

  function clearMarker() {
    if (marker && marker.parentNode) marker.parentNode.removeChild(marker);
    document.querySelectorAll(".tb-slot.drop-target").forEach((n) => n.classList.remove("drop-target"));
    marker = null;
  }
  function onMove(e) {
    if (!moved && Math.abs(e.clientX - ev.clientX) < 3 && Math.abs(e.clientY - ev.clientY) < 3) return;
    if (!moved) { moved = true; source.classList.add("dragging"); }
    const slotNode = slotUnder(e.clientX, e.clientY);
    clearMarker();
    if (!slotNode) { target = null; return; }
    slotNode.classList.add("drop-target");
    const chips = [...slotNode.querySelectorAll(".chip:not(.fixed)")];
    let idx = chips.length;
    for (let i = 0; i < chips.length; i++) {
      const r = chips[i].getBoundingClientRect();
      if (e.clientX < r.left + r.width / 2) { idx = i; break; }
    }
    target = { slot: slotNode.dataset.slot, index: idx };
    marker = el("div", "drop-line-v");
    if (idx >= chips.length) {
      const fixed = slotNode.querySelector(".chip.fixed");
      if (fixed) slotNode.insertBefore(marker, fixed); else slotNode.appendChild(marker);
    } else {
      slotNode.insertBefore(marker, chips[idx]);
    }
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
    source.classList.remove("dragging");
    clearMarker();
    if (moved && target) {
      const data = topbar();
      const [w] = data[slot].splice(index, 1);
      let idx = target.index;
      if (target.slot === slot && index < idx) idx--;
      data[target.slot].splice(idx, 0, w);
      selected = { kind: "topbar", slot: target.slot, index: idx };
      markDirty();
    }
    renderTopbar();
    renderInspector();
  }
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp, { once: true });
}

function slotUnder(x, y) {
  for (const node of document.querySelectorAll(".tb-slot")) {
    const r = node.getBoundingClientRect();
    if (x >= r.left && x <= r.right && y >= r.top - 6 && y <= r.bottom + 6) return node;
  }
  return null;
}

/* ---------- Auswahl ---------- */

function select(ci, mi) {
  selected = { kind: "module", col: ci, mod: mi };
  renderStage();
  renderInspector();
}

/* ---------- Formulare aus dem Schema ---------- */

/* Welche Gruppen aufgeklappt sind. Ausserhalb von renderForm, damit ein neu
 * gezeichneter Inspektor nicht alles wieder zuklappt. */
const openGroups = new Set();

/* Wert eines Feldes, wie ihn das Formular sieht: das Gespeicherte, sonst der
 * Default aus dem Schema. Ohne den Default waere ein Feld mit
 * show_if ("mode" = "widget") unsichtbar, solange niemand die Auswahl
 * einmal angefasst hat — der Default ist ja gerade "widget". */
function effectiveValue(schema, values, key) {
  if (values[key] !== undefined && values[key] !== null) return values[key];
  const field = schema.find((f) => f.key === key);
  return field ? field.default : undefined;
}

/* Erfuellt das Feld seine show_if-Bedingung? Leere Werteliste heisst
 * "irgendein nicht-leerer Wert". */
function fieldVisible(f, schema, values) {
  if (!f.show_if) return true;
  const [key, allowed] = f.show_if;
  const value = effectiveValue(schema, values, key);
  if (!allowed || !allowed.length) {
    return Array.isArray(value) ? value.length > 0
                                : value !== undefined && value !== null && value !== "";
  }
  return allowed.some((v) => String(v) === String(value));
}

/* Schluessel, von denen die Sichtbarkeit anderer Felder abhaengt — aendert
 * sich so einer, muss der Inspektor neu gezeichnet werden. */
function visibilityKeys(schema) {
  return new Set(schema.filter((f) => f.show_if).map((f) => f.show_if[0]));
}

/* Ein Formular fuer eine Feldliste. onChange(key, value) wird bei jeder
 * Aenderung gerufen; das Formular selbst wird dabei nicht neu gebaut, sonst
 * fiele der Fokus aus dem Feld. Felder mit `group` landen in einem
 * aufklappbaren Block, Felder mit unerfuellter `show_if` gar nicht. */
function renderForm(schema, values, onChange) {
  const form = el("div", "form");
  /* Ziel des naechsten Feldes: das Formular selbst, oder der Inhalt der
   * gerade offenen Gruppe. */
  let target = form;
  let group = "";

  for (const f of schema) {
    if (!fieldVisible(f, schema, values)) continue;

    const wanted = f.group || "";
    if (wanted !== group) {
      group = wanted;
      target = form;
      if (wanted) {
        const count = schema.filter((g) => (g.group || "") === wanted
                                           && fieldVisible(g, schema, values)).length;
        const box = el("details", "group");
        box.open = openGroups.has(wanted);
        const head = el("summary", null, `${wanted} (${count})`);
        box.appendChild(head);
        box.addEventListener("toggle", () => {
          if (box.open) openGroups.add(wanted); else openGroups.delete(wanted);
        });
        form.appendChild(box);
        target = box;
      }
    }

    const field = el("div", "field");
    const label = el("label", null, f.label);
    const current = values[f.key] !== undefined && values[f.key] !== null ? values[f.key] : f.default;

    if (f.kind === "bool") {
      /* Schalter rechts neben dem Text, Hilfe darunter — nicht daneben, dort
       * bricht sie in der schmalen Seitenleiste nur um. */
      const row = el("div", "check-row");
      const input = el("input");
      input.type = "checkbox";
      input.checked = Boolean(current);
      input.addEventListener("change", () => onChange(f.key, input.checked));
      row.appendChild(label);
      row.appendChild(input);
      field.appendChild(row);
    } else if (f.kind === "select") {
      field.appendChild(label);
      const sel = el("select");
      for (const [value, text] of f.options || []) {
        const opt = el("option", null, text);
        opt.value = value;
        if (String(value) === String(current ?? "")) opt.selected = true;
        sel.appendChild(opt);
      }
      sel.addEventListener("change", () => onChange(f.key, sel.value));
      field.appendChild(sel);
    } else if (f.kind === "list") {
      field.appendChild(label);
      const box = el("div", "checks");
      const chosen = new Set(Array.isArray(current) ? current : []);
      for (const [value, text] of f.options || []) {
        const wrap = el("label");
        const cb = el("input");
        cb.type = "checkbox";
        cb.checked = chosen.has(value);
        cb.addEventListener("change", () => {
          if (cb.checked) chosen.add(value); else chosen.delete(value);
          // Reihenfolge der Optionen beibehalten, nicht die der Klicks.
          onChange(f.key, (f.options || []).map((o) => o[0]).filter((v) => chosen.has(v)));
        });
        wrap.appendChild(cb);
        wrap.appendChild(el("span", null, text));
        box.appendChild(wrap);
      }
      field.appendChild(box);
    } else {
      field.appendChild(label);
      const input = el("input");
      input.type = (f.kind === "int" || f.kind === "float") ? "number" : "text";
      if (f.kind === "int") input.step = "1";
      if (f.kind === "float") input.step = "any";
      if (f.min !== null && f.min !== undefined) input.min = String(f.min);
      if (f.max !== null && f.max !== undefined) input.max = String(f.max);
      input.value = current === null || current === undefined ? "" : String(current);
      input.dataset.key = f.key;
      input.addEventListener("change", () => {
        let v = input.value.trim();
        if (f.kind === "int") v = v === "" ? null : parseInt(v, 10);
        else if (f.kind === "float") v = v === "" ? null : parseFloat(v);
        if ((f.kind === "int" || f.kind === "float") && v !== null && !Number.isFinite(v)) return;
        onChange(f.key, v);
      });
      if (f.kind === "path" || f.kind === "dir") {
        /* Tippen geht auch — der Editor laeuft am Rechner mit Tastatur —,
         * aber einen Pfad abzutippen ist fehlertraechtig. Derselbe Knopf und
         * dieselbe Verdrahtung wie beim Deck-Kommando, nur oeffnet der Picker
         * im Home statt in /usr/bin. */
        const wrap = el("div", "with-btn");
        const browse = el("button", "ghost", "…");
        browse.title = f.kind === "dir" ? "Choose folder" : "Choose file";
        browse.addEventListener("click", () => {
          pendingBrowse = input;
          post({ action: "browse", target: f.kind === "dir" ? "dir" : "file" });
        });
        wrap.appendChild(input);
        wrap.appendChild(browse);
        field.appendChild(wrap);
      } else {
        field.appendChild(input);
      }
    }
    if (f.help) field.appendChild(el("div", "help", f.help));
    target.appendChild(field);
  }
  return form;
}

/* ---------- Inspektor ---------- */

function renderInspector() {
  const box = $("inspector");
  const title = $("side-title");
  box.innerHTML = "";
  $("settings-btn").classList.toggle("active", Boolean(selected && selected.kind === "settings"));

  if (!selected) {
    title.textContent = "Selection";
    box.appendChild(el("p", "muted",
      "Nothing selected. Click a module, a topbar widget or a column width — " +
      "or Settings at the top."));
    return;
  }
  if (selected.kind === "settings") return renderSettings(box, title);
  if (selected.kind === "column") return renderColumnInspector(box, title);
  if (selected.kind === "topbar") return renderTopbarInspector(box, title);
  return renderModuleInspector(box, title);
}

function renderSettings(box, title) {
  title.textContent = "Settings";
  box.appendChild(renderForm(SETTINGS_SCHEMA, settings, (key, value) => {
    settings[key] = value;
    markDirty();
  }));
  box.appendChild(el("p", "muted",
    "Takes effect in the dashboard right after saving. The memory cap applies to " +
    "newly built web panels."));
}

function renderColumnInspector(box, title) {
  const ci = selected.col;
  const col = columns()[ci];
  if (!col) { selected = null; return renderInspector(); }
  title.textContent = `Column ${ci + 1} of ${columns().length}`;

  const row = el("div", "row");
  row.appendChild(el("label", null, "Width"));
  const input = el("input");
  input.type = "number"; input.min = "80"; input.step = "10";
  input.value = String(renderedWidth(col));
  input.disabled = col.width === FLEX;
  input.addEventListener("change", () => setColumnWidth(ci, parseInt(input.value, 10)));
  row.appendChild(input);
  row.appendChild(el("span", "muted", "px"));
  box.appendChild(row);

  const flexRow = el("div", "row");
  flexRow.appendChild(el("label", null, "Flex"));
  const flexBtn = el("button", "ghost", col.width === FLEX ? "takes the rest" : "make this column flex");
  flexBtn.disabled = col.width === FLEX;
  flexBtn.title = "Exactly one column fills the remaining space.";
  flexBtn.addEventListener("click", () => { setFlexColumn(ci); markDirty(); render(); });
  flexRow.appendChild(flexBtn);
  box.appendChild(flexRow);

  box.appendChild(el("p", "muted", (col.width === FLEX
    ? "This column gets whatever the fixed ones leave over. "
    : "Fixed width in pixels on the target monitor. ")
    + "With several modules in the column, the edge between them can be dragged."));
}

function renderTopbarInspector(box, title) {
  const data = topbar();
  const w = data[selected.slot] && data[selected.slot][selected.index];
  if (!w) { selected = null; return renderInspector(); }
  const spec = topbarSpecFor(w.type);
  title.textContent = `Topbar · ${topbarLabelFor(w.type)}`;
  w.config = w.config || {};
  if (spec && spec.schema.length) {
    const gates = visibilityKeys(spec.schema);
    box.appendChild(renderForm(spec.schema, w.config, (key, value) => {
      if (value === null || value === "") delete w.config[key]; else w.config[key] = value;
      markDirty();
      if (gates.has(key)) renderInspector();
    }));
  } else {
    box.appendChild(el("p", "muted", "This widget has no settings."));
  }
}

function renderModuleInspector(box, title) {
  const col = columns()[selected.col];
  const mod = col && col.modules[selected.mod];
  if (!mod) { selected = null; return renderInspector(); }
  const spec = specFor(mod.type);
  title.textContent = labelFor(mod.type);
  mod.config = mod.config || {};

  if (mod.type === "deck") return renderDeckEditor(box);

  if (spec && spec.schema.length) {
    const gates = visibilityKeys(spec.schema);
    box.appendChild(renderForm(spec.schema, mod.config, (key, value) => {
      if (value === null || value === "") delete mod.config[key]; else mod.config[key] = value;
      markDirty();
      renderColumns();
      // Haengt die Sichtbarkeit anderer Felder an diesem, muss das Formular
      // neu gebaut werden — sonst bleiben Felder stehen, die im neuen Modus
      // nichts mehr tun.
      if (gates.has(key)) renderInspector();
    }));
  } else {
    box.appendChild(el("p", "muted", "This module has no settings."));
  }

  /* TradingView und OpenMarket holen sich ihren Chart ueber dasselbe
   * Login-Fenster; die Seite sagt der Bruecke, welche Site. */
  if (mod.type === "tradingview" || mod.type === "openmarket") {
    const btns = el("div", "row-btns");
    const login = el("button", "ghost", "Sign in / choose chart…");
    login.title = "Opens a browser window: sign in there, open a chart, “Use as chart”";
    login.addEventListener("click", () => {
      pendingLogin = mod;
      login.disabled = true;
      setStatus("Login window open …", "");
      post({ action: "login", site: mod.type });
    });
    btns.appendChild(login);
    if (mod.type === "tradingview") {
      const widget = el("button", "ghost", "Back to the widget");
      widget.title = "Show the anonymous widget again; the chart address stays saved";
      widget.disabled = (mod.config.mode || "widget") !== "account";
      widget.addEventListener("click", () => {
        mod.config.mode = "widget"; markDirty(); renderColumns(); renderInspector();
      });
      btns.appendChild(widget);
    }
    box.appendChild(btns);
    box.appendChild(el("p", "muted", mod.type === "tradingview"
      ? "Signing in writes the address into the field above and sets the source to " +
        "“Own chart”. The full page costs about 1 GB; see the memory cap " +
        "in the settings. The widget costs a fraction of that."
      : "Signing in writes the address of the opened chart into the field above. " +
        "The page costs about 1 GB and permanently about a third of a core; " +
        "see the memory cap in the settings."));
  }
}

/* ---------- Deck ---------- */

const emptyEntry = (kind, n) => ({ id: `${kind}${n}`, label: "", command: "", args: "", kind });

function appSlots() {
  const n = parseInt(settings.deck_app_slots, 10);
  return Number.isFinite(n) ? Math.max(0, Math.min(DECK.slots, n)) : 9;
}

/* Die 18 Plaetze: erst die Apps, dann die Macros. Beide Listen werden bis zu
 * ihrem Kontingent aufgefuellt; was darueber hinaus in apps.json steht,
 * bleibt erhalten (Regler runter und wieder rauf bringt es zurueck). */
function deckEntries() {
  const a = appSlots(), m = DECK.slots - a;
  while (apps.apps.length < a) apps.apps.push(emptyEntry("app", apps.apps.length + 1));
  while (apps.macros.length < m) apps.macros.push(emptyEntry("macro", apps.macros.length + 1));
  const out = [];
  for (let i = 0; i < a; i++) out.push(apps.apps[i]);
  for (let i = 0; i < m; i++) out.push(apps.macros[i]);
  return out;
}

function setDeckEntry(i, entry) {
  const a = appSlots();
  if (i < a) { entry.kind = "app"; apps.apps[i] = entry; }
  else { entry.kind = "macro"; apps.macros[i - a] = entry; }
}

const entryLabel = (e) => {
  if (e.label) return e.label;
  const cmd = (e.command || "").trim();
  if (!cmd) return "";
  const base = cmd.split("/").pop();
  return base.includes(".") ? base.slice(0, base.lastIndexOf(".")) : base;
};

function renderDeckEditor(box) {
  const entries = deckEntries();
  if (deckSlot >= entries.length) deckSlot = 0;

  const split = el("div", "field");
  split.appendChild(el("label", null, `Pads for apps (the rest are macros): ${appSlots()} + ${DECK.slots - appSlots()}`));
  const range = el("input");
  range.type = "number"; range.min = "0"; range.max = String(DECK.slots); range.step = "1";
  range.value = String(appSlots());
  range.addEventListener("change", () => {
    const n = parseInt(range.value, 10);
    if (!Number.isFinite(n)) return;
    settings.deck_app_slots = Math.max(0, Math.min(DECK.slots, n));
    markDirty();
    renderInspector();
  });
  split.appendChild(range);
  box.appendChild(split);

  const grid = el("div", "deck");
  grid.style.gridTemplateColumns = `repeat(${DECK.cols}, 1fr)`;
  entries.forEach((e, i) => {
    const cell = el("div", "deck-cell");
    const text = entryLabel(e);
    cell.textContent = text || "—";
    if (!text) cell.classList.add("empty");
    if (i >= appSlots()) cell.classList.add("macro");
    if (e.confirm) cell.classList.add("danger");
    if (i === deckSlot) cell.classList.add("selected");
    cell.dataset.index = String(i);
    cell.addEventListener("pointerdown", (ev) => startDeckDrag(ev, i));
    decorateCell(cell, e);
    grid.appendChild(cell);
  });
  box.appendChild(grid);
  const legend = el("div", "deck-legend");
  legend.appendChild(el("span", null, "solid = app"));
  legend.appendChild(el("span", null, "dashed = macro"));
  legend.appendChild(el("span", null, "! = hold to confirm"));
  legend.appendChild(el("span", null, "dot = colour"));
  box.appendChild(legend);

  const e = entries[deckSlot];
  const kind = deckSlot < appSlots() ? "App" : "Macro";
  box.appendChild(el("h2", null, `Pad ${deckSlot + 1} · ${kind}`));

  const form = el("div", "form");
  const text = (key, label, help) => {
    const field = el("div", "field");
    field.appendChild(el("label", null, label));
    const wrap = el("div", "with-btn");
    const input = el("input");
    input.type = "text";
    input.value = e[key] || "";
    input.addEventListener("change", () => {
      e[key] = input.value.trim();
      markDirty();
      refreshDeckCells();
    });
    wrap.appendChild(input);
    if (key === "command") {
      const browse = el("button", "ghost", "…");
      browse.title = "Choose program";
      browse.addEventListener("click", () => { pendingBrowse = input; post({ action: "browse" }); });
      wrap.appendChild(browse);
    }
    field.appendChild(wrap);
    if (help) field.appendChild(el("div", "help", help));
    form.appendChild(field);
    return input;
  };
  text("label", "Label", "Empty = file name of the command");
  text("command", "Command");
  text("args", "Arguments");
  text("icon", "Icon", "Name from xeneon_edge/icons/, path to an SVG/PNG or a theme icon name; empty = automatic");

  const confirm = el("div", "field");
  const confirmRow = el("div", "check-row");
  confirmRow.appendChild(el("label", null, "Hold to trigger"));
  const cb = el("input"); cb.type = "checkbox"; cb.checked = Boolean(e.confirm);
  cb.addEventListener("change", () => { e.confirm = cb.checked; markDirty(); refreshDeckCells(); });
  confirmRow.appendChild(cb);
  confirm.appendChild(confirmRow);
  form.appendChild(confirm);

  const btns = el("div", "row-btns");
  const clear = el("button", "ghost danger", "Clear pad");
  clear.addEventListener("click", () => {
    setDeckEntry(deckSlot, emptyEntry(deckSlot < appSlots() ? "app" : "macro", deckSlot + 1));
    markDirty();
    renderInspector();
  });
  btns.appendChild(clear);
  form.appendChild(btns);
  box.appendChild(form);
}

/* Nur die Zellen nachziehen — das Formular bleibt stehen, der Fokus auch. */
function refreshDeckCells() {
  const entries = deckEntries();
  document.querySelectorAll(".deck-cell").forEach((cell, i) => {
    const e = entries[i];
    const text = entryLabel(e);
    cell.textContent = text || "—";
    cell.classList.toggle("empty", !text);
    cell.classList.toggle("danger", Boolean(e.confirm));
    decorateCell(cell, e);
  });
}

/* ---- Pad-Farbe: untere Kante + Farbpunkt mit Palette ---- */

const PAD_COLOURS = [
  "#ff0033", "#ff6a00", "#ffd000", "#00ff66", "#00d4ff", "#3b82f6",
  "#a855f7", "#ff4fd8", "#ffffff", "#9ca3af", "#22c55e", "#ef4444",
];
const hexOf = (e) => {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(String(e.accent || "").trim());
  return m ? "#" + m[1].toLowerCase() : "";
};

function decorateCell(cell, e) {
  cell.querySelectorAll(".pad-dot").forEach((d) => d.remove());
  const colour = hexOf(e) || getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  cell.style.borderBottomColor = colour;
  const dot = el("span", "pad-dot");
  dot.style.background = colour;
  dot.title = "Pad colour";
  dot.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  dot.addEventListener("click", (ev) => { ev.stopPropagation(); openPalette(cell, e); });
  cell.appendChild(dot);
}

function closePalette() {
  document.querySelectorAll(".palette").forEach((p) => p.remove());
}

function openPalette(cell, e) {
  closePalette();
  const pal = el("div", "palette");
  const r = cell.getBoundingClientRect();
  const host = $("inspector").getBoundingClientRect();
  pal.style.left = `${Math.max(0, r.left - host.left)}px`;
  pal.style.top = `${r.bottom - host.top + 4}px`;

  const apply = (hex) => {
    if (hex) e.accent = hex; else delete e.accent;
    markDirty();
    refreshDeckCells();
    closePalette();
  };

  const sw = el("div", "swatches");
  const theme = el("div", "swatch theme");
  theme.title = "Theme accent";
  theme.addEventListener("click", () => apply(""));
  sw.appendChild(theme);
  for (const c of PAD_COLOURS) {
    const s = el("div", "swatch");
    s.style.background = c;
    s.title = c;
    s.addEventListener("click", () => apply(c));
    sw.appendChild(s);
  }
  pal.appendChild(sw);

  const row = el("div", "with-btn");
  const input = el("input");
  input.type = "text"; input.placeholder = "#rrggbb"; input.value = hexOf(e);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { const m = /^#?([0-9a-fA-F]{6})$/.exec(input.value.trim()); if (m) apply("#" + m[1].toLowerCase()); }
    if (ev.key === "Escape") closePalette();
  });
  const ok = el("button", "ghost", "OK");
  ok.addEventListener("click", () => { const m = /^#?([0-9a-fA-F]{6})$/.exec(input.value.trim()); if (m) apply("#" + m[1].toLowerCase()); });
  row.appendChild(input); row.appendChild(ok);
  pal.appendChild(row);

  pal.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  $("inspector").style.position = "relative";
  $("inspector").appendChild(pal);
  input.focus();
}

function startDeckDrag(ev, i) {
  ev.preventDefault();
  const source = ev.currentTarget;
  let moved = false;
  let over = null;

  function cellUnder(x, y) {
    for (const node of document.querySelectorAll(".deck-cell")) {
      const r = node.getBoundingClientRect();
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return node;
    }
    return null;
  }
  function onMove(e) {
    if (!moved && Math.abs(e.clientX - ev.clientX) < 4 && Math.abs(e.clientY - ev.clientY) < 4) return;
    if (!moved) { moved = true; source.classList.add("dragging"); }
    document.querySelectorAll(".deck-cell.drop-target").forEach((n) => n.classList.remove("drop-target"));
    over = cellUnder(e.clientX, e.clientY);
    if (over && over !== source) over.classList.add("drop-target");
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
    source.classList.remove("dragging");
    document.querySelectorAll(".deck-cell.drop-target").forEach((n) => n.classList.remove("drop-target"));
    if (moved && over && over !== source) {
      const j = Number(over.dataset.index);
      const entries = deckEntries();
      const a = clone(entries[i]), b = clone(entries[j]);
      setDeckEntry(i, b);
      setDeckEntry(j, a);
      deckSlot = j;
      markDirty();
    } else {
      deckSlot = i;
    }
    renderInspector();
  }
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp, { once: true });
}

/* ---------- Hinzufuegen-Menue ---------- */

function renderMenu() {
  const mods = $("menu-modules");
  mods.innerHTML = "";
  for (const spec of CATALOGUE) {
    const b = el("button", null, spec.label);
    const present = spec.singleton && columns().some((c) => c.modules.some((m) => m.type === spec.type));
    b.disabled = present;
    b.title = present ? "Can only be added once" : "Into the selected column, otherwise the last one";
    b.addEventListener("click", () => { addModule(spec); closeMenu(); });
    mods.appendChild(b);
  }
  const tb = $("menu-topbar");
  tb.innerHTML = "";
  const data = topbar();
  for (const spec of TOPBAR_CATALOGUE) {
    const b = el("button", null, spec.label);
    const present = spec.singleton && SLOTS.some((s) => data[s].some((w) => w.type === spec.type));
    b.disabled = present;
    b.title = present ? "Can only be added once" : "Into the selected slot, otherwise the centre";
    b.addEventListener("click", () => { addTopbar(spec); closeMenu(); });
    tb.appendChild(b);
  }
}

function openMenu() { renderMenu(); $("add-menu").hidden = false; }
function closeMenu() { $("add-menu").hidden = true; }

function addModule(spec) {
  const cols = columns();
  const ci = selected && (selected.kind === "module" || selected.kind === "column")
    ? selected.col : cols.length - 1;
  cols[ci].modules.push({ type: spec.type, config: {} });
  selected = { kind: "module", col: ci, mod: cols[ci].modules.length - 1 };
  markDirty();
  render();
}

function addTopbar(spec) {
  const data = topbar();
  const slot = selected && selected.kind === "topbar" ? selected.slot : "center";
  data[slot].push({ type: spec.type, config: {} });
  selected = { kind: "topbar", slot, index: data[slot].length - 1 };
  markDirty();
  render();
}

/* ---------- Profile ---------- */

function renderProfiles() {
  const sel = $("profile");
  sel.innerHTML = "";
  for (const [id, prof] of Object.entries(layout.profiles)) {
    const opt = el("option", null, prof.label || id);
    opt.value = id;
    if (id === layout.active_profile) opt.selected = true;
    sel.appendChild(opt);
  }
  $("profile-delete").disabled = Object.keys(layout.profiles).length < 2;
}

function slugify(name) {
  const base = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return base || "profile";
}
function uniqueId(base) {
  let id = base, n = 2;
  while (layout.profiles[id]) id = `${base}-${n++}`;
  return id;
}

/* Namenseingabe blendet sich in der Kopfleiste ein. Kein prompt(): WebKitGTK
 * zeigt Skript-Dialoge je nach Version gar nicht, dann bliebe der Knopf ohne
 * jede Wirkung. */
function askName(initial, onCommit) {
  const input = $("profile-name");
  input.hidden = false;
  input.value = initial;
  input.focus();
  input.select();
  function done(commit) {
    input.hidden = true;
    input.removeEventListener("keydown", onKey);
    input.removeEventListener("blur", onBlur);
    if (commit) { const name = input.value.trim(); if (name) onCommit(name); }
  }
  function onKey(e) { if (e.key === "Enter") done(true); else if (e.key === "Escape") done(false); }
  function onBlur() { done(false); }
  input.addEventListener("keydown", onKey);
  input.addEventListener("blur", onBlur);
}

function newProfile() {
  askName("New", (name) => {
    const id = uniqueId(slugify(name));
    layout.profiles[id] = clone(profile());
    layout.profiles[id].label = name;
    layout.active_profile = id;
    selected = null;
    markDirty();
    render();
  });
}
function renameProfile() {
  const prof = profile();
  askName(prof.label || layout.active_profile, (name) => { prof.label = name; markDirty(); render(); });
}

let deleteArmed = false;
let deleteTimer = null;
function resetDelete() {
  deleteArmed = false;
  if (deleteTimer) { clearTimeout(deleteTimer); deleteTimer = null; }
  const btn = $("profile-delete");
  btn.textContent = "×";
  btn.classList.remove("primary");
}
function deleteProfile() {
  if (Object.keys(layout.profiles).length < 2) return;
  if (!deleteArmed) {
    deleteArmed = true;
    const btn = $("profile-delete");
    btn.textContent = "really?";
    btn.classList.add("primary");
    deleteTimer = setTimeout(resetDelete, 4000);
    return;
  }
  resetDelete();
  delete layout.profiles[layout.active_profile];
  layout.active_profile = Object.keys(layout.profiles)[0];
  selected = null;
  markDirty();
  render();
}

/* ---------- Bruecke zu Python ---------- */

let pendingLogin = null;    // Chart-Modul (TradingView/OpenMarket), das auf die Login-URL wartet
let pendingBrowse = null;   // Eingabefeld, das auf den Datei-Picker wartet

function post(msg) {
  if (!window.webkit || !window.webkit.messageHandlers || !window.webkit.messageHandlers.bridge) {
    setStatus("No connection to the dashboard", "bad");
    return false;
  }
  window.webkit.messageHandlers.bridge.postMessage(JSON.stringify(msg));
  return true;
}

window.__login_done = function (url, error) {
  const mod = pendingLogin;
  pendingLogin = null;
  if (url && mod) {
    mod.config = mod.config || {};
    mod.config.url = url;
    // Ohne das bliebe die Quelle auf "Widget" und der frisch gewaehlte Chart
    // waere nirgends zu sehen. OpenMarket hat keinen Widget-Modus.
    if (mod.type === "tradingview") mod.config.mode = "account";
    markDirty();
    setStatus("Chart taken over — remember to save", "ok");
  } else {
    setStatus(error || "No chart taken over", "bad");
  }
  renderColumns();
  renderInspector();
};

window.__browsed = function (path) {
  if (pendingBrowse && path) {
    pendingBrowse.value = path;
    pendingBrowse.dispatchEvent(new Event("change"));
  }
  pendingBrowse = null;
};

/* ---------- Speichern ---------- */

/* Leere Spalten fliegen raus — layout_store lehnt sie ab, und eine Spalte ohne
 * Module ist ohnehin nur ein Rest vom Verschieben. */
function cleaned() {
  const copy = clone(layout);
  for (const prof of Object.values(copy.profiles)) {
    prof.columns = prof.columns.filter((c) => c.modules.length > 0);
    prof.columns.forEach(normaliseHeights);
  }
  return copy;
}

function save() {
  const data = cleaned();
  const prof = data.profiles[data.active_profile];
  if (!prof.columns.length) { setStatus("Layout has no columns", "bad"); return; }
  const flex = prof.columns.filter((c) => c.width === FLEX).length;
  if (flex !== 1) { setStatus(`Exactly one column has to be flex (currently ${flex})`, "bad"); return; }
  if (post({ action: "save", layout: data, settings, apps })) setStatus("Saving …", "");
}

/* Von Python nach dem Schreiben aufgerufen. */
window.__saved = function (ok, message) {
  setStatus(message, ok ? "ok" : "bad");
  if (ok) {
    dirty = false;
    ORIGINAL = JSON.stringify({ layout, settings, apps });
    $("save").disabled = true;
    $("revert").disabled = true;
  }
};

function revert() {
  loadWorking();
  selected = null;
  dirty = false;
  $("save").disabled = true;
  $("revert").disabled = true;
  setStatus("Discarded", "");
  render();
}

/* ---------- Start ---------- */

function init() {
  applyPalette();
  loadWorking();

  if (!layout || !layout.profiles || !layout.active_profile) {
    document.body.innerHTML =
      "<p style='padding:20px'>No layout loaded — layout.json is missing or invalid.</p>";
    return;
  }

  $("profile").addEventListener("change", (e) => {
    resetDelete();
    layout.active_profile = e.target.value;
    selected = null;
    markDirty();
    render();
  });
  $("profile-new").addEventListener("click", newProfile);
  $("profile-rename").addEventListener("click", renameProfile);
  $("profile-delete").addEventListener("click", deleteProfile);
  $("save").addEventListener("click", save);
  $("revert").addEventListener("click", revert);
  $("save").disabled = true;
  $("revert").disabled = true;

  $("add-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    if ($("add-menu").hidden) openMenu(); else closeMenu();
  });
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest(".menu-wrap")) closeMenu();
    if (!e.target.closest(".palette") && !e.target.classList.contains("pad-dot")) closePalette();
  });
  $("settings-btn").addEventListener("click", () => {
    selected = selected && selected.kind === "settings" ? null : { kind: "settings" };
    renderStage();
    renderInspector();
  });

  /* Klick ins Leere hebt die Auswahl auf. */
  $("stage").addEventListener("pointerdown", (e) => {
    const t = e.target;
    if (t.id === "stage" || t.id === "columns" || t.id === "topbar"
        || t.classList.contains("column") || t.classList.contains("column-empty")
        || t.classList.contains("tb-slot")) {
      selected = null;
      renderStage();
      renderInspector();
    }
  });

  /* Die Greifkanten sitzen auf gemessenen Pixeln — nach einer
   * Fenstergroesse stimmen sie nicht mehr. */
  window.addEventListener("resize", () => placeGrips($("columns")));

  render();
}

document.addEventListener("DOMContentLoaded", init);
