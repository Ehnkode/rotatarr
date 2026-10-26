"use strict";

let lang = "en";
let settings = {};
let libraries = [];

const $ = (sel) => document.querySelector(sel);
const t = (key) => (I18N[lang] && I18N[lang][key]) || I18N.en[key] || key;

function applyTexts() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
  document.querySelectorAll("[data-t-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.tPlaceholder); });
  $("#lang").value = lang;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* not json */ }
    // Validation errors come as a list; show their messages, not raw JSON.
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

function notify(text, isError = false) {
  const el = $("#notice");
  el.textContent = isError ? `${t("error")}: ${text}` : text;
  el.className = isError ? "error" : "ok";
  clearTimeout(notify.timer);
  // Errors stay until the next message, so they are not missed.
  if (!isError) notify.timer = setTimeout(() => { el.textContent = ""; el.className = ""; }, 6000);
}

function format(template, values) {
  return template.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? "");
}

// --- unsaved changes -------------------------------------------------------------

const dirty = new Set();

function confirmLeave() {
  if (!dirty.size) return true;
  if (!confirm(t("unsaved"))) return false;
  dirty.clear();
  return true;
}

function markSaved(form) {
  dirty.delete(form.id);
  const button = form.querySelector("button[type=submit]");
  button.textContent = t("saved_short");
  clearTimeout(button.resetTimer);
  button.resetTimer = setTimeout(() => { button.textContent = t("save"); }, 2500);
}

function lines(text) { return text.split("\n").map((s) => s.trim()).filter(Boolean); }

// Same rule as the server: a line written as /.../ is a regular expression.
function matchesWord(title, word) {
  if (word.length > 2 && word.startsWith("/") && word.endsWith("/")) {
    try { return new RegExp(word.slice(1, -1), "i").test(title); } catch (_) { return false; }
  }
  return title.toLowerCase().includes(word.toLowerCase());
}

// --- tabs ----------------------------------------------------------------------

function showTab(name) {
  const current = document.querySelector("main > section:not([hidden])");
  if (current && current.id !== `tab-${name}` && !confirmLeave()) return;
  document.querySelectorAll("main > section").forEach((s) => { s.hidden = s.id !== `tab-${name}`; });
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  location.hash = name;
  document.querySelectorAll(".not-connected").forEach((el) => { el.hidden = settings.connected; });
  $("#library-picker").hidden = !settings.connected;
  if (name === "status") refreshStatus();
}

// --- status --------------------------------------------------------------------

function formatNext(ts) {
  if (!ts) return t("manual_only");
  return new Date(ts * 1000).toLocaleString(lang);
}

async function refreshStatus() {
  $("#dry-run-banner").hidden = !settings.dry_run;
  try {
    const state = await api("/api/state");
    $("#next-rotate").textContent = formatNext(state.next_run.rotate);
    $("#next-shuffle").textContent = formatNext(state.next_run.shuffle);
    document.querySelectorAll("[data-run]").forEach((b) => {
      const busy = state.running.includes(b.dataset.run);
      b.disabled = busy || !settings.connected;
      b.textContent = busy ? t("running") : t(`run_${b.dataset.run}`);
    });
  } catch (e) { /* server restarting */ }
  const history = await api("/api/history").catch(() => []);
  renderHistory(history);
  renderOverview(history);
  if (settings.connected) await renderRows();
}

function renderHistory(history) {
  const box = $("#history");
  box.innerHTML = "";
  if (!history.length) { box.textContent = t("no_runs"); return; }
  history.slice(0, 15).forEach((h) => {
    const div = document.createElement("div");
    div.className = `run ${h.ok ? "" : "failed"}`;
    const head = document.createElement("div");
    head.className = "run-head";
    head.textContent = `${new Date(h.started).toLocaleString(lang)} · ${t(`kind_${h.kind}`)}`
      + (h.dry_run ? ` · ${t("test")}` : "") + (h.seconds !== undefined ? ` · ${h.seconds}s` : "");
    div.appendChild(head);
    const texts = h.results && h.results.length && h.lines.length === h.results.length
      ? h.results.map((r) => (r.error ? `${r.library}: ${r.error}` : format(t(`log_${h.kind}`), r)))
      : h.lines;
    texts.forEach((l) => { const p = document.createElement("div"); p.textContent = l; div.appendChild(p); });
    box.appendChild(div);
  });
}

async function renderRows() {
  const select = $("#rows-library");
  if (!select.value) return;
  const rows = await api(`/api/libraries/${select.value}/rows`).catch(() => []);
  const list = $("#rows");
  list.innerHTML = "";
  rows.filter((r) => r.recommended || r.home || r.shared).forEach((r) => {
    const li = document.createElement("li");
    if (!r.collection) li.classList.add("builtin");
    const poster = document.createElement(r.thumb ? "img" : "span");
    poster.className = "poster";
    if (r.thumb) {
      poster.src = `/api/thumb?path=${encodeURIComponent(r.thumb)}`;
      poster.loading = "lazy";
      poster.alt = "";
    }
    const text = document.createElement("span");
    text.className = "row-text";
    const title = document.createElement("span");
    title.textContent = r.title;
    const badges = document.createElement("span");
    [["recommended", "badge_rec"], ["home", "badge_home"], ["shared", "badge_shared"]].forEach(([flag, key]) => {
      if (!r[flag]) return;
      const b = document.createElement("span");
      b.className = "badge";
      b.textContent = t(key);
      badges.appendChild(b);
    });
    text.append(title, badges);
    li.append(poster, text);
    list.appendChild(li);
  });
}

async function renderOverview(history) {
  const box = $("#overview");
  if (!settings.connected) { box.innerHTML = ""; return; }
  const libs = await api("/api/overview").catch(() => null);
  if (!libs) return;
  box.innerHTML = "";
  libs.forEach((l) => {
    const tile = document.createElement("div");
    tile.className = `tile ${l.enabled ? "" : "off"}`;
    const head = document.createElement("div");
    head.className = "tile-head";
    const name = document.createElement("strong");
    name.textContent = l.title;
    const state = document.createElement("span");
    state.className = `pill ${l.enabled ? "on" : ""}`;
    state.textContent = t(l.enabled ? "rotation_on" : "rotation_off");
    head.append(name, state);
    const counts = document.createElement("div");
    counts.className = "tile-counts";
    [["recommended", "badge_rec"], ["home", "badge_home"], ["shared", "badge_shared"]].forEach(([k, label]) => {
      const c = document.createElement("div");
      const n = document.createElement("b");
      n.textContent = l[k];
      const lab = document.createElement("small");
      lab.textContent = t(label);
      c.append(n, lab);
      counts.appendChild(c);
    });
    const last = history.find((h) => h.kind === "rotate" && (h.results || []).some((r) => r.library === l.title));
    const foot = document.createElement("div");
    foot.className = "muted tile-foot";
    if (last) {
      const r = last.results.find((x) => x.library === l.title);
      foot.textContent = `${t("last_run")}: ${new Date(last.started).toLocaleString(lang)}` + (r.error ? ` · ${t("failed")}` : "");
      if (r.error) foot.classList.add("error-text");
    } else {
      foot.textContent = `${t("last_run")}: –`;
    }
    tile.append(head, counts, foot);
    tile.onclick = () => {
      showTab("libraries");
      if ($("#tab-libraries").hidden) return;
      $("#library-select").value = l.key;
      fillLibraryForm();
    };
    box.appendChild(tile);
  });
}

async function runNow(kind) {
  try {
    await api(`/api/run/${kind}`, { method: "POST" });
    notify(t("started"));
    setTimeout(refreshStatus, 500);
  } catch (e) { notify(e.message, true); }
}

// --- libraries -----------------------------------------------------------------

async function loadLibraries() {
  if (!settings.connected) { libraries = []; fillLibraryForm(); return; }
  try { libraries = await api("/api/libraries"); } catch (e) { notify(e.message, true); return; }
  for (const select of [$("#library-select"), $("#rows-library")]) {
    const current = select.value;
    select.innerHTML = "";
    libraries.forEach((l) => select.add(new Option(l.title, l.key)));
    if (current) select.value = current;
  }
  fillLibraryForm();
}

let collections = [];
const collectionModes = new Map(); // lower-case title -> "random" | "always" | "never" | "seasonal"
const seasons = new Map(); // lower-case title -> { start: "MM-DD", end: "MM-DD" }

async function fillLibraryForm() {
  const lib = libraries.find((l) => l.key === $("#library-select").value);
  const form = $("#library-form");
  form.hidden = !lib;
  if (!lib) return;
  dirty.delete("library-form");
  const s = lib.settings;
  for (const name of ["recommended", "home", "shared", "min_items"]) form.elements[name].value = s[name];
  for (const name of ["enabled", "shuffle_order", "shuffle_items"]) form.elements[name].checked = s[name];
  form.elements.exclude.value = s.exclude.join("\n");
  $("#quota-rows").innerHTML = "";
  s.quotas.forEach(addQuotaRow);

  collectionModes.clear();
  s.always_visible.forEach((title) => collectionModes.set(title.toLowerCase(), "always"));
  s.never.forEach((title) => collectionModes.set(title.toLowerCase(), "never"));
  seasons.clear();
  s.seasonal.forEach((x) => {
    collectionModes.set(x.title.toLowerCase(), "seasonal");
    seasons.set(x.title.toLowerCase(), { start: x.start, end: x.end });
  });
  form.elements.automatic_max.value = s.automatic_max ?? "";
  form.elements.automatic_max_home.value = s.automatic_max_home ?? "";
  collections = await api(`/api/libraries/${lib.key}/collections`).catch(() => []);
  renderCollections();
}

function collectionStatus(c, form) {
  const mode = collectionModes.get(c.title.toLowerCase()) || "random";
  if (mode !== "random") return mode;
  if (c.items < (+form.elements.min_items.value || 0)) return "too_small";
  if (lines(form.elements.exclude.value).some((w) => matchesWord(c.title, w))) return "excluded";
  return "random";
}

function renderCollections() {
  const form = $("#library-form");
  const filter = $("#collection-filter").value.trim().toLowerCase();
  const body = $("#collections");
  body.innerHTML = "";
  const counts = { random: 0, always: 0, never: 0, seasonal: 0, too_small: 0, excluded: 0 };
  collections.forEach((c) => {
    const status = collectionStatus(c, form);
    counts[status] += 1;
    if (filter && !c.title.toLowerCase().includes(filter)) return;
    const tr = document.createElement("tr");
    if (status === "too_small" || status === "excluded" || status === "never") tr.className = "out";
    if (status === "always" || status === "seasonal") tr.className = "always";
    const name = document.createElement("td");
    const title = document.createElement("span");
    title.className = "coll-title";
    title.textContent = c.title;
    const info = document.createElement("small");
    info.className = "muted-cell";
    info.textContent = [c.items, c.smart ? t("smart") : "", c.automatic ? t("automatic") : "", ["too_small", "excluded"].includes(status) ? t(status) : ""]
      .filter((x) => x !== "").join(" · ");
    name.append(title, " ", info);
    if (status === "seasonal") name.appendChild(seasonEditor(c.title.toLowerCase()));
    const modeCell = document.createElement("td");
    const select = document.createElement("select");
    ["random", "always", "seasonal", "never"].forEach((m) => select.add(new Option(t(`mode_${m}`), m)));
    select.value = collectionModes.get(c.title.toLowerCase()) || "random";
    select.onchange = () => {
      const key = c.title.toLowerCase();
      if (select.value === "random") collectionModes.delete(key);
      else collectionModes.set(key, select.value);
      if (select.value === "seasonal" && !seasons.has(key)) seasons.set(key, { start: "12-01", end: "12-31" });
      renderCollections();
    };
    modeCell.appendChild(select);
    tr.append(name, modeCell);
    body.appendChild(tr);
  });
  const automatic = collections.filter((c) => c.automatic).length;
  $("#automatic-field").hidden = automatic === 0;
  $("#automatic-hint").textContent = format(t("automatic_hint"), { count: automatic });
  const pool = counts.random + counts.always + counts.seasonal;
  $("#pool-summary").textContent = `${format(t("pool_summary"), { pool, total: collections.length })} `
    + format(t("pool_details"), { small: counts.too_small, excluded: counts.excluded, never: counts.never });
}

function seasonEditor(key) {
  const season = seasons.get(key);
  const box = document.createElement("div");
  box.className = "season";
  const months = [...Array(12)].map((_, i) => new Date(2000, i, 1).toLocaleString(lang, { month: "short" }));
  const part = (field) => {
    const [month, day] = season[field].split("-").map(Number);
    const daySelect = document.createElement("select");
    for (let d = 1; d <= 31; d++) daySelect.add(new Option(d, d));
    daySelect.value = day;
    const monthSelect = document.createElement("select");
    months.forEach((name, i) => monthSelect.add(new Option(name, i + 1)));
    monthSelect.value = month;
    const update = () => {
      season[field] = `${String(monthSelect.value).padStart(2, "0")}-${String(daySelect.value).padStart(2, "0")}`;
    };
    daySelect.onchange = update;
    monthSelect.onchange = update;
    return [daySelect, monthSelect];
  };
  box.append(t("season_from"), " ", ...part("start"), " ", t("season_to"), " ", ...part("end"));
  return box;
}

function titlesWithMode(mode) {
  return collections.filter((c) => collectionModes.get(c.title.toLowerCase()) === mode).map((c) => c.title);
}

function addQuotaRow(quota = { match: "", max: 10 }) {
  const row = document.createElement("div");
  row.className = "quota-row";
  row.innerHTML = `<input class="quota-match" type="text"><input class="quota-max" type="number" min="0"><button type="button" class="quota-remove">×</button>`;
  row.querySelector(".quota-match").value = quota.match;
  row.querySelector(".quota-match").placeholder = t("quota_match");
  row.querySelector(".quota-match").setAttribute("aria-label", t("quota_match"));
  row.querySelector(".quota-max").value = quota.max;
  row.querySelector(".quota-max").setAttribute("aria-label", t("quota_max"));
  row.querySelector(".quota-remove").title = t("quota_remove");
  row.querySelector(".quota-remove").onclick = () => { row.remove(); dirty.add("library-form"); };
  $("#quota-rows").appendChild(row);
}

async function saveLibrary(ev) {
  ev.preventDefault();
  const form = ev.target;
  const key = $("#library-select").value;
  const quotas = [...document.querySelectorAll(".quota-row")].map((row) => ({
    match: row.querySelector(".quota-match").value.trim(),
    max: parseInt(row.querySelector(".quota-max").value, 10),
  })).filter((q) => q.match && q.max >= 0);
  const body = {
    enabled: form.elements.enabled.checked,
    recommended: +form.elements.recommended.value,
    home: +form.elements.home.value,
    shared: +form.elements.shared.value,
    min_items: +form.elements.min_items.value,
    exclude: lines(form.elements.exclude.value),
    always_visible: titlesWithMode("always"),
    never: titlesWithMode("never"),
    seasonal: titlesWithMode("seasonal").map((title) => ({ title, ...seasons.get(title.toLowerCase()) })),
    quotas,
    automatic_max: form.elements.automatic_max.value === "" ? null : +form.elements.automatic_max.value,
    automatic_max_home: form.elements.automatic_max_home.value === "" ? null : +form.elements.automatic_max_home.value,
    shuffle_order: form.elements.shuffle_order.checked,
    shuffle_items: form.elements.shuffle_items.checked,
  };
  try {
    const saved = await api(`/api/libraries/${key}`, { method: "PUT", body });
    libraries.find((l) => l.key === key).settings = saved;
    markSaved(form);
  } catch (e) { notify(e.message, true); }
}

// --- settings ------------------------------------------------------------------

function fillSettingsForm() {
  const form = $("#settings-form");
  for (const name of ["rotation_interval_minutes", "shuffle_interval_minutes", "items_to_front", "repeat_block_runs"]) {
    form.elements[name].value = settings[name];
  }
  if (!pinnedRows.length) pinnedRows = settings.pinned_rows.map((key) => ({ key, checked: true }));
  renderPinned();
  form.elements.dry_run.checked = settings.dry_run;
  form.elements.discord_webhook.value = settings.discord_webhook;
  form.elements.notify_success.checked = settings.notify_success;
  $("#connected-card").hidden = !settings.connected;
  $("#connected-url").textContent = settings.plex_url;
}

let pinnedRows = []; // [{key, title, checked}] in display order

async function loadBuiltinRows() {
  const builtin = settings.connected ? await api("/api/builtin-rows").catch(() => []) : [];
  const titles = new Map(builtin.map((r) => [r.key, r.title]));
  // Saved rows first, in their order; then the other built-in rows Plex knows.
  pinnedRows = settings.pinned_rows.map((key) => ({ key, title: titles.get(key), checked: true }));
  builtin.forEach((r) => {
    if (!pinnedRows.some((p) => p.key === r.key)) pinnedRows.push({ key: r.key, title: r.title, checked: false });
  });
  renderPinned();
}

function renderPinned() {
  const list = $("#pinned-list");
  list.innerHTML = "";
  pinnedRows.forEach((row, i) => {
    const li = document.createElement("li");
    const label = document.createElement("label");
    label.className = "check";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = row.checked;
    box.onchange = () => { row.checked = box.checked; };
    const text = document.createElement("span");
    text.textContent = row.title || row.key;
    if (!row.title) {
      const hint = document.createElement("small");
      hint.className = "muted";
      hint.textContent = ` (${t("builtin_unknown")})`;
      text.appendChild(hint);
    }
    label.append(box, text);
    const buttons = document.createElement("span");
    buttons.className = "order-buttons";
    [["↑", -1, "move_up"], ["↓", 1, "move_down"]].forEach(([symbol, dir, key]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = symbol;
      b.title = t(key);
      b.setAttribute("aria-label", t(key));
      b.disabled = i + dir < 0 || i + dir >= pinnedRows.length;
      b.onclick = () => {
        [pinnedRows[i], pinnedRows[i + dir]] = [pinnedRows[i + dir], pinnedRows[i]];
        dirty.add("settings-form");
        renderPinned();
      };
      buttons.appendChild(b);
    });
    li.append(label, buttons);
    list.appendChild(li);
  });
}

async function saveSettings(ev) {
  ev.preventDefault();
  const form = ev.target;
  try {
    settings = await api("/api/settings", { method: "PUT", body: {
      rotation_interval_minutes: +form.elements.rotation_interval_minutes.value,
      shuffle_interval_minutes: +form.elements.shuffle_interval_minutes.value,
      items_to_front: +form.elements.items_to_front.value,
      repeat_block_runs: +form.elements.repeat_block_runs.value,
      pinned_rows: pinnedRows.filter((r) => r.checked).map((r) => r.key),
      dry_run: form.elements.dry_run.checked,
      discord_webhook: form.elements.discord_webhook.value.trim(),
      notify_success: form.elements.notify_success.checked,
    } });
    markSaved(form);
  } catch (e) { notify(e.message === "invalid_webhook" ? t("discord_invalid") : e.message, true); }
}

async function setLanguage(value) {
  lang = value;
  applyTexts();
  settings = await api("/api/settings", { method: "PUT", body: { language: lang } }).catch(() => settings);
  renderPinned();
  if (collections.length) renderCollections();
  refreshStatus();
}

async function testNotification() {
  if (dirty.has("settings-form")) { notify(t("notify_save_first"), true); return; }
  try {
    await api("/api/notify/test", { method: "POST" });
    notify(t("notify_sent"));
  } catch (e) { notify(e.message === "no_webhook" ? t("notify_save_first") : e.message, true); }
}

async function resetPlex() {
  if (!confirm(t("reset_confirm"))) return;
  const button = $("#reset");
  button.disabled = true;
  try {
    const result = await api("/api/reset", { method: "POST" });
    notify(result.results.length ? t("reset_done") : t("reset_none"), !result.ok);
    await loadLibraries();
  } catch (e) { notify(e.message, true); }
  button.disabled = false;
}

// --- connection ----------------------------------------------------------------

async function afterConnect(result) {
  notify(`${t("connected_to")} ${result.server}`);
  settings = await api("/api/settings");
  fillSettingsForm();
  await loadLibraries();
  loadBuiltinRows();
  showTab("libraries");
}

async function plexLogin() {
  // Open the window right away, browsers block pop-ups opened after an await.
  const popup = window.open("", "plexauth", "width=600,height=700");
  try {
    const pin = await api("/api/plex/pin", { method: "POST" });
    popup.location = pin.auth_url;
    $("#plex-wait").hidden = false;
    for (let i = 0; i < 150; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const res = await api(`/api/plex/pin/${pin.id}`);
      if (res.done) {
        popup.close();
        $("#plex-wait").hidden = true;
        showServers(pin.id, res.servers);
        return;
      }
    }
  } catch (e) {
    popup.close();
    notify(e.message, true);
  }
  $("#plex-wait").hidden = true;
}

function showServers(pinId, servers) {
  const list = $("#server-list");
  list.innerHTML = "";
  servers.forEach((srv, index) => {
    srv.connections.forEach((c) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.textContent = `${srv.name} · ${c.uri}${c.local ? " (LAN)" : ""}`;
      b.onclick = async () => {
        try {
          await afterConnect(await api("/api/plex/server", { method: "POST", body: { pin_id: pinId, server: index, uri: c.uri } }));
        } catch (e) { notify(e.message, true); }
      };
      li.appendChild(b);
      list.appendChild(li);
    });
  });
  $("#servers").hidden = false;
}

async function connectManual(ev) {
  ev.preventDefault();
  const form = ev.target;
  try {
    await afterConnect(await api("/api/plex/manual", { method: "POST", body: {
      url: form.elements.url.value.trim(), token: form.elements.token.value.trim(),
    } }));
    form.reset();
  } catch (e) { notify(e.message, true); }
}

async function disconnect() {
  await api("/api/plex/disconnect", { method: "POST" });
  settings = await api("/api/settings");
  fillSettingsForm();
  await loadLibraries();
  showTab("connection");
}

// --- start ---------------------------------------------------------------------

async function init() {
  settings = await api("/api/settings");
  lang = settings.language in I18N ? settings.language : "en";
  applyTexts();
  fillSettingsForm();

  document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.goto)));
  document.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => runNow(b.dataset.run)));
  $("#lang").addEventListener("change", (e) => setLanguage(e.target.value));
  let shownLibrary = "";
  $("#library-select").addEventListener("focus", (e) => { shownLibrary = e.target.value; });
  $("#library-select").addEventListener("change", (e) => {
    if (!confirmLeave()) { e.target.value = shownLibrary; return; }
    shownLibrary = e.target.value;
    fillLibraryForm();
  });
  for (const id of ["library-form", "settings-form"]) {
    const form = document.getElementById(id);
    const track = (e) => { if (e.target.id !== "collection-filter") dirty.add(id); };
    form.addEventListener("input", track);
    form.addEventListener("change", track);
  }
  $("#add-quota").addEventListener("click", () => dirty.add("library-form"));
  window.addEventListener("beforeunload", (e) => { if (dirty.size) e.preventDefault(); });
  $("#rows-library").addEventListener("change", renderRows);
  $("#library-form").addEventListener("submit", saveLibrary);
  $("#add-quota").addEventListener("click", () => addQuotaRow());
  $("#collection-filter").addEventListener("input", renderCollections);
  for (const name of ["min_items", "exclude"]) {
    $("#library-form").elements[name].addEventListener("input", renderCollections);
  }
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#notify-test").addEventListener("click", testNotification);
  $("#manual-form").addEventListener("submit", connectManual);
  $("#plex-login").addEventListener("click", plexLogin);
  $("#disconnect").addEventListener("click", disconnect);
  $("#reset").addEventListener("click", resetPlex);

  await loadLibraries();
  loadBuiltinRows();
  const start = location.hash.slice(1);
  // Until Plex is connected, every other tab is empty.
  showTab(!settings.connected ? "connection"
    : ["status", "libraries", "settings", "connection"].includes(start) ? start : "status");
  setInterval(() => { if (!$("#tab-status").hidden) refreshStatus(); }, 15000);
}

init();
