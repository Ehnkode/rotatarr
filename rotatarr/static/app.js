"use strict";

let lang = "en";
let settings = {};
let libraries = [];

const $ = (sel) => document.querySelector(sel);
const t = (key) => (I18N[lang] && I18N[lang][key]) || I18N.en[key] || key;

function applyTexts() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
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
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

function notify(text, isError = false) {
  const el = $("#notice");
  el.textContent = isError ? `${t("error")}: ${text}` : text;
  el.className = isError ? "error" : "ok";
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { el.textContent = ""; el.className = ""; }, 6000);
}

function lines(text) { return text.split("\n").map((s) => s.trim()).filter(Boolean); }

// --- tabs ----------------------------------------------------------------------

function showTab(name) {
  document.querySelectorAll("main > section").forEach((s) => { s.hidden = s.id !== `tab-${name}`; });
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  location.hash = name;
  if (name === "status") refreshStatus();
}

// --- status --------------------------------------------------------------------

function formatNext(ts) {
  if (!ts) return t("manual_only");
  return new Date(ts * 1000).toLocaleString(lang);
}

async function refreshStatus() {
  $("#not-connected").hidden = settings.connected;
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
  renderHistory(await api("/api/history").catch(() => []));
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
      + (h.dry_run ? " · test" : "") + (h.seconds !== undefined ? ` · ${h.seconds}s` : "");
    div.appendChild(head);
    h.lines.forEach((l) => { const p = document.createElement("div"); p.textContent = l; div.appendChild(p); });
    box.appendChild(div);
  });
}

async function renderRows() {
  const select = $("#rows-library");
  if (!select.value) return;
  const list = $("#rows");
  list.innerHTML = "";
  const rows = await api(`/api/libraries/${select.value}/rows`).catch(() => []);
  rows.filter((r) => r.recommended || r.home || r.shared).forEach((r) => {
    const li = document.createElement("li");
    li.textContent = r.title;
    [["recommended", "badge_rec"], ["home", "badge_home"], ["shared", "badge_shared"]].forEach(([flag, key]) => {
      if (!r[flag]) return;
      const b = document.createElement("span");
      b.className = "badge";
      b.textContent = t(key);
      li.appendChild(b);
    });
    if (!r.collection) li.classList.add("builtin");
    list.appendChild(li);
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
  if (!settings.connected) return;
  try { libraries = await api("/api/libraries"); } catch (e) { notify(e.message, true); return; }
  for (const select of [$("#library-select"), $("#rows-library")]) {
    const current = select.value;
    select.innerHTML = "";
    libraries.forEach((l) => select.add(new Option(l.title, l.key)));
    if (current) select.value = current;
  }
  fillLibraryForm();
}

async function fillLibraryForm() {
  const lib = libraries.find((l) => l.key === $("#library-select").value);
  const form = $("#library-form");
  form.hidden = !lib;
  if (!lib) return;
  const s = lib.settings;
  for (const name of ["recommended", "home", "shared", "min_items"]) form.elements[name].value = s[name];
  for (const name of ["enabled", "shuffle_order", "shuffle_items"]) form.elements[name].checked = s[name];
  form.elements.exclude.value = s.exclude.join("\n");
  form.elements.always_visible.value = s.always_visible.join("\n");
  form.elements.quotas.value = s.quotas.map((q) => `${q.match} = ${q.max}`).join("\n");

  const collections = await api(`/api/libraries/${lib.key}/collections`).catch(() => []);
  $("#collection-count").textContent = collections.length;
  const ul = $("#collections");
  ul.innerHTML = "";
  collections.forEach((c) => {
    const li = document.createElement("li");
    li.textContent = `${c.title} (${c.items})` + (c.smart ? ` · ${t("smart")}` : "");
    ul.appendChild(li);
  });
}

async function saveLibrary(ev) {
  ev.preventDefault();
  const form = ev.target;
  const key = $("#library-select").value;
  const quotas = lines(form.elements.quotas.value).map((l) => {
    const [match, max] = l.split("=");
    return { match: (match || "").trim(), max: parseInt(max, 10) || 0 };
  }).filter((q) => q.match);
  const body = {
    enabled: form.elements.enabled.checked,
    recommended: +form.elements.recommended.value,
    home: +form.elements.home.value,
    shared: +form.elements.shared.value,
    min_items: +form.elements.min_items.value,
    exclude: lines(form.elements.exclude.value),
    always_visible: lines(form.elements.always_visible.value),
    quotas,
    shuffle_order: form.elements.shuffle_order.checked,
    shuffle_items: form.elements.shuffle_items.checked,
  };
  try {
    const saved = await api(`/api/libraries/${key}`, { method: "PUT", body });
    libraries.find((l) => l.key === key).settings = saved;
    notify(t("saved"));
  } catch (e) { notify(e.message, true); }
}

// --- settings ------------------------------------------------------------------

function fillSettingsForm() {
  const form = $("#settings-form");
  for (const name of ["rotation_interval_minutes", "shuffle_interval_minutes", "items_to_front"]) {
    form.elements[name].value = settings[name];
  }
  form.elements.pinned_rows.value = settings.pinned_rows.join("\n");
  form.elements.dry_run.checked = settings.dry_run;
  $("#connected-card").hidden = !settings.connected;
  $("#connected-url").textContent = settings.plex_url;
}

async function saveSettings(ev) {
  ev.preventDefault();
  const form = ev.target;
  try {
    settings = await api("/api/settings", { method: "PUT", body: {
      rotation_interval_minutes: +form.elements.rotation_interval_minutes.value,
      shuffle_interval_minutes: +form.elements.shuffle_interval_minutes.value,
      items_to_front: +form.elements.items_to_front.value,
      pinned_rows: lines(form.elements.pinned_rows.value),
      dry_run: form.elements.dry_run.checked,
    } });
    notify(t("saved"));
  } catch (e) { notify(e.message, true); }
}

async function setLanguage(value) {
  lang = value;
  applyTexts();
  settings = await api("/api/settings", { method: "PUT", body: { language: lang } }).catch(() => settings);
  refreshStatus();
}

// --- connection ----------------------------------------------------------------

async function afterConnect(result) {
  notify(`${t("connected_to")} ${result.server}`);
  settings = await api("/api/settings");
  fillSettingsForm();
  await loadLibraries();
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
  refreshStatus();
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
  $("#library-select").addEventListener("change", fillLibraryForm);
  $("#rows-library").addEventListener("change", renderRows);
  $("#library-form").addEventListener("submit", saveLibrary);
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#manual-form").addEventListener("submit", connectManual);
  $("#plex-login").addEventListener("click", plexLogin);
  $("#disconnect").addEventListener("click", disconnect);

  await loadLibraries();
  const start = location.hash.slice(1);
  showTab(["status", "libraries", "settings", "connection"].includes(start) ? start
    : (settings.connected ? "status" : "connection"));
  setInterval(() => { if (!$("#tab-status").hidden) refreshStatus(); }, 15000);
}

init();
