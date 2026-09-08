"use strict";
/* Layout-Editor.
 *
 * Zeichnet die Spalten des aktiven Profils als beschriftete Kaesten in echter
 * Proportion, laesst sie verschieben und skalieren und schickt das Ergebnis
 * per postMessage an Python zurueck.
 *
 * Bewusst kein Framework und kein Build-Schritt: die Seite wird von
 * editor/__init__.py in eine Datei eingebettet und muss nur hier laufen.
 */

const P = window.__PAYLOAD__ || {};
const FLEX = P.flex || "flex";
const STAGE = P.stage || { width: 2560, height: 720, connector: "" };
const CATALOGUE = P.catalogue || [];

/* Arbeitskopie. Das Original bleibt fuer "Verwerfen" liegen. */
const ORIGINAL = JSON.stringify(P.layout || {});
let layout = JSON.parse(ORIGINAL);
let selected = null;          // {kind:"module",col,mod} | {kind:"column",col}
let dirty = false;

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

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

function specFor(type) {
  return CATALOGUE.find((c) => c.type === type) || null;
}

function labelFor(type) {
  const spec = specFor(type);
  return spec ? spec.label : type;
}

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

/* Summe der festen Spalten. Passt sie nicht auf den Monitor, bleibt fuer die
 * Flex-Spalte nichts uebrig — das kann der Editor sehen, das Dashboard nicht
 * sinnvoll melden. */
function fixedTotal() {
  return columns().reduce((sum, c) => sum + (c.width === FLEX ? 0 : c.width), 0);
}

function flexWidth() {
  return Math.max(0, STAGE.width - fixedTotal());
}

function renderedWidth(col) {
  return col.width === FLEX ? flexWidth() : col.width;
}

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
    warn.textContent =
      `Feste Spalten belegen ${fixedTotal()} px von ${STAGE.width} px — ` +
      `fuer die Flex-Spalte bleibt nichts uebrig.`;
  } else if (left < 120) {
    warn.hidden = false;
    warn.textContent = `Nur noch ${left} px fuer die Flex-Spalte.`;
  } else {
    warn.hidden = true;
  }
}

function renderStage() {
  const stage = $("stage");
  stage.innerHTML = "";
  stage.style.aspectRatio = `${STAGE.width} / ${STAGE.height}`;

  const cols = columns();
  cols.forEach((col, ci) => {
    if (ci > 0) stage.appendChild(makeGrip(ci - 1));
    stage.appendChild(makeColumn(col, ci));
  });
}

function makeColumn(col, ci) {
  const node = el("div", "column");
  node.dataset.col = String(ci);

  /* Breite als Anteil der Monitorbreite — daher die echte Proportion. */
  const share = renderedWidth(col) / STAGE.width;
  node.style.flex = `0 0 ${(share * 100).toFixed(3)}%`;

  const head = el("div", "column-head");
  const width = el("button", "column-width" + (col.width === FLEX ? " is-flex" : ""));
  width.textContent = col.width === FLEX ? `flex · ${flexWidth()} px` : `${col.width} px`;
  width.title = col.width === FLEX
    ? "Nimmt den Rest. Klicken, um eine feste Breite zu setzen."
    : "Klicken fuer eine exakte Breite, oder diese Spalte auf flex setzen.";
  width.addEventListener("click", () => selectColumn(ci));
  head.appendChild(width);
  node.appendChild(head);

  if (!col.modules.length) {
    node.appendChild(el("div", "column-empty", "leer — wird verworfen"));
  }
  col.modules.forEach((mod, mi) => node.appendChild(makeModule(mod, ci, mi)));

  return node;
}

function makeModule(mod, ci, mi) {
  const node = el("div", "module");
  node.dataset.col = String(ci);
  node.dataset.mod = String(mi);
  if (selected && selected.kind === "module"
      && selected.col === ci && selected.mod === mi) {
    node.classList.add("selected");
  }

  node.appendChild(el("div", "module-label", labelFor(mod.type).toUpperCase()));

  const sub = describeConfig(mod);
  if (sub) node.appendChild(el("div", "module-sub", sub));

  node.addEventListener("pointerdown", (ev) => startDrag(ev, ci, mi));
  return node;
}

/* Eine Zeile Kontext im Kasten — bei mehreren Web-Panels ist sonst nicht zu
 * sehen, welches welches ist. */
function describeConfig(mod) {
  const cfg = mod.config || {};
  if (mod.type === "web") {
    if (!cfg.url) return "eingebettetes Widget";
    try { return new URL(cfg.url).hostname; } catch { return cfg.url.slice(0, 30); }
  }
  if (Array.isArray(cfg.metrics)) return cfg.metrics.join(" · ");
  return "";
}

function makeGrip(leftIndex) {
  const grip = el("div", "grip");
  grip.dataset.left = String(leftIndex);
  grip.addEventListener("pointerdown", (ev) => startResize(ev, leftIndex));
  return grip;
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
    setStatus("Breite muss mindestens 80 px sein", "bad");
    return false;
  }
  if (col.width === FLEX) {
    const next = cols.findIndex((c, i) => i !== ci);
    if (next === -1) {
      setStatus("Eine Spalte muss flex bleiben", "bad");
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

function startResize(ev, leftIndex) {
  ev.preventDefault();
  const stage = $("stage");
  const cols = columns();
  const left = cols[leftIndex];
  const right = cols[leftIndex + 1];
  if (!left || !right) return;

  const pxPerScreenPx = STAGE.width / stage.getBoundingClientRect().width;
  const startX = ev.clientX;
  const startLeft = renderedWidth(left);
  const startRight = renderedWidth(right);
  const grip = ev.currentTarget;
  grip.classList.add("active");
  grip.setPointerCapture(ev.pointerId);

  /* Die Flex-Spalte hat keine eigene Zahl — sie ergibt sich aus dem Rest.
   * Beim Ziehen wird deshalb immer die *feste* der beiden veraendert; sind
   * beide fest, wandert die Breite von einer zur anderen. */
  function onMove(e) {
    const delta = Math.round((e.clientX - startX) * pxPerScreenPx);
    if (left.width !== FLEX && right.width !== FLEX) {
      const l = startLeft + delta, r = startRight - delta;
      if (l < 80 || r < 80) return;
      left.width = l;
      right.width = r;
    } else if (left.width !== FLEX) {
      const l = startLeft + delta;
      if (l < 80 || STAGE.width - (fixedTotal() - left.width + l) < 80) return;
      left.width = l;
    } else {
      const r = startRight - delta;
      if (r < 80 || STAGE.width - (fixedTotal() - right.width + r) < 80) return;
      right.width = r;
    }
    markDirty();
    render();
  }

  function onUp() {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
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
    document.querySelectorAll(".column.drop-target")
      .forEach((n) => n.classList.remove("drop-target"));
    marker = null;
  }

  function onMove(e) {
    if (!moved && Math.abs(e.clientY - ev.clientY) < 3
              && Math.abs(e.clientX - ev.clientX) < 3) return;
    if (!moved) {
      moved = true;
      source.classList.add("dragging");
    }

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
  /* Im selben Spalten-Array verschiebt das Entfernen alles danach um eins. */
  if (fromCol === toCol && fromMod < toIndex) toIndex--;
  cols[toCol].modules.splice(toIndex, 0, mod);
  selected = { kind: "module", col: toCol,
                mod: Math.min(toIndex, cols[toCol].modules.length - 1) };
}

/* ---------- Auswahl und Inspektor ---------- */

function select(ci, mi) {
  selected = { kind: "module", col: ci, mod: mi };
  renderStage();
  renderInspector();
}

function renderInspector() {
  const box = $("inspector");
  box.innerHTML = "";

  if (!selected) {
    box.appendChild(el("p", "muted",
      "Nichts ausgewaehlt. Modul anklicken, oder die Breite ueber der Spalte."));
    return;
  }
  if (selected.kind === "column") return renderColumnInspector(box);
  return renderModuleInspector(box);
}

function renderColumnInspector(box) {
  const ci = selected.col;
  const col = columns()[ci];
  if (!col) { selected = null; return renderInspector(); }

  const title = el("div", "row");
  title.appendChild(el("label", null, "Spalte"));
  title.appendChild(el("span", null, `${ci + 1} von ${columns().length}`));
  box.appendChild(title);

  const row = el("div", "row");
  row.appendChild(el("label", null, "Breite"));
  const input = el("input");
  input.type = "number";
  input.min = "80";
  input.step = "10";
  input.value = String(renderedWidth(col));
  input.disabled = col.width === FLEX;
  /* change statt input: bei jedem Tastendruck neu zu zeichnen wuerde den
   * Fokus aus dem Feld werfen, weil render() die Buehne neu aufbaut. */
  input.addEventListener("change", () => setColumnWidth(ci, parseInt(input.value, 10)));
  row.appendChild(input);
  row.appendChild(el("span", "muted", "px"));
  box.appendChild(row);

  const flexRow = el("div", "row");
  flexRow.appendChild(el("label", null, "Flex"));
  const flexBtn = el("button", "ghost",
    col.width === FLEX ? "nimmt den Rest" : "diese Spalte flex machen");
  flexBtn.disabled = col.width === FLEX;
  flexBtn.title = "Genau eine Spalte fuellt den verbleibenden Platz.";
  flexBtn.addEventListener("click", () => {
    setFlexColumn(ci);
    markDirty();
    render();
  });
  flexRow.appendChild(flexBtn);
  box.appendChild(flexRow);

  box.appendChild(el("p", "muted",
    col.width === FLEX
      ? "Diese Spalte bekommt, was die festen uebrig lassen."
      : "Feste Breite in Pixeln auf dem Zielmonitor."));
}

function renderModuleInspector(box) {
  const col = columns()[selected.col];
  const mod = col && col.modules[selected.mod];
  if (!mod) { selected = null; return renderInspector(); }

  const title = el("div", "row");
  title.appendChild(el("label", null, "Modul"));
  title.appendChild(el("span", null, labelFor(mod.type)));
  box.appendChild(title);

  /* Die volle Einstellungsmaske aus dem schema kommt in Schritt 4. Bis dahin
   * nur die URL, weil ohne sie mehrere Web-Panels nicht zu unterscheiden
   * waeren. */
  if (mod.type === "web") {
    const row = el("div", "row");
    row.appendChild(el("label", null, "URL"));
    const input = el("input");
    input.type = "text";
    input.value = (mod.config && mod.config.url) || "";
    input.placeholder = "leer = eingebettetes Widget";
    input.addEventListener("change", () => {
      mod.config = mod.config || {};
      mod.config.url = input.value.trim();
      markDirty();
      renderStage();
    });
    row.appendChild(input);
    box.appendChild(row);
  }

  const remove = el("button", "ghost danger", "Modul entfernen");
  remove.addEventListener("click", () => {
    col.modules.splice(selected.mod, 1);
    selected = null;
    markDirty();
    render();
  });
  box.appendChild(remove);
}

/* ---------- Katalog ---------- */

function renderCatalogue() {
  const box = $("catalogue");
  box.innerHTML = "";
  for (const spec of CATALOGUE) {
    const b = el("button", "ghost", spec.label);
    b.title = spec.singleton
      ? "Kann nur einmal vorkommen"
      : "In die ausgewaehlte Spalte einfuegen";
    b.addEventListener("click", () => addModule(spec));
    box.appendChild(b);
  }
}

function addModule(spec) {
  const cols = columns();
  if (spec.singleton && cols.some((c) => c.modules.some((m) => m.type === spec.type))) {
    setStatus(`${spec.label} kann nur einmal vorkommen`, "bad");
    return;
  }
  const ci = selected ? selected.col : cols.length - 1;
  cols[ci].modules.push({ type: spec.type, config: {} });
  selected = { kind: "module", col: ci, mod: cols[ci].modules.length - 1 };
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
  return base || "profil";
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
    if (commit) {
      const name = input.value.trim();
      if (name) onCommit(name);
    }
  }
  function onKey(e) {
    if (e.key === "Enter") done(true);
    else if (e.key === "Escape") done(false);
  }
  function onBlur() { done(false); }

  input.addEventListener("keydown", onKey);
  input.addEventListener("blur", onBlur);
}

function newProfile() {
  askName("Neu", (name) => {
    const id = uniqueId(slugify(name));
    /* Vom aktuellen Profil kopieren statt leer beginnen: ein Profil ohne
     * Spalten waere ungueltig, und meist will man eine Variante. */
    layout.profiles[id] = JSON.parse(JSON.stringify(profile()));
    layout.profiles[id].label = name;
    layout.active_profile = id;
    selected = null;
    markDirty();
    render();
  });
}

function renameProfile() {
  const prof = profile();
  askName(prof.label || layout.active_profile, (name) => {
    prof.label = name;
    markDirty();
    render();
  });
}

/* Zweistufig statt confirm(): der Knopf fragt sich selbst nach und faellt
 * nach vier Sekunden zurueck. */
let deleteArmed = false;
let deleteTimer = null;

function resetDelete() {
  deleteArmed = false;
  if (deleteTimer) { clearTimeout(deleteTimer); deleteTimer = null; }
  const btn = $("profile-delete");
  btn.textContent = "\u00d7";
  btn.classList.remove("primary");
}

function deleteProfile() {
  if (Object.keys(layout.profiles).length < 2) return;

  if (!deleteArmed) {
    deleteArmed = true;
    const btn = $("profile-delete");
    btn.textContent = "wirklich?";
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

/* ---------- Speichern ---------- */

/* Leere Spalten fliegen raus — layout_store lehnt sie ab, und eine Spalte ohne
 * Module ist ohnehin nur ein Rest vom Verschieben. */
function cleaned() {
  const copy = JSON.parse(JSON.stringify(layout));
  for (const prof of Object.values(copy.profiles)) {
    prof.columns = prof.columns.filter((c) => c.modules.length > 0);
  }
  return copy;
}

function save() {
  const data = cleaned();
  const prof = data.profiles[data.active_profile];

  if (!prof.columns.length) {
    setStatus("Layout hat keine Spalten", "bad");
    return;
  }
  const flex = prof.columns.filter((c) => c.width === FLEX).length;
  if (flex !== 1) {
    setStatus(`Genau eine Spalte muss flex sein (aktuell ${flex})`, "bad");
    return;
  }

  if (!window.webkit || !window.webkit.messageHandlers ||
      !window.webkit.messageHandlers.bridge) {
    setStatus("Keine Verbindung zum Dashboard", "bad");
    return;
  }
  window.webkit.messageHandlers.bridge.postMessage(
    JSON.stringify({ action: "save", layout: data })
  );
  setStatus("Speichere …", "");
}

/* Von Python nach dem Schreiben aufgerufen. */
window.__saved = function (ok, message) {
  setStatus(message, ok ? "ok" : "bad");
  if (ok) {
    dirty = false;
    $("save").disabled = true;
    $("revert").disabled = true;
  }
};

function revert() {
  layout = JSON.parse(ORIGINAL);
  selected = null;
  dirty = false;
  $("save").disabled = true;
  $("revert").disabled = true;
  setStatus("Verworfen", "");
  render();
}

/* ---------- Start ---------- */

function init() {
  applyPalette();

  if (!layout || !layout.profiles || !layout.active_profile) {
    document.body.innerHTML =
      "<p style='padding:20px'>Kein Layout geladen — layout.json fehlt oder ist ungueltig.</p>";
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

  /* Klick ins Leere hebt die Auswahl auf. */
  $("stage").addEventListener("pointerdown", (e) => {
    if (e.target.id === "stage" || e.target.classList.contains("column")
        || e.target.classList.contains("column-empty")) {
      selected = null;
      renderStage();
      renderInspector();
    }
  });

  renderCatalogue();
  render();
}

document.addEventListener("DOMContentLoaded", init);
