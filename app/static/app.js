"use strict";

/* ---------- 공통 ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const dlg = $("#dlg");

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const dash = (v, suffix = "") => (v === null || v === undefined || v === "" ? "—" : `${v}${suffix}`);
const pct = (v) => (v === null || v === undefined ? "—" : `${Math.round(v)}%`);
function barClass(v) { return v >= 90 ? "bad" : v >= 75 ? "warn" : ""; }
function bar(v) {
  if (v === null || v === undefined) return '<div class="bar" aria-hidden="true"></div>';
  return `<div class="bar" aria-hidden="true"><i class="${barClass(v)}" style="width:${Math.min(100, Math.max(0, v))}%"></i></div>`;
}
function uptime(sec) {
  if (!sec && sec !== 0) return "—";
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600);
  return d ? `${d}일 ${h}시간` : `${h}시간 ${Math.floor((sec % 3600) / 60)}분`;
}

class ApiError extends Error {}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  if (res.status === 401 && !path.startsWith("/api/auth/")) { showLogin(); throw new ApiError("로그인이 필요합니다"); }
  let data = null;
  try { data = await res.json(); } catch (_) { /* 본문 없음 */ }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map((m) => m.msg).join(", ");
    throw new ApiError(msg || `요청 실패 (HTTP ${res.status})`);
  }
  return data;
}

let toastTimer;
function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (bad ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = "toast"; }, 3200);
}

function openDialog(html) {
  dlg.innerHTML = html;
  dlg.showModal();
  return new Promise((resolve) => {
    dlg.onclose = () => resolve(dlg.returnValue);
  });
}

async function confirmBox(title, message, okLabel = "실행", danger = true) {
  const r = await openDialog(`<form method="dialog" class="dlg">
    <h2>${esc(title)}</h2><p>${esc(message)}</p>
    <div class="dlg-foot"><button class="btn" value="cancel">취소</button>
    <button class="btn ${danger ? "danger" : "primary"}" value="ok">${esc(okLabel)}</button></div></form>`);
  return r === "ok";
}

function showText(title, text) {
  openDialog(`<form method="dialog" class="dlg"><h2>${esc(title)}</h2><pre>${esc(text || "(내용 없음)")}</pre>
    <div class="dlg-foot"><button class="btn" value="close">닫기</button></div></form>`);
}

/** fields: [{name,label,type,options,full,placeholder}] → 입력값 객체 또는 null */
async function formBox(title, fields, values = {}) {
  const body = fields.map((f) => {
    const v = values[f.name] ?? "";
    const cls = `field${f.full ? " full" : ""}`;
    if (f.type === "textarea") return `<label class="${cls}">${esc(f.label)}<textarea name="${f.name}" rows="3" placeholder="${esc(f.placeholder || "")}">${esc(v)}</textarea></label>`;
    if (f.type === "select") return `<label class="${cls}">${esc(f.label)}<select name="${f.name}">${f.options.map((o) => {
      const [val, text] = Array.isArray(o) ? o : [o, o];
      return `<option value="${esc(val)}" ${val === v ? "selected" : ""}>${esc(text)}</option>`;
    }).join("")}</select></label>`;
    if (f.type === "checks") {
      const set = new Set(v || []);
      const extra = [...set].filter((x) => !f.options.includes(x));
      return `<fieldset class="field full" style="border:none;margin:0;padding:0"><legend style="font-size:13px;color:var(--muted);padding-bottom:8px">${esc(f.label)}</legend>
        <div class="checks">${[...f.options, ...extra].map((o) => `<label><input type="checkbox" name="${f.name}" value="${esc(o)}" ${set.has(o) ? "checked" : ""}>${esc(o)}</label>`).join("")}</div></fieldset>`;
    }
    return `<label class="${cls}">${esc(f.label)}<input name="${f.name}" value="${esc(v)}" placeholder="${esc(f.placeholder || "")}" ${f.required ? "required" : ""}></label>`;
  }).join("");
  const r = await openDialog(`<form method="dialog" class="dlg" id="fbox"><h2>${esc(title)}</h2>
    <div class="form-grid">${body}</div>
    <div class="dlg-foot"><button class="btn" value="cancel" formnovalidate>취소</button><button class="btn primary" value="ok">저장</button></div></form>`);
  if (r !== "ok") return null;
  const form = $("#fbox", dlg);
  const out = {};
  for (const f of fields) {
    if (f.type === "checks") out[f.name] = [...form.querySelectorAll(`input[name="${f.name}"]:checked`)].map((i) => i.value);
    else out[f.name] = form.elements[f.name].value.trim();
  }
  return out;
}

/* ---------- 로그인 ---------- */
function showLogin() {
  $("#app").hidden = true;
  $("#setup").hidden = true;
  $("#login").hidden = false;
  $("#login-form").username.focus();
}

function showSetup() {
  $("#app").hidden = true;
  $("#login").hidden = true;
  $("#setup").hidden = false;
  $("#setup-form").password.focus();
}

function showApp() {
  $("#login").hidden = true;
  $("#setup").hidden = true;
  $("#app").hidden = false;
}

$("#setup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  $("#setup-err").textContent = "";
  if (f.password.value !== f.password2.value) { $("#setup-err").textContent = "비밀번호 확인이 일치하지 않습니다"; return; }
  try {
    await api("/api/auth/setup", { method: "POST", body: { username: f.username.value.trim(), password: f.password.value } });
    f.password.value = ""; f.password2.value = "";
    showApp(); checkUpdateQuietly();
    location.hash = "#/settings";
    route();
    toast("계정을 만들었습니다. 이제 허브와 서버를 연결하세요");
  } catch (err) {
    $("#setup-err").textContent = err.message;
  }
});

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  $("#login-err").textContent = "";
  try {
    await api("/api/auth/login", { method: "POST", body: { username: f.username.value, password: f.password.value } });
    f.password.value = "";
    showApp(); checkUpdateQuietly();
    route();
  } catch (err) {
    $("#login-err").textContent = err.message;
  }
});

$("#logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  showLogin();
});

/* ---------- 연동 공통: 종류 목록 · 상태 카드 ---------- */
let META = null;   // /api/integrations — 연동 종류와 입력 칸 선언
async function loadMeta() {
  if (!META) META = await api("/api/integrations");
  return META;
}
const metaOf = (type) => (META || []).find((m) => m.type === type);
const CATEGORY_LABEL = { infra: "인프라", smarthome: "스마트홈" };

function shortUrl(u) { return String(u || "").replace(/^https?:\/\//, "").replace(/\/$/, ""); }

/** 연동 종류 고르기 버튼들. asLink=true 면 #/settings?add= 로 이동하는 링크 */
function typeButtons(types, asLink) {
  return `<div class="picker">${types.map((m) => asLink
    ? `<a class="pick" href="#/settings?add=${encodeURIComponent(m.type)}"><b>+ ${esc(m.title)}</b><small>${esc(m.desc)}</small></a>`
    : `<button type="button" class="pick" data-add="${esc(m.type)}"><b>${esc(m.title)}</b><small>${esc(m.desc)}</small></button>`).join("")}</div>`;
}

function emptyStart(title, desc, types) {
  return `<section class="card onboarding"><div class="card-title"><h2>${esc(title)}</h2><small>${esc(desc)}</small></div>
    ${typeButtons(types, true)}</section>`;
}

/** 메뉴 화면의 "+ 연결 추가": 그 메뉴에 해당하는 종류를 골라 연결 설정으로 이동 */
function openTypePicker(category) {
  const types = META.filter((m) => !category || m.category === category || m.type === "web");
  dlg.innerHTML = `<form method="dialog" class="dlg"><h2>${category ? CATEGORY_LABEL[category] + " " : ""}연결 추가</h2>
    <p>추가할 시스템을 고르세요. 같은 종류도 여러 개 추가할 수 있어요.</p>${typeButtons(types, true)}
    <div class="dlg-foot"><button class="btn" value="cancel">닫기</button></div></form>`;
  dlg.showModal();
}

function actionButton(connId, a, small) {
  return `<button type="button" class="btn${small ? " sm" : ""}${a.danger ? " danger" : ""}" data-cact="${esc(a.id)}" data-conn="${esc(connId)}"
    data-params="${esc(JSON.stringify(a.params || {}))}" data-label="${esc(a.label)}" ${a.confirm ? `data-confirm="${esc(a.confirm)}"` : ""}>${esc(a.label)}</button>`;
}

/* ---------- 상태 카드 ---------- */
const expandedRows = new Set();   // "연결id:섹션번호" — "더 보기"로 펼친 목록

function rowHtml(connId, r) {
  const main = `<div class="row-main"><b>${esc(r.name)}</b>${r.note ? `<small>${esc(r.note)}</small>` : ""}</div>
    ${r.badge ? `<span class="pill ${esc(r.tone)}">${esc(r.badge)}</span>` : ""}`;
  if (!r.actions.length) return `<div class="row">${main}</div>`;
  // 작업 버튼은 줄을 눌렀을 때만 펼친다 (카드가 길어지지 않게)
  return `<details class="row xrow"><summary>${main}<span class="xrow-more" aria-hidden="true">⋯</span></summary>
    <div class="row-act">${r.actions.map((a) => actionButton(connId, a, true)).join("")}</div></details>`;
}

/** 상태 카드 안쪽. opts.rows: 목록 줄 수 (0 = 요약만, -1 = 전부) */
function statusCardInner(st, opts = { rows: -1 }, loading = false) {
  const m = metaOf(st.type) || { title: st.title || "" };
  const badge = !st.card && st.online === undefined ? '<span class="badge"><span class="dot"></span>확인 중</span>'
    : st.online ? '<span class="badge ok"><span class="dot ok"></span>온라인</span>'
    : `<span class="badge bad" title="${esc(st.error || "")}"><span class="dot bad"></span>오류</span>`;
  const head = `<div class="card-head"><div class="card-title"><span class="type-label">${esc(m.title)}</span><h2>${esc(st.name)}</h2>
      <small>${esc(st.card && st.card.summary ? st.card.summary : shortUrl(st.link))}</small></div>
    <span class="head-badges">${loading ? '<span class="spin" title="새로 고치는 중" aria-label="새로 고치는 중"></span>' : ""}${badge}</span></div>`;
  const link = st.link ? `<a class="card-link" href="${esc(st.link)}" target="_blank" rel="noopener noreferrer">웹 화면 열기 ↗</a>` : "";
  if (!st.card) {
    if (st.online === undefined) return `${head}<div class="skeleton-lines" aria-hidden="true"><i></i><i></i><i></i></div>`;
    return `${head}<div class="card-scroll"><div class="empty">연결하지 못했습니다: ${esc(st.error || "")}
      <br><a href="#/settings">연결 설정</a>에서 주소와 토큰을 확인하세요.</div>${link}</div>`;
  }
  const c = st.card;
  const metrics = c.metrics.length ? `<dl class="metrics">${c.metrics.map((x) => `<div class="metric"><dt>${esc(x.label)}</dt><dd>${esc(x.value)}</dd>
    ${x.pct !== null && x.pct !== undefined ? bar(x.pct) : ""}</div>`).join("")}</dl>` : "";
  let sections;
  if (opts.rows === 0) {
    const counts = c.sections.filter((s) => s.rows.length).map((s) => `${esc(s.title)} ${s.rows.length}개`);
    sections = counts.length ? `<p class="muted small-line">${counts.join(" · ")}</p>` : "";
  } else {
    sections = c.sections.map((s, i) => {
      const key = `${st.id}:${i}`;
      const open = opts.rows < 0 || expandedRows.has(key);
      const shown = open ? s.rows : s.rows.slice(0, opts.rows);
      const rest = s.rows.length - shown.length;
      const toggle = rest > 0 ? `<button type="button" class="linklike more-rows" data-expand="${esc(key)}">${rest}개 더 보기</button>`
        : opts.rows > 0 && expandedRows.has(key) && s.rows.length > opts.rows ? `<button type="button" class="linklike more-rows" data-expand="${esc(key)}">접기</button>` : "";
      return `<div class="rows"><span class="rows-title">${esc(s.title)}${s.rows.length > 3 ? ` <span class="muted">${s.rows.length}</span>` : ""}</span>
        ${shown.map((r) => rowHtml(st.id, r)).join("") || `<div class="empty" style="margin-top:4px">${esc(s.empty || "항목이 없습니다")}</div>`}${toggle}</div>`;
    }).join("");
  }
  const actions = c.actions.length ? `<div class="actions">${c.actions.map((a) => actionButton(st.id, a, false)).join("")}</div>` : "";
  return `${head}<div class="card-scroll">${c.note ? `<p class="muted small-line">${esc(c.note)}</p>` : ""}${metrics}${sections}${actions}${link}</div>`;
}

/* ---------- 대시보드 (인프라 · 스마트홈 허브의 상태 카드) ----------
   카드마다 따로 불러와서 느린 시스템이 있어도 나머지는 바로 보인다. 한 번 받은 상태는 기억해 두고
   다시 열 때 먼저 보여 준 뒤 새로 고친다. 배치(순서 · 크기 · 줄 수 · 숨김)는 서버에 저장 → 어느 기기에서나 같음. */
const statusCache = {};
const DASH = { page: null, category: null, conns: [], layout: null, draft: null, editing: false, loading: new Set(), seq: 0, dragId: null };
const ROW_CHOICES = [[0, "요약만"], [3, "3줄"], [5, "5줄"], [10, "10줄"], [-1, "전부"]];
// 같은 크기: 모든 카드를 "가장 긴 카드의 내용 높이"로 맞추고, 고른 크기는 최대 높이로만 쓴다 (넘치면 카드 안에서 스크롤)
const HEIGHT_CHOICES = [["s", "같은 크기 · 최대 작게"], ["m", "같은 크기 · 최대 보통"], ["l", "같은 크기 · 최대 크게"], ["auto", "내용에 맞춤 (카드마다 다름)"]];
const HEIGHT_CAP = { s: 380, m: 480, l: 620 };
const dashHeight = () => dashLayout().height || "m";

const dashLayout = () => (DASH.editing ? DASH.draft : DASH.layout);
function cardOpts(id) { return { size: "m", rows: 5, hidden: false, ...(dashLayout().cards[id] || {}) }; }
function orderedConns() {
  const pos = new Map(dashLayout().order.map((id, i) => [id, i]));
  return DASH.conns.map((c, i) => [c, pos.has(c.id) ? pos.get(c.id) : 1000 + i]).sort((a, b) => a[1] - b[1]).map((x) => x[0]);
}

async function dashSetup(page, category) {
  await loadMeta();
  const [conns, layout] = await Promise.all([api("/api/connections"), api(`/api/layout/${page}`)]);
  Object.assign(DASH, { page, category, layout, draft: null, editing: false, seq: DASH.seq + 1, loading: new Set(),
    conns: conns.filter((c) => c.category === category) });
}

function dashCardHtml(c) {
  const o = cardOpts(c.id);
  if (o.hidden && !DASH.editing) return "";
  const st = statusCache[c.id] || { id: c.id, type: c.type, name: c.name, link: c.config && c.config.url };
  const tools = DASH.editing ? `<div class="dash-tools">
      <span class="grip" title="끌어서 옮기기" aria-hidden="true">⠿</span>
      <button type="button" class="btn sm" data-dash="left" aria-label="${esc(c.name)} 앞으로">◀</button>
      <button type="button" class="btn sm" data-dash="right" aria-label="${esc(c.name)} 뒤로">▶</button>
      <button type="button" class="btn sm" data-dash="size">${o.size === "l" ? "1칸으로" : "2칸으로"}</button>
      <select class="sm-select" data-dash="rows" aria-label="${esc(c.name)} 목록 줄 수">${ROW_CHOICES.map(([v, t]) => `<option value="${v}" ${v === o.rows ? "selected" : ""}>${t}</option>`).join("")}</select>
      <button type="button" class="btn sm" data-dash="hide">${o.hidden ? "보이기" : "숨기기"}</button></div>` : "";
  return `<section class="card dash-card${o.size === "l" ? " wide2" : ""}${o.hidden ? " is-hidden" : ""}" data-cid="${esc(c.id)}"${DASH.editing ? ' draggable="true"' : ""}>
    ${tools}<div class="dash-body">${statusCardInner({ ...st, name: c.name }, o, DASH.loading.has(c.id))}</div></section>`;
}

function dashCounts() {
  const sts = DASH.conns.map((c) => statusCache[c.id]).filter((x) => x && x.online !== undefined);
  const ok = sts.filter((x) => x.online).length;
  const waiting = DASH.conns.length - sts.length;
  return `연결 ${DASH.conns.length}개 · ${ok}개 응답${waiting ? ` · ${waiting}개 확인 중` : ""}`;
}

function dashButtons() {
  if (DASH.editing) {
    return `<div class="chips"><button type="button" class="btn" data-dashmode="reset">기본 배치로</button>
      <button type="button" class="btn" data-dashmode="cancel">취소</button><button type="button" class="btn primary" data-dashmode="save">완료</button></div>`;
  }
  return `<div class="chips"><button type="button" class="btn" data-pick="${DASH.category}">+ 연결 추가</button>
    <button type="button" class="btn" data-dashmode="edit">대시보드 편집</button><button type="button" class="btn accent" data-dashmode="refresh">새로 고침</button></div>`;
}

function dashGridHtml() {
  const hidden = DASH.conns.filter((c) => cardOpts(c.id).hidden).length;
  return `${DASH.editing ? `<div class="dash-help"><label>카드 높이 <select class="sm-select" data-dashheight>${HEIGHT_CHOICES.map(([v, t]) => `<option value="${v}" ${v === dashHeight() ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <span>카드를 끌어서 옮기거나 ◀ ▶로 순서를 바꾸세요. 2칸으로 넓히고, 목록 줄 수를 정하고, 안 보고 싶은 카드는 숨길 수 있어요.</span></div>` : ""}
    <div class="grid dash${DASH.editing ? " editing" : ""}${dashHeight() === "auto" ? "" : ` uniform h-${dashHeight()}`}" id="dash-grid">${orderedConns().map(dashCardHtml).join("")}</div>
    ${!DASH.editing && hidden ? `<p class="muted small-line">숨긴 카드 ${hidden}개 · <button type="button" class="linklike" data-dashmode="edit">대시보드 편집에서 보이기</button></p>` : ""}`;
}

// 카드마다 높이에 맞는 줄 수 (grid-auto-rows: 2px + 카드 아래 여백 14px)
const dashFitObs = "ResizeObserver" in window ? new ResizeObserver((entries) => entries.forEach((en) => fitCard(en.target))) : null;
function fitCard(el) {
  if (!el.isConnected) { if (dashFitObs) dashFitObs.unobserve(el); return; }
  if (el.parentElement && el.parentElement.classList.contains("uniform")) { el.style.gridRowEnd = ""; return; }
  el.style.gridRowEnd = `span ${Math.ceil((el.getBoundingClientRect().height + 14) / 2)}`;
}
function fitUniform(grid) {
  const cards = [...grid.querySelectorAll(":scope > .dash-card")];
  if (!cards.length) return;
  grid.classList.add("measuring");          // 잠깐 높이 제한을 풀고 내용 높이를 잰다 (그리기 전이라 깜빡이지 않음)
  const natural = Math.max(...cards.map((c) => c.getBoundingClientRect().height));
  grid.classList.remove("measuring");
  const h = `${Math.ceil(Math.min(HEIGHT_CAP[dashHeight()] || 480, natural))}px`;
  if (grid.style.getPropertyValue("--dash-h") !== h) grid.style.setProperty("--dash-h", h);
}
// 창 폭이 바뀌면 줄바꿈이 달라져 내용 높이도 달라지므로 다시 잰다
const dashGridObs = "ResizeObserver" in window ? new ResizeObserver((entries) => entries.forEach((en) => {
  if (en.target.isConnected && en.target.classList.contains("uniform")) fitUniform(en.target);
})) : null;
function dashFit() {
  const grid = $("#dash-grid");
  if (!grid) return;
  if (grid.classList.contains("uniform")) {
    grid.querySelectorAll(":scope > .dash-card").forEach((el) => { el.style.gridRowEnd = ""; });
    fitUniform(grid);
    if (dashGridObs) dashGridObs.observe(grid);
    return;
  }
  grid.querySelectorAll(":scope > .dash-card").forEach((el) => { fitCard(el); if (dashFitObs) dashFitObs.observe(el); });
}

function dashPaintAll() {
  const host = $("#dash-host");
  if (host) host.innerHTML = dashGridHtml();
  const head = $("#dash-buttons");
  if (head) head.innerHTML = dashButtons();
  const cnt = $("#dash-count");
  if (cnt) cnt.textContent = dashCounts();
  dashFit();
}

function dashPaintCard(id) {
  const el = document.querySelector(`#dash-grid [data-cid="${CSS.escape(id)}"]`);
  const c = DASH.conns.find((x) => x.id === id);
  if (el && c) {
    // 펼쳐 둔 작업 버튼(details)은 다시 그려도 열린 채로
    const open = [...el.querySelectorAll("details.xrow")].map((d, i) => (d.open ? i : -1)).filter((i) => i >= 0);
    el.outerHTML = dashCardHtml(c);
    const nel = document.querySelector(`#dash-grid [data-cid="${CSS.escape(id)}"]`);
    if (nel) {
      const ds = nel.querySelectorAll("details.xrow");
      open.forEach((i) => { if (ds[i]) ds[i].open = true; });
    }
  }
  const cnt = $("#dash-count");
  if (cnt) cnt.textContent = dashCounts();
  dashFit();
}

/** 카드 상태를 불러온다. ids 를 주면 그 카드만 */
function dashLoad(ids) {
  const seq = DASH.seq;
  for (const c of DASH.conns.filter((x) => !ids || ids.includes(x.id))) {
    DASH.loading.add(c.id);
    dashPaintCard(c.id);
    api(`/api/status/${encodeURIComponent(c.id)}`)
      .then((st) => { statusCache[c.id] = st; })
      .catch((err) => { if (!(err instanceof ApiError && err.message === "로그인이 필요합니다")) statusCache[c.id] = { id: c.id, type: c.type, name: c.name, online: false, error: err.message, card: null }; })
      .finally(() => { if (seq !== DASH.seq) return; DASH.loading.delete(c.id); dashPaintCard(c.id); });
  }
}

function dashMove(id, delta) {
  const order = orderedConns().map((c) => c.id);
  const i = order.indexOf(id), j = i + delta;
  if (i < 0 || j < 0 || j >= order.length) return;
  [order[i], order[j]] = [order[j], order[i]];
  DASH.draft.order = order;
  dashPaintAll();
  const btn = document.querySelector(`#dash-grid [data-cid="${CSS.escape(id)}"] [data-dash="${delta < 0 ? "left" : "right"}"]`);
  if (btn) btn.focus();
}

function dashSetCard(id, patch) {
  DASH.draft.cards[id] = { ...cardOpts(id), ...patch };
  dashPaintAll();
}

view.addEventListener("click", async (e) => {
  const ex = e.target.closest("[data-expand]");
  if (ex) {
    const k = ex.dataset.expand;
    expandedRows.has(k) ? expandedRows.delete(k) : expandedRows.add(k);
    dashPaintCard(k.slice(0, k.lastIndexOf(":")));
    return;
  }
  const mode = e.target.closest("[data-dashmode]");
  if (mode) {
    const m = mode.dataset.dashmode;
    if (m === "refresh") { dashLoad(); return; }
    if (m === "edit") {
      DASH.draft = JSON.parse(JSON.stringify(DASH.layout));
      DASH.draft.order = orderedConns().map((c) => c.id);
      DASH.editing = true;
    } else if (m === "cancel") {
      DASH.editing = false;
    } else if (m === "reset") {
      DASH.draft = { height: "m", order: [], cards: {} };
    } else if (m === "save") {
      try {
        DASH.layout = await api(`/api/layout/${DASH.page}`, { method: "PUT", body: DASH.draft });
        DASH.editing = false;
        toast("배치를 저장했습니다");
      } catch (err) { toast(err.message, true); return; }
    }
    dashPaintAll();
    return;
  }
  const t = e.target.closest("[data-dash]");
  if (!t || t.tagName === "SELECT") return;
  const id = t.closest("[data-cid]").dataset.cid;
  const o = cardOpts(id);
  if (t.dataset.dash === "left") dashMove(id, -1);
  else if (t.dataset.dash === "right") dashMove(id, 1);
  else if (t.dataset.dash === "size") dashSetCard(id, { size: o.size === "l" ? "m" : "l" });
  else if (t.dataset.dash === "hide") dashSetCard(id, { hidden: !o.hidden });
});

view.addEventListener("change", (e) => {
  const h = e.target.closest("select[data-dashheight]");
  if (h) { DASH.draft.height = h.value; dashPaintAll(); return; }
  const t = e.target.closest('select[data-dash="rows"]');
  if (t) dashSetCard(t.closest("[data-cid]").dataset.cid, { rows: Number(t.value) });
});

// 끌어서 옮기기 (편집 중일 때만 draggable)
view.addEventListener("dragstart", (e) => {
  const card = e.target.closest && e.target.closest("#dash-grid.editing [data-cid]");
  if (!card) return;
  DASH.dragId = card.dataset.cid;
  card.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", DASH.dragId);
});
view.addEventListener("dragover", (e) => {
  if (!DASH.dragId || !e.target.closest("#dash-grid")) return;
  e.preventDefault();
  const over = e.target.closest("[data-cid]");
  document.querySelectorAll("#dash-grid .drop-before, #dash-grid .drop-after").forEach((x) => x.classList.remove("drop-before", "drop-after"));
  if (over && over.dataset.cid !== DASH.dragId) {
    const r = over.getBoundingClientRect();
    over.classList.add(e.clientX < r.left + r.width / 2 ? "drop-before" : "drop-after");
  }
});
view.addEventListener("drop", (e) => {
  if (!DASH.dragId) return;
  e.preventDefault();
  const over = e.target.closest("[data-cid]");
  if (over && over.dataset.cid !== DASH.dragId) {
    const order = orderedConns().map((c) => c.id).filter((x) => x !== DASH.dragId);
    const r = over.getBoundingClientRect();
    const at = order.indexOf(over.dataset.cid) + (e.clientX < r.left + r.width / 2 ? 0 : 1);
    order.splice(at, 0, DASH.dragId);
    DASH.draft.order = order;
  }
  DASH.dragId = null;
  dashPaintAll();
});
view.addEventListener("dragend", () => {
  if (!DASH.dragId) return;
  DASH.dragId = null;
  dashPaintAll();
});

// 상태 카드의 작업 버튼
view.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-cact]");
  if (!btn) return;
  const label = btn.dataset.label;
  const confirmMsg = btn.dataset.confirm;
  if (confirmMsg && !(await confirmBox(`${label}할까요?`, confirmMsg, label))) return;
  btn.disabled = true;
  try {
    const r = await api(`/api/connections/${encodeURIComponent(btn.dataset.conn)}/actions/${encodeURIComponent(btn.dataset.cact)}`,
      { method: "POST", body: { params: JSON.parse(btn.dataset.params || "{}"), confirm: !!confirmMsg } });
    if (r.text !== undefined) { showText(r.title || label, r.text); return; }
    toast(r.message || "완료했습니다");
    const cid = btn.dataset.conn;
    setTimeout(() => (document.querySelector(`#dash-grid [data-cid="${CSS.escape(cid)}"]`) ? dashLoad([cid]) : route()), 1000);
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- 인프라 ---------- */
async function renderInfra() {
  await dashSetup("infra", "infra");
  const types = META.filter((m) => m.category === "infra");
  if (!DASH.conns.length) {
    view.innerHTML = `<header class="page-head"><div><h1>인프라</h1><p>아직 연결한 인프라가 없어요.</p></div></header>
      ${emptyStart("인프라 연결하기", "쓰는 것만 골라 연결하면 이 화면에 나타납니다.", types)}`;
    return;
  }
  view.innerHTML = `<header class="page-head"><div><h1>인프라</h1><p id="dash-count">${dashCounts()}</p></div><div id="dash-buttons">${dashButtons()}</div></header>
    <div id="dash-host" class="dash-host">${dashGridHtml()}</div>`;
  dashLoad();
}

view.addEventListener("click", (e) => {
  const b = e.target.closest("[data-pick]");
  if (b) openTypePicker(b.dataset.pick);
});

/* ---------- 스마트홈 허브 ---------- */
const ROLE_OPTIONS = ["HomeKit 홈 허브", "Thread 보더 라우터", "Matter 컨트롤러", "Matter 브리지", "Zigbee 코디네이터", "음성 비서", "브리지", "디스플레이", "가전 허브"];
const PLATFORM_OPTIONS = ["HomeKit", "Google Home", "SmartThings", "Aqara", "Homey", "LG ThinQ", "Hubitat", "Home Assistant", "기타"];
let pingCache = {};

async function renderHubs() {
  const [, devices, platforms, backups] = await Promise.all([
    dashSetup("hubs", "smarthome"), api("/api/registry/devices"), api("/api/registry/platforms"), api("/api/hub-backups"),
  ]);
  const types = META.filter((m) => m.category === "smarthome");
  const list = DASH.conns;
  view.innerHTML = `
    <header class="page-head"><div><h1>스마트홈 허브</h1><p>API로 관리하는 허브와, 연동은 안 되지만 역할을 기록해 두는 기기</p></div></header>
    ${list.length ? `<section class="section"><div class="section-head"><div><h2>허브 상태</h2><p id="dash-count">${dashCounts()}</p></div><div id="dash-buttons">${dashButtons()}</div></div>
      <div id="dash-host" class="dash-host">${dashGridHtml()}</div>
      ${backups.length ? `<details class="card"><summary style="cursor:pointer;font-size:14px">Hubitat 백업 파일 ${backups.length}개</summary>
        <div class="rows">${backups.map((b) => `<div class="row"><div class="row-main"><b class="mono">${esc(b.file)}</b><small>${(b.size / 1048576).toFixed(1)} MB · ${new Date(b.mtime * 1000).toLocaleString("ko-KR")}</small></div>
        <a class="btn sm" style="display:inline-flex;align-items:center;text-decoration:none" href="/api/hub-backups/${encodeURIComponent(b.file)}" download>받기</a></div>`).join("")}</div></details>` : ""}
    </section>`
    : `<section class="section">${emptyStart("허브 연결하기", "쓰는 허브만 골라 연결하세요.", types)}</section>`}
    <section class="section"><div class="section-head"><div><h2>수동 등록 기기</h2><p>API 연동은 없지만 IP를 넣으면 응답 여부(ping)를 확인합니다</p></div>
      <div class="chips">${devices.some((d) => d.ip) ? '<button class="btn" data-act="ping-all">전체 응답 확인</button>' : ""}<button class="btn accent" data-act="dev-add">+ 기기 등록</button></div></div>
      <div class="grid mid">${devices.map(manualCard).join("") || '<div class="empty">Apple TV, HomePod, Nest Hub, Aqara 허브처럼 API로 연결하지 않는 기기를 역할과 함께 적어 둘 수 있어요. "+ 기기 등록"을 누르세요.</div>'}</div>
    </section>
    <section class="section"><div class="section-head"><div><h2>플랫폼 역할</h2><p>플랫폼마다 무엇을 맡기는지</p></div>
      <button class="btn" data-act="pf-add">+ 플랫폼 추가</button></div>
      ${platforms.length ? `<div class="table-wrap"><table class="stack-table full" style="min-width:860px"><thead><tr><th scope="col">플랫폼</th><th scope="col">용도</th><th scope="col">주요 기능 · 담당 기기</th><th scope="col">허브 · 연결 경로</th><th scope="col"><span class="muted">편집</span></th></tr></thead>
      <tbody>${platforms.map((p) => `<tr><th scope="row">${esc(p.name)}</th><td><span class="tag">${esc(p.use)}</span></td><td>${esc(p.features)}</td><td>${esc(p.path)}</td>
        <td class="cell-actions" style="white-space:nowrap"><button class="btn sm" data-act="pf-edit" data-k="${p.id}">편집</button> <button class="btn sm danger" data-act="pf-del" data-k="${p.id}" aria-label="${esc(p.name)} 삭제">삭제</button></td></tr>`).join("")}</tbody></table></div>`
      : '<div class="empty">플랫폼마다 무엇을 맡기는지 정리해 두는 표입니다. "+ 플랫폼 추가"로 시작하세요.</div>'}
    </section>`;
  view._devices = devices;
  view._platforms = platforms;
  if (list.length) dashLoad();
}

function manualCard(d) {
  const p = pingCache[d.id];
  const badge = !d.ip ? '<span class="badge">IP 없음</span>'
    : p === true ? '<span class="badge ok"><span class="dot ok"></span>응답</span>'
    : p === false ? '<span class="badge bad"><span class="dot bad"></span>응답 없음</span>'
    : '<span class="badge"><span class="dot"></span>응답 확인 전</span>';
  return `<article class="card"><div class="card-head"><div class="card-title"><b>${esc(d.name)}</b>
    <small>${esc(d.platform)}${d.model ? " · " + esc(d.model) : ""}${d.ip ? " · " + esc(d.ip) : ""}</small></div>${badge}</div>
    ${d.roles.length ? `<div class="chips" style="gap:6px">${d.roles.map((r) => `<span class="tag">${esc(r)}</span>`).join("")}</div>` : ""}
    ${d.memo ? `<p style="margin:0;font-size:13px;color:var(--muted);line-height:1.5">${esc(d.memo)}</p>` : ""}
    <div class="actions"><button class="btn" data-act="dev-edit" data-k="${d.id}">편집</button><button class="btn danger" data-act="dev-del" data-k="${d.id}">삭제</button></div></article>`;
}

const DEVICE_FIELDS = [
  { name: "name", label: "이름", required: true, placeholder: "예: 거실 Apple TV" },
  { name: "model", label: "모델", placeholder: "예: Apple TV 4K (3세대)" },
  { name: "platform", label: "플랫폼", type: "select", options: PLATFORM_OPTIONS },
  { name: "ip", label: "IP 주소 (선택)", placeholder: "192.168.0.x" },
  { name: "roles", label: "역할", type: "checks", options: ROLE_OPTIONS },
  { name: "memo", label: "메모", type: "textarea", full: true, placeholder: "연결된 기기, 주의할 점 등" },
];
const PLATFORM_FIELDS = [
  { name: "name", label: "플랫폼", required: true },
  { name: "use", label: "용도", placeholder: "예: 자동화 중심" },
  { name: "features", label: "주요 기능 · 담당 기기", type: "textarea", full: true },
  { name: "path", label: "허브 · 연결 경로", type: "textarea", full: true },
];
async function pathFields() {
  const conns = await api("/api/connections");
  return [
    { name: "src", label: "출발", required: true, placeholder: "예: SmartThings" },
    { name: "dst", label: "도착", required: true, placeholder: "예: Hubitat Main" },
    { name: "via", label: "연동 방식", full: true, placeholder: "예: HubiThings Replica" },
    { name: "check_ref", label: "상태 확인 (이 연결이 응답하면 정상으로 표시)", full: true, type: "select",
      options: [["", "확인 안 함"], ...conns.map((c) => [c.id, `${c.name} (${c.title})`])] },
  ];
}

async function saveRow(kind, id, fields, current) {
  const title = { devices: "기기", platforms: "플랫폼", paths: "연동 경로" }[kind];
  const values = await formBox(id ? `${title} 편집` : `${title} 추가`, fields, current || {});
  if (!values) return;
  try {
    await api(`/api/registry/${kind}${id ? "/" + id : ""}`, { method: id ? "PUT" : "POST", body: { ...values, sort: current ? current.sort : 999 } });
    toast("저장했습니다");
    route();
  } catch (e) { toast(e.message, true); }
}

async function deleteRow(kind, id, name) {
  if (!(await confirmBox("삭제할까요?", `${name} 항목을 삭제합니다.`, "삭제"))) return;
  try { await api(`/api/registry/${kind}/${id}`, { method: "DELETE" }); toast("삭제했습니다"); route(); }
  catch (e) { toast(e.message, true); }
}

/* ---------- 스마트홈 연동 ---------- */
let roomFilter = "전체";

async function renderIntegration() {
  const [d] = await Promise.all([api("/api/smarthome"), loadMeta()]);
  view._sm = d;
  drawIntegration();
}

function drawIntegration() {
  const d = view._sm;
  const hasSource = d.sources.length > 0;
  const rooms = ["전체", ...new Set(d.devices.map((x) => x.room))];
  if (!rooms.includes(roomFilter)) roomFilter = "전체";
  const shown = d.devices.filter((x) => roomFilter === "전체" || x.room === roomFilter);
  const statusChip = { ok: '<span class="badge ok">응답 중</span>', down: '<span class="badge bad">응답 없음</span>', unknown: '<span class="badge">연결 전</span>', unchecked: '<span class="badge">확인 안 함</span>' };
  const away = (d.mode || "").toLowerCase() === "away";
  const chips = [
    d.mode ? `<span class="chip"><span class="dot ${away ? "warn" : "ok"}"></span>모드 · ${esc(d.mode)}</span>` : "",
    d.hsm ? `<span class="chip">HSM · ${esc(d.hsm)}</span>` : "",
    hasSource ? '<button class="btn accent" data-refresh>새로 고침</button>' : "",
  ].join("");

  const devicesHtml = !hasSource
    ? emptyStart("기기 제어", "기기를 가져올 수 있는 허브(Hubitat Maker API, Home Assistant, Homey Pro, SwitchBot 등)를 연결하면 방별 기기 목록과 켜기/끄기가 여기에 나타납니다.", META.filter((m) => m.devices))
    : `<div class="split">
      <section class="section grow"><div class="section-head"><h2>기기 제어</h2>
        ${d.devices.length ? `<div class="filters" role="group" aria-label="방 필터">${rooms.map((r) => `<button type="button" data-room="${esc(r)}" aria-pressed="${r === roomFilter}">${esc(r)}</button>`).join("")}</div>` : ""}</div>
        ${d.devices.length ? `<div class="legend"><span><span class="src HE">HE</span>Hubitat</span><span><span class="src HA">HA</span>Home Assistant</span>${d.devices.some((x) => x.source === "SB") ? '<span><span class="src SB">SB</span>SwitchBot</span>' : ""}${d.devices.some((x) => x.source === "HY") ? '<span><span class="src HY">HY</span>Homey</span>' : ""}<span><span class="src HB">HB</span>Homebridge → HomeKit 노출</span></div>` : ""}
        <div class="list">${shown.map(deviceRow).join("") || '<div class="empty" style="border:none">가져온 기기가 없습니다. Maker API에서 관리할 기기를 골랐는지 확인하세요.</div>'}</div>
        ${d.devices.length ? `<span class="muted" style="font-size:12px">표시 ${shown.length}개 · 전체 ${d.devices.length}개</span>` : ""}
      </section>
      <aside class="rail" aria-labelledby="al-h"><h2 id="al-h" style="margin:0;font-size:17px">확인 필요</h2>
        ${d.alerts.map((a) => `<div class="alert ${a.kind}"><span class="ico" aria-hidden="true">${a.kind === "down" ? "×" : "!"}</span><div><b>${esc(a.title)}</b><p>${esc(a.body)}</p></div></div>`).join("") || '<div class="empty">지금은 확인할 것이 없습니다</div>'}
      </aside>
    </div>`;

  view.innerHTML = `
    <header class="page-head"><div><h1>스마트홈 연동</h1><p>플랫폼 간 연동 경로와 기기 제어</p></div>
      ${chips ? `<div class="chips">${chips}</div>` : ""}</header>
    ${devicesHtml}
    <section class="section"><div class="section-head"><div><h2>연동 경로</h2><p>어느 플랫폼이 어떤 방식으로 어디에 연결되는지 적어 두면, 연결한 시스템의 응답 여부로 상태를 보여 줍니다.</p></div>
      <button class="btn" data-act="path-add">+ 경로 추가</button></div>
      ${d.paths.length ? `<div class="table-wrap"><table class="stack-table" style="min-width:720px"><thead><tr><th scope="col">출발</th><th scope="col">연동 방식</th><th scope="col">도착</th><th scope="col">상태</th><th scope="col"><span class="muted">편집</span></th></tr></thead>
      <tbody>${d.paths.map((p) => `<tr><th scope="row">${esc(p.src)}</th><td><span class="path-arrow" aria-hidden="true">→ </span>${esc(p.via)}</td><td><span class="path-arrow" aria-hidden="true">→ </span>${esc(p.dst)}</td>
        <td>${statusChip[p.status] || statusChip.unknown}</td>
        <td class="cell-actions" style="white-space:nowrap"><button class="btn sm" data-act="path-edit" data-k="${p.id}">편집</button> <button class="btn sm danger" data-act="path-del" data-k="${p.id}">삭제</button></td></tr>`).join("")}</tbody></table></div>`
      : '<div class="empty">아직 적어 둔 연동 경로가 없습니다. 예: SmartThings → HubiThings Replica → Hubitat</div>'}
    </section>`;
}

function deviceRow(x) {
  const key = `${esc(x.source)}|${esc(x.hub)}|${esc(x.id)}`;
  const ctl = x.is_switch
    ? `<button type="button" class="switch" role="switch" aria-checked="${x.on}" aria-label="${esc(x.label)} 켜기/끄기" data-toggle="${key}"></button>`
    : `<span class="pill ${esc(x.tone)}">${esc(x.state_label || "—")}</span>`;
  return `<div class="row"><div class="row-main"><div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center"><b>${esc(x.label)}</b>${(x.sources || [x.source]).map((s) => `<span class="src ${esc(s)}">${esc(s)}</span>`).join("")}</div>
    <small>${esc(x.room)} · ${esc(x.detail)}</small></div>${ctl}</div>`;
}

/* ---------- 작업 기록 ---------- */
async function renderLog() {
  const rows = await api("/api/audit?limit=200");
  view.innerHTML = `<header class="page-head"><div><h1>작업 기록</h1><p>HomeOps에서 실행한 제어 작업</p></div></header>
    <div class="table-wrap"><table style="min-width:640px"><thead><tr><th scope="col">시각</th><th scope="col">작업</th><th scope="col">대상</th><th scope="col">결과</th></tr></thead>
    <tbody>${rows.map((r) => `<tr><td class="mono">${esc(new Date(r.ts).toLocaleString("ko-KR"))}</td><td>${esc(r.action)}</td><td class="mono">${esc(r.target)}</td>
    <td><span class="pill ${r.result === "성공" ? "ok" : "warn"}">${esc(r.result)}</span></td></tr>`).join("") || '<tr><td colspan="4">기록이 없습니다</td></tr>'}</tbody></table></div>`;
}

/* ---------- 연결 설정 ---------- */
const MASK = "__SET__";

function inputHtml(f, value, idPrefix) {
  const id = `${idPrefix}-${f.name}`;
  if (f.type === "bool") {
    const on = value === undefined || value === null ? f.def : value;
    return `<label class="field full" style="flex-direction:row;align-items:center;gap:10px;color:var(--text)"><input type="checkbox" name="${f.name}" ${on ? "checked" : ""} style="width:20px;height:20px;accent-color:var(--accent)">${esc(f.label)}</label>`;
  }
  if (f.type === "select") {
    const cur = value ?? f.def;
    return `<label class="field${f.full ? " full" : ""}" for="${id}">${esc(f.label)}<select id="${id}" name="${f.name}">
      ${(f.options || []).map(([v, t]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
  }
  const isSet = f.secret && value === MASK;
  const v = f.secret ? (value && value !== MASK ? value : "") : (value ?? f.def ?? "");
  const ph = isSet ? "저장됨 · 바꿀 때만 입력" : (f.ph || "");
  return `<label class="field${f.full ? " full" : ""}" for="${id}"><span class="field-label">${esc(f.label)}${isSet ? ' <span class="badge ok">저장됨</span>' : ""}</span>
    <input id="${id}" name="${f.name}" ${f.secret ? 'type="password" autocomplete="new-password"' : 'autocomplete="off"'} ${f.type === "number" ? 'inputmode="numeric"' : ""} ${f.type === "time" ? 'type="time"' : ""} value="${esc(v)}" placeholder="${esc(ph)}"></label>`;
}

function readForm(form, fields) {
  const out = {};
  for (const f of fields) {
    const el = form.elements[f.name];
    if (!el) continue;
    if (f.type === "bool") out[f.name] = el.checked;
    else out[f.name] = el.value.trim();
  }
  return out;
}

function setResult(form, ok, msg) {
  const p = form.querySelector(".test-result");
  if (!p) return;
  p.textContent = msg;
  p.className = "test-result " + (ok ? "ok" : "bad");
}

/** 연동 선언의 입력 칸 → 폼 칸 */
function formFields(meta) {
  return [{ name: "__name", label: "이름", ph: meta.title },
    ...meta.fields.filter((f) => f.kind !== "hidden").map((f) => ({ name: f.name, label: f.label, type: f.kind === "url" || f.kind === "text" ? "text" : f.kind,
      secret: f.secret, ph: f.ph, def: f.default, full: f.full, options: f.options }))];
}

function readConn(form, meta) {
  const v = readForm(form, formFields(meta));
  const name = v.__name;
  delete v.__name;
  return { name, config: v };
}

async function renderSettings() {
  const [conns, s, me] = await Promise.all([api("/api/connections"), api("/api/settings"), api("/api/auth/me"), loadMeta()]);
  view._conns = conns;
  view._settings = s;
  view._me = me;
  view._editing = new Set();
  view._new = [];        // 아직 저장하지 않은 새 연결 [{key, type}]
  view._drafts = {};     // 다시 그릴 때 입력 중인 값 유지
  drawSettings();
  const add = new URLSearchParams(location.hash.split("?")[1] || "").get("add");
  history.replaceState(null, "", "#/settings");
  if (add && metaOf(add)) startAdd(add);
}

function keepDrafts() {
  view.querySelectorAll("form[data-card]").forEach((f) => {
    const meta = metaOf(f.dataset.type);
    if (meta) view._drafts[f.dataset.card] = readConn(f, meta);
  });
}

function connForm(key, meta, conn) {
  const draft = view._drafts[key];
  const values = { __name: draft ? draft.name : (conn ? conn.name : ""), ...(conn ? conn.config : {}), ...(draft ? draft.config : {}) };
  if (conn && draft) {  // 비워 둔 비밀값은 "저장됨" 유지
    for (const f of meta.fields) if (f.secret && !draft.config[f.name] && conn.config[f.name] === MASK) values[f.name] = MASK;
  }
  return `<form class="card conn editing" data-card="${esc(key)}" data-type="${esc(meta.type)}" ${conn ? `data-id="${esc(conn.id)}"` : ""} novalidate>
    <div class="card-head"><div class="card-title"><span class="type-label">${esc(CATEGORY_LABEL[meta.category] || "")}</span>
      <h2>${esc(conn ? conn.name : `${meta.title} 추가`)}</h2></div>${conn ? "" : '<span class="badge warn">새 연결</span>'}</div>
    ${meta.help ? `<div class="howto">${meta.help}</div>` : ""}
    <div class="form-grid">${formFields(meta).map((f) => inputHtml(f, values[f.name], key.replace(/\W/g, ""))).join("")}</div>
    <p class="test-result" role="status" aria-live="polite"></p>
    <div class="actions"><button type="button" class="btn" data-sact="test">연결 테스트</button>
      <button type="button" class="btn primary" data-sact="save">저장</button>
      <button type="button" class="btn" data-sact="cancel">취소</button></div></form>`;
}

function connSummary(conn) {
  const meta = metaOf(conn.type);
  return `<article class="card conn" data-card="c:${esc(conn.id)}" data-type="${esc(conn.type)}" data-id="${esc(conn.id)}">
    <div class="card-head"><div class="card-title"><span class="type-label">${esc(meta ? meta.title : conn.type)}</span><b>${esc(conn.name)}</b>
      <small>${esc(shortUrl(conn.config.url))}</small></div>
      ${conn.available ? '<span class="badge ok"><span class="dot ok"></span>저장됨</span>' : '<span class="badge bad">지원 안 됨</span>'}</div>
    <p class="test-result" role="status" aria-live="polite"></p>
    <div class="actions">${conn.available ? '<button type="button" class="btn" data-sact="test">연결 테스트</button><button type="button" class="btn" data-sact="edit">편집</button>' : ""}
      <button type="button" class="btn danger" data-sact="remove">삭제</button></div></article>`;
}

function pickerByCategory() {
  return ["smarthome", "infra"].map((cat) => {
    const types = META.filter((m) => m.category === cat && m.type !== "web");
    return types.length ? `<div class="picker-group"><span class="rows-title">${CATEGORY_LABEL[cat]}</span>${typeButtons(types, false)}</div>` : "";
  }).join("") + `<div class="picker-group"><span class="rows-title">기타</span>${typeButtons(META.filter((m) => m.type === "web"), false)}</div>`;
}

function drawSettings() {
  const s = view._settings;
  const me = view._me;
  const cards = [
    ...view._new.map((n) => connForm(n.key, metaOf(n.type), null)),
    ...view._conns.map((c) => (view._editing.has(c.id) && metaOf(c.type) ? connForm(`c:${c.id}`, metaOf(c.type), c) : connSummary(c))),
  ];
  const empty = cards.length === 0;
  view.innerHTML = `
    <header class="page-head"><div><h1>연결 설정</h1><p>${empty ? "쓰는 시스템만 골라서 연결하세요." : `연결 ${view._conns.length}개 · 토큰과 비밀번호는 암호화되어 저장됩니다.`}</p></div>
      ${empty ? "" : '<div class="chips"><button type="button" class="btn primary" data-sact="add">+ 연결 추가</button></div>'}</header>
    ${empty ? `<section class="card onboarding"><div class="card-title"><h2>무엇부터 연결할까요?</h2>
        <small>하나만 연결해도 바로 쓸 수 있고, 나머지는 나중에 "+ 연결 추가"로 언제든 붙일 수 있어요. 같은 종류도 여러 개 추가할 수 있습니다.</small></div>
        ${pickerByCategory()}</section>`
      : `<div class="grid wide">${cards.join("")}</div>`}

    <details class="card fold"><summary><b>알림 · 계정</b><small>배터리 경고 기준 ${s.alerts.battery_warn}% · 로그인 ${esc(me.user)}</small></summary>
      <div class="grid wide" style="margin-top:12px">
        <form class="card" data-section="alerts" novalidate style="background:var(--raise)">
          <div class="card-title"><h2>알림 기준</h2><small>스마트홈 연동 화면의 "확인 필요"</small></div>
          <div class="form-grid">${inputHtml({ name: "battery_warn", label: "배터리 경고 기준 (%)", type: "number" }, s.alerts.battery_warn, "alerts")}</div>
          <p class="test-result" role="status" aria-live="polite"></p>
          <div class="actions"><button type="button" class="btn primary" data-sact="alerts-save">저장</button></div>
        </form>
        <form class="card" id="pw-form" novalidate style="background:var(--raise)">
          <div class="card-title"><h2>관리자 비밀번호</h2><small>로그인 계정 ${esc(me.user)}</small></div>
          ${me.env_admin ? '<div class="howto">환경 변수(HOMEOPS_ADMIN_PASSWORD)로 지정한 계정이라 여기서는 바꿀 수 없습니다.</div>' : `
          <div class="form-grid">
            <label class="field full">현재 비밀번호<input type="password" name="current" autocomplete="current-password"></label>
            <label class="field">새 비밀번호 (8자 이상)<input type="password" name="new" autocomplete="new-password" minlength="8"></label>
            <label class="field">새 비밀번호 확인<input type="password" name="new2" autocomplete="new-password" minlength="8"></label>
          </div>
          <p class="test-result" role="status" aria-live="polite"></p>
          <div class="actions"><button type="button" class="btn primary" data-sact="password">비밀번호 변경</button></div>`}
        </form>
      </div>
    </details>

    <div class="chips"><a class="btn" style="display:inline-flex;align-items:center;text-decoration:none" href="#/backup">백업 · 복구</a>
      <a class="btn" style="display:inline-flex;align-items:center;text-decoration:none" href="#/log">작업 기록</a>
      <a class="btn" style="display:inline-flex;align-items:center;text-decoration:none" href="#/update">업데이트</a></div>`;
}

let newSeq = 0;
function startAdd(type) {
  keepDrafts();
  const key = `n:${++newSeq}`;
  view._new.unshift({ key, type });
  drawSettings();
  const card = view.querySelector(`[data-card="${key}"]`);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    const first = card.querySelector("input:not([type=checkbox])");
    if (first) first.focus({ preventScroll: true });
  }
}

async function refreshConns(message) {
  view._conns = await api("/api/connections");
  drawSettings();
  if (message) toast(message);
}

view.addEventListener("click", async (e) => {
  if (view.dataset.route !== "settings") return;
  const pick = e.target.closest("[data-add]");
  if (pick) { startAdd(pick.dataset.add); return; }
  const btn = e.target.closest("[data-sact]");
  if (!btn) return;
  const a = btn.dataset.sact;
  const card = btn.closest("[data-card]");
  const form = btn.closest("form") || card;

  if (a === "add") {
    keepDrafts();
    dlg.innerHTML = `<form method="dialog" class="dlg"><h2>연결 추가</h2><p>추가할 시스템을 고르세요. 같은 종류도 여러 개 추가할 수 있어요.</p>${pickerByCategory()}
      <div class="dlg-foot"><button class="btn" value="cancel">닫기</button></div></form>`;
    dlg.showModal();
    return;
  }
  if (a === "password") {
    const f = form.elements;
    if (f.new.value !== f.new2.value) { setResult(form, false, "새 비밀번호 확인이 일치하지 않습니다"); return; }
    try {
      await api("/api/auth/password", { method: "POST", body: { current: f.current.value, new: f.new.value } });
      form.reset(); setResult(form, true, "비밀번호를 바꿨습니다");
    } catch (err) { setResult(form, false, err.message); }
    return;
  }
  if (a === "alerts-save") {
    btn.disabled = true;
    try {
      view._settings = await api("/api/settings/alerts", { method: "PUT", body: { battery_warn: Number(form.elements.battery_warn.value) } });
      setResult(form, true, "저장했습니다");
    } catch (err) { setResult(form, false, err.message); } finally { btn.disabled = false; }
    return;
  }
  if (!card) return;
  const key = card.dataset.card;
  const type = card.dataset.type;
  const id = card.dataset.id || null;
  const meta = metaOf(type);
  const editing = card.tagName === "FORM";
  const conn = id ? view._conns.find((c) => c.id === id) : null;

  if (a === "edit") { keepDrafts(); view._editing.add(id); drawSettings(); return; }
  if (a === "cancel") {
    keepDrafts();
    delete view._drafts[key];
    if (id) view._editing.delete(id);
    else view._new = view._new.filter((n) => n.key !== key);
    drawSettings();
    return;
  }

  const body = editing ? { type, id, ...readConn(card, meta) } : { type, id, name: conn.name, config: conn.config };

  if (a === "test") {
    btn.disabled = true; setResult(form, true, "연결하는 중…");
    try {
      const r = await api("/api/connections/test", { method: "POST", body });
      setResult(form, r.ok, r.message);
    } catch (err) { setResult(form, false, err.message); } finally { btn.disabled = false; }
    return;
  }
  if (a === "save") {
    btn.disabled = true;
    try {
      keepDrafts();
      if (id) await api(`/api/connections/${encodeURIComponent(id)}`, { method: "PUT", body: { name: body.name, config: body.config } });
      else await api("/api/connections", { method: "POST", body: { type, name: body.name, config: body.config } });
      delete view._drafts[key];
      if (id) view._editing.delete(id);
      else view._new = view._new.filter((n) => n.key !== key);
      await refreshConns(`${body.name || meta.title} 연결을 저장했습니다`);
    } catch (err) { setResult(form, false, err.message); btn.disabled = false; }
    return;
  }
  if (a === "remove") {
    if (!(await confirmBox("연결을 삭제할까요?", `${conn.name} 연결 정보를 지웁니다. 장비 자체에는 영향이 없습니다.`, "삭제"))) return;
    try {
      keepDrafts();
      await api(`/api/connections/${encodeURIComponent(id)}`, { method: "DELETE" });
      view._editing.delete(id);
      await refreshConns(`${conn.name} 연결을 삭제했습니다`);
    } catch (err) { toast(err.message, true); }
  }
});

// 대화상자 안의 종류 버튼 (연결 설정 · 백업 원격 저장소 공용)
dlg.addEventListener("click", (e) => {
  const pick = e.target.closest("[data-add]");
  if (!pick || pick.disabled) return;
  e.preventDefault();
  dlg.close("cancel");
  if (view.dataset.route === "settings") startAdd(pick.dataset.add);
  else if (view.dataset.route === "backup") startAddTarget(pick.dataset.add);
});

/* ---------- 백업 · 복구 ---------- */
const BK_GENERAL = [
  { name: "password", label: "백업 암호 (백업 파일 전체를 암호화)", secret: true, full: true },
  { name: "schedule_enabled", label: "매일 자동 백업", type: "bool", def: false },
  { name: "schedule_time", label: "자동 백업 시각", type: "time", def: "03:30" },
  { name: "timezone", label: "시간대", def: "Asia/Seoul" },
  { name: "keep_local", label: "로컬 보관 개수", type: "number", def: 14 },
  { name: "keep_remote", label: "원격 보관 개수", type: "number", def: 30 },
  { name: "include_hub_backups", label: "Hubitat 허브 백업 파일(허브별 최신 1개) 포함", type: "bool", def: false },
];
const BK_FTP = [
  { name: "host", label: "서버 주소", ph: "192.168.0.x 또는 nas.local" },
  { name: "port", label: "포트", type: "number", def: 21 },
  { name: "tls", label: "FTPS (TLS) 사용", type: "bool", def: false },
  { name: "username", label: "아이디" },
  { name: "password", label: "비밀번호", secret: true },
  { name: "path", label: "저장 폴더 (없으면 만듭니다)", def: "/homeops", full: true },
];
const BK_DAV = [
  { name: "url", label: "폴더 주소 (없으면 만듭니다)", ph: "https://192.168.0.x:5006/backup/homeops", full: true },
  { name: "username", label: "아이디" },
  { name: "password", label: "비밀번호", secret: true },
  { name: "verify_ssl", label: "HTTPS 인증서 검증 (자체 서명 인증서면 끄기)", type: "bool", def: true },
];
let backupTab = "local";
const BK_TARGETS = {
  ftp: { title: "FTP", sub: "FTP / FTPS 서버", desc: "NAS나 공유기의 FTP 서버", fields: BK_FTP },
  webdav: { title: "WebDAV", sub: "Synology WebDAV, Nextcloud 등", desc: "Synology WebDAV, Nextcloud 등", fields: BK_DAV },
};

function fmtSize(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}
function backupDate(name) {
  const m = /^homeops-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})(-.+)?\.hob$/.exec(name);
  if (!m) return name;
  return `${m[1]}.${m[2]}.${m[3]} ${m[4]}:${m[5]}${m[7] === "-before-restore" ? " · 복구 전 자동" : ""}`;
}

async function renderBackup() {
  const [st, s] = await Promise.all([api("/api/backup"), api("/api/settings")]);
  view._bk = st;
  view._settings = s;
  view._bkAdding = new Set();
  if (backupTab !== "local" && !st.targets[backupTab]) backupTab = "local";
  await drawBackup();
}

function bkForm(kind, title, sub, fields, value, extraButtons, afterButtons = "") {
  return `<form class="card" data-bk="${kind}" novalidate>
    <div class="card-title"><h2>${esc(title)}</h2><small>${esc(sub)}</small></div>
    <div class="form-grid">${fields.map((f) => inputHtml(f, value[f.name], `bk-${kind}`)).join("")}</div>
    <p class="test-result" role="status" aria-live="polite"></p>
    <div class="actions">${extraButtons}<button type="button" class="btn primary" data-bact="save">저장</button>${afterButtons}</div></form>`;
}

async function drawBackup() {
  const st = view._bk;
  const b = view._settings.backup;
  const remotes = ["ftp", "webdav"].filter((k) => b[k].enabled || view._bkAdding.has(k));
  const last = st.last;
  const uploads = last && last.uploads ? Object.entries(last.uploads).map(([k, v]) =>
    `<span class="badge ${v === "성공" ? "ok" : "bad"}" title="${esc(v)}">${k.toUpperCase()} ${v === "성공" ? "성공" : "실패"}</span>`).join("") : "";
  const lastCard = !last ? '<div class="empty">아직 백업한 적이 없습니다</div>'
    : `<div class="row" style="border:none"><div class="row-main"><b>${esc(new Date(last.time).toLocaleString("ko-KR"))} · ${esc(last.reason)}</b>
      <small>${last.name ? esc(last.name) + " · " + fmtSize(last.size) : esc(last.error || "")}${last.hub_files ? ` · 허브 백업 ${last.hub_files}개 포함` : ""}</small></div>
      <span class="badge ${last.ok ? "ok" : "bad"}">${last.ok ? "성공" : "일부 실패"}</span></div>
      ${uploads ? `<div class="chips" style="gap:6px">${uploads}</div>` : ""}
      ${Object.values(last.uploads || {}).filter((v) => v !== "성공").map((v) => `<p class="test-result bad">${esc(v)}</p>`).join("")}`;

  const tabs = [["local", "로컬"], ...(st.targets.ftp ? [["ftp", "FTP"]] : []), ...(st.targets.webdav ? [["webdav", "WebDAV"]] : [])];
  let files = st.local, listErr = "";
  if (backupTab !== "local") {
    try { files = await api(`/api/backup/remote/${backupTab}`); } catch (e) { files = []; listErr = e.message; }
  }
  const rows = files.map((f) => `<div class="row"><div class="row-main"><b>${esc(backupDate(f.name))}</b><small class="mono">${esc(f.name)} · ${fmtSize(f.size)}</small></div>
    <div class="row-act">
      ${backupTab === "local" ? `<a class="btn sm" style="display:inline-flex;align-items:center;text-decoration:none" href="/api/backup/local/${encodeURIComponent(f.name)}" download>받기</a>` : ""}
      <button class="btn sm" data-bact="restore" data-k="${esc(f.name)}">복구</button>
      ${backupTab === "local" ? `<button class="btn sm danger" data-bact="delete" data-k="${esc(f.name)}">삭제</button>` : ""}
    </div></div>`).join("");

  view.innerHTML = `
    <header class="page-head"><div><h1>백업 · 복구</h1><p>계정, 연결 설정, 수동 등록 기기, 플랫폼 역할, 연동 경로, 작업 기록을 한 파일로 백업합니다.</p></div>
      <div class="chips"><a class="btn" style="display:inline-flex;align-items:center;text-decoration:none" href="#/settings">연결 설정</a>
      <button class="btn primary" data-bact="run" ${st.password_set ? "" : "disabled title=\"백업 암호를 먼저 저장하세요\""}>지금 백업</button></div></header>

    ${st.password_set ? "" : '<div class="alert warn"><span class="ico" aria-hidden="true">!</span><div><b>백업 암호를 먼저 정하세요</b><p>백업 파일에는 토큰과 비밀번호가 들어 있어 암호로 전체를 잠급니다. 이 암호를 잊으면 백업을 복구할 수 없으니 따로 적어 두세요.</p></div></div>'}

    <div class="grid wide">
      <section class="card"><div class="card-title"><h2>마지막 백업</h2></div>${lastCard}</section>
      <section class="card"><div class="card-title"><h2>다음 자동 백업</h2></div>
        <p style="margin:0;font-size:18px">${st.next_run ? esc(new Date(st.next_run).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" })) : "꺼져 있음"}</p>
        <small class="muted">${st.next_run ? `매일 ${esc(b.schedule_time)} (${esc(b.timezone)}) · 로컬 ${b.keep_local}개, 원격 ${b.keep_remote}개 보관` : "아래 백업 설정에서 켤 수 있습니다"}</small>
        <small class="muted">저장 위치: 로컬${st.targets.ftp ? " · FTP" : ""}${st.targets.webdav ? " · WebDAV" : ""}</small></section>
    </div>

    <section class="section"><div class="section-head"><h2>백업 설정</h2></div>
      <div class="grid wide">
        ${bkForm("general", "기본", "암호 · 자동 백업 · 보관 개수", BK_GENERAL, b, "")}
      </div></section>

    <section class="section"><div class="section-head"><div><h2>원격 저장소</h2><p>로컬과 함께 백업 파일을 올릴 곳입니다.</p></div>
      ${remotes.length < 2 ? '<button type="button" class="btn accent" data-bact="add-target">+ 저장소 추가</button>' : ""}</div>
      ${remotes.length ? `<div class="grid wide">${remotes.map((k) => {
        const t = BK_TARGETS[k];
        const isNew = !b[k].enabled;
        return bkForm(k, t.title, t.sub, t.fields, b[k],
          '<button type="button" class="btn" data-bact="test" data-k="' + k + '">연결 테스트</button>',
          isNew ? '<button type="button" class="btn" data-bact="cancel-target" data-k="' + k + '">취소</button>'
                : '<button type="button" class="btn danger" data-bact="remove-target" data-k="' + k + '">삭제</button>');
      }).join("")}</div>` : '<div class="empty">지금은 로컬에만 저장합니다. "+ 저장소 추가"로 FTP나 WebDAV에도 함께 올릴 수 있어요.</div>'}
    </section>

    <section class="section"><div class="section-head"><h2>백업 파일</h2>
      <div class="filters" role="group" aria-label="저장 위치">${tabs.map(([k, l]) => `<button type="button" data-btab="${k}" aria-pressed="${k === backupTab}">${l}</button>`).join("")}</div></div>
      <div class="list">${listErr ? `<div class="empty" style="border:none">${esc(listErr)}</div>` : rows || '<div class="empty" style="border:none">백업 파일이 없습니다</div>'}</div>
    </section>

    <section class="section"><div class="section-head"><div><h2>파일로 복구</h2><p>다른 PC에 받아 둔 백업 파일(.hob)이나 다른 HomeOps에서 만든 백업으로 되돌립니다.</p></div></div>
      <form class="card" id="restore-upload" novalidate>
        <div class="form-grid">
          <label class="field full">백업 파일<input type="file" name="file" accept=".hob"></label>
          <label class="field full">백업 암호 (이 HomeOps에 저장된 암호와 같으면 비워 두세요)<input type="password" name="password" autocomplete="off"></label>
        </div>
        <p class="test-result" role="status" aria-live="polite"></p>
        <div class="actions"><button type="button" class="btn danger" data-bact="upload-restore">이 파일로 복구</button></div>
      </form>
    </section>`;
}

/** 화면의 백업 설정 폼 → 저장할 값. 화면에 없는 저장소는 지금 값(꺼짐 포함)을 그대로 쓴다 */
function readBackupForms(disable) {
  const b = view._settings.backup;
  const g = readForm(view.querySelector('form[data-bk="general"]'), BK_GENERAL);
  const target = (k) => {
    if (k === disable) return { ...b[k], enabled: false };
    const f = view.querySelector(`form[data-bk="${k}"]`);
    if (!f) return b[k];
    const v = { ...readForm(f, BK_TARGETS[k].fields), enabled: true };
    if (k === "ftp") v.port = Number(v.port) || 21;
    return v;
  };
  return { ...g, keep_local: Number(g.keep_local) || 14, keep_remote: Number(g.keep_remote) || 30,
    ftp: target("ftp"), webdav: target("webdav") };
}

function startAddTarget(k) {
  view._bkAdding.add(k);
  drawBackup().then(() => {
    const f = view.querySelector(`form[data-bk="${k}"]`);
    if (f) { f.scrollIntoView({ behavior: "smooth", block: "start" }); const i = f.querySelector("input:not([type=checkbox])"); if (i) i.focus({ preventScroll: true }); }
  });
}

async function restoreDialog(where) {
  const r = await openDialog(`<form method="dialog" class="dlg" id="rbox"><h2>이 백업으로 복구할까요?</h2>
    <p>${esc(where)}</p>
    <p>지금의 계정·연결 설정·수동 등록 기기·작업 기록이 백업 시점으로 바뀝니다. 복구 직전 상태는 로컬에 자동으로 한 번 백업해 둡니다. 복구 후에는 다시 로그인해야 할 수 있습니다.</p>
    <label class="field">백업 암호 (저장된 암호와 같으면 비워 두세요)<input type="password" name="password" autocomplete="off"></label>
    <div class="dlg-foot"><button class="btn" value="cancel" formnovalidate>취소</button><button class="btn danger" value="ok">복구</button></div></form>`);
  if (r !== "ok") return null;
  return { password: $("#rbox", dlg).elements.password.value };
}

async function afterRestore(res) {
  const msg = [`${res.created ? new Date(res.created).toLocaleString("ko-KR") + " 백업으로 " : ""}복구했습니다.`];
  if (res.safety_backup) msg.push(`복구 전 상태는 ${res.safety_backup} 으로 남겨 두었습니다.`);
  if (res.warning) msg.push(res.warning);
  await openDialog(`<form method="dialog" class="dlg"><h2>복구 완료</h2>${msg.map((m) => `<p>${esc(m)}</p>`).join("")}
    <div class="dlg-foot"><button class="btn primary" value="ok">확인</button></div></form>`);
  try { await api("/api/auth/me"); route(); } catch (_) { showLogin(); }
}

view.addEventListener("click", async (e) => {
  const tab = e.target.closest("[data-btab]");
  if (tab) { backupTab = tab.dataset.btab; view.querySelector(".list").innerHTML = '<p class="skeleton" style="padding:16px">불러오는 중…</p>'; await drawBackup(); return; }
  const btn = e.target.closest("[data-bact]");
  if (!btn) return;
  const a = btn.dataset.bact;
  const form = btn.closest("form");

  if (a === "add-target") {
    const b = view._settings.backup;
    dlg.innerHTML = `<form method="dialog" class="dlg"><h2>원격 저장소 추가</h2><p>백업 파일을 함께 올릴 곳을 고르세요.</p>
      <div class="picker">${["ftp", "webdav"].map((k) => {
        const added = b[k].enabled || view._bkAdding.has(k);
        return `<button type="button" class="pick" data-add="${k}" ${added ? "disabled" : ""}><b>${BK_TARGETS[k].title}</b><small>${added ? "추가됨" : BK_TARGETS[k].desc}</small></button>`;
      }).join("")}</div>
      <div class="dlg-foot"><button class="btn" value="cancel">닫기</button></div></form>`;
    dlg.showModal();
    return;
  }
  if (a === "cancel-target") { view._bkAdding.delete(btn.dataset.k); await drawBackup(); return; }
  if (a === "remove-target") {
    const k = btn.dataset.k;
    if (!(await confirmBox(`${BK_TARGETS[k].title} 저장소를 삭제할까요?`, "이후 백업부터 이 저장소에 올리지 않습니다. 이미 올라간 백업 파일은 그대로 남습니다.", "삭제"))) return;
    try {
      view._settings = await api("/api/settings/backup", { method: "PUT", body: readBackupForms(k) });
      view._bk = await api("/api/backup");
      if (backupTab === k) backupTab = "local";
      await drawBackup();
      toast(`${BK_TARGETS[k].title} 저장소를 삭제했습니다`);
    } catch (err) { toast(err.message, true); }
    return;
  }
  if (a === "save") {
    btn.disabled = true;
    try {
      view._settings = await api("/api/settings/backup", { method: "PUT", body: readBackupForms() });
      view._bkAdding = new Set();
      view._bk = await api("/api/backup");
      await drawBackup();
      toast("백업 설정을 저장했습니다");
    } catch (err) { setResult(form, false, err.message); } finally { btn.disabled = false; }
    return;
  }
  if (a === "test") {
    btn.disabled = true; setResult(form, true, "연결하는 중…");
    try {
      const r = await api(`/api/backup/test/${btn.dataset.k}`, { method: "POST", body: readBackupForms() });
      setResult(form, r.ok, r.message);
    } catch (err) { setResult(form, false, err.message); } finally { btn.disabled = false; }
    return;
  }
  if (a === "run") {
    btn.disabled = true; btn.textContent = "백업하는 중…";
    try {
      const r = await api("/api/backup/run", { method: "POST", body: {} });
      const fails = Object.entries(r.uploads).filter(([, v]) => v !== "성공");
      toast(fails.length ? `로컬에는 저장했지만 ${fails.map(([k]) => k.toUpperCase()).join(", ")} 업로드 실패` : "백업했습니다", fails.length > 0);
      view._bk = await api("/api/backup");
      await drawBackup();
    } catch (err) { toast(err.message, true); btn.disabled = false; btn.textContent = "지금 백업"; }
    return;
  }
  if (a === "delete") {
    if (!(await confirmBox("백업 파일을 삭제할까요?", backupDate(btn.dataset.k), "삭제"))) return;
    try {
      await api(`/api/backup/local/${encodeURIComponent(btn.dataset.k)}/delete`, { method: "POST", body: { confirm: true } });
      view._bk = await api("/api/backup"); await drawBackup(); toast("삭제했습니다");
    } catch (err) { toast(err.message, true); }
    return;
  }
  if (a === "restore") {
    const where = `${{ local: "로컬", ftp: "FTP", webdav: "WebDAV" }[backupTab]} · ${backupDate(btn.dataset.k)}`;
    const ans = await restoreDialog(where);
    if (!ans) return;
    btn.disabled = true;
    try {
      const res = await api("/api/backup/restore", { method: "POST", body: { source: backupTab, name: btn.dataset.k, password: ans.password, confirm: true } });
      await afterRestore(res);
    } catch (err) { toast(err.message, true); btn.disabled = false; }
    return;
  }
  if (a === "upload-restore") {
    const f = form.elements.file.files[0];
    if (!f) { setResult(form, false, "백업 파일을 고르세요"); return; }
    if (!(await confirmBox("이 파일로 복구할까요?", `${f.name} — 지금 데이터가 백업 시점으로 바뀝니다. 복구 직전 상태는 로컬에 자동으로 백업해 둡니다.`, "복구"))) return;
    btn.disabled = true; setResult(form, true, "복구하는 중…");
    try {
      const res = await fetch("/api/backup/restore-upload", {
        method: "POST", credentials: "same-origin", body: f,
        headers: { "Content-Type": "application/octet-stream", "X-Confirm": "yes", "X-Backup-Password": encodeURIComponent(form.elements.password.value) },
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 401) { showLogin(); return; }
      if (!res.ok) throw new Error(data.detail || `복구 실패 (HTTP ${res.status})`);
      await afterRestore(data);
    } catch (err) { setResult(form, false, err.message); } finally { btn.disabled = false; }
  }
});

/* ---------- 이벤트 ---------- */
view.addEventListener("click", async (e) => {
  const btn = e.target.closest("button, [data-room]");
  if (!btn) return;
  if (btn.hasAttribute("data-refresh")) { route(); return; }
  if (btn.dataset.room) { roomFilter = btn.dataset.room; drawIntegration(); return; }
  if (btn.dataset.toggle) {
    const [source, hub, id] = btn.dataset.toggle.split("|");
    const next = btn.getAttribute("aria-checked") !== "true";
    btn.setAttribute("aria-checked", String(next));
    try {
      await api(`/api/smarthome/devices/${encodeURIComponent(hub)}/${encodeURIComponent(id)}/${next ? "on" : "off"}`, { method: "POST" });
      const dev = view._sm.devices.find((x) => x.source === source && x.hub === hub && x.id === id);
      if (dev) dev.on = next;
    } catch (err) {
      btn.setAttribute("aria-checked", String(!next));
      toast(err.message, true);
    }
    return;
  }
  const a = btn.dataset.act;
  if (!a) return;
  const k = (btn.dataset.k || "").split("|");
  switch (a) {
    case "ping-all":
      btn.disabled = true;
      try { pingCache = await api("/api/registry/devices/ping"); route(); }
      catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
      return;
    case "dev-add": return saveRow("devices", null, DEVICE_FIELDS);
    case "dev-edit": return saveRow("devices", k[0], DEVICE_FIELDS, view._devices.find((x) => String(x.id) === k[0]));
    case "dev-del": { const x = view._devices.find((v) => String(v.id) === k[0]); return deleteRow("devices", k[0], x ? x.name : "이"); }
    case "pf-add": return saveRow("platforms", null, PLATFORM_FIELDS);
    case "pf-edit": return saveRow("platforms", k[0], PLATFORM_FIELDS, view._platforms.find((x) => String(x.id) === k[0]));
    case "pf-del": { const x = view._platforms.find((v) => String(v.id) === k[0]); return deleteRow("platforms", k[0], x ? x.name : "이"); }
    case "path-add": return saveRow("paths", null, await pathFields());
    case "path-edit": return saveRow("paths", k[0], await pathFields(), view._sm.paths.find((x) => String(x.id) === k[0]));
    case "path-del": { const x = view._sm.paths.find((v) => String(v.id) === k[0]); return deleteRow("paths", k[0], x ? `${x.src} → ${x.dst}` : "이"); }
  }
});

/* ---------- 업데이트 ---------- */
let updTimer = null;

function setVersionLabel(current, available, latest) {
  const el = $("#app-version");
  if (!el) return;
  el.innerHTML = `HomeOps v${esc(current)}${available ? `<span class="new" title="v${esc(latest)}">새 버전</span>` : ""}`;
}

function mdInline(t) {
  return esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");
}

const UPD_STATE = { queued: "준비 중", running: "업데이트 중", restarting: "다시 시작하는 중", ok: "완료", failed: "실패" };

async function renderUpdate(refresh = false) {
  const st = await api(`/api/update${refresh ? "?refresh=1" : ""}`);
  view._upd = st;
  setVersionLabel(st.current, st.available, st.latest);
  const job = st.job;
  const busy = job && ["queued", "running", "restarting"].includes(job.state);
  const howto = { lxc: "LXC (install.sh)", docker: "Docker", manual: "직접 실행" }[st.mode];

  const changes = st.changelog.length ? st.changelog.map((c) => `
      <div class="row" style="flex-direction:column;align-items:stretch;gap:8px"><b>v${esc(c.version)}${c.date ? ` <small class="muted">${esc(c.date)}</small>` : ""}</b>
      <ul class="changes">${c.items.map((i) => `<li class="${i.sub ? "sub" : ""}">${mdInline(i.text)}</li>`).join("")}</ul></div>`).join("")
    : "";

  let action = "";
  if (busy) action = `<span class="badge warn">${UPD_STATE[job.state]}…</span>`;
  else if (st.available && st.can_update) action = '<button class="btn primary" data-uact="apply">지금 업데이트</button>';

  view.innerHTML = `
    <header class="page-head"><div><h1>업데이트</h1><p>GitHub(${esc(st.repo)} · ${esc(st.branch)})에 올라온 새 버전을 확인하고 이 화면에서 바로 업데이트합니다.</p></div>
      <div class="chips"><button class="btn" data-uact="check" ${busy ? "disabled" : ""}>다시 확인</button>${action}</div></header>

    ${st.error ? `<div class="alert warn"><span class="ico" aria-hidden="true">!</span><div><b>새 버전을 확인하지 못했습니다</b><p>${esc(st.error)}</p></div></div>` : ""}
    ${st.available && !st.can_update ? `<div class="alert warn"><span class="ico" aria-hidden="true">!</span><div><b>이번 한 번은 직접 업데이트해야 합니다</b><p>${esc(st.hint)}</p></div></div>` : ""}

    <div class="grid wide">
      <section class="card"><div class="card-title"><h2>지금 버전</h2></div>
        <p class="ver-big">v${esc(st.current)}</p><small class="muted">설치 방식: ${esc(howto)}</small></section>
      <section class="card"><div class="card-title"><h2>최신 버전</h2></div>
        <p class="ver-big">${st.latest ? `v${esc(st.latest)}` : "—"} ${st.latest ? `<span class="badge ${st.available ? "warn" : "ok"}">${st.available ? "새 버전 있음" : "최신"}</span>` : ""}</p>
        <small class="muted">${st.checked_at ? `확인: ${esc(new Date(st.checked_at).toLocaleString("ko-KR"))}` : ""}</small></section>
    </div>

    ${job && (busy || job.state === "failed" || job.log) ? `<section class="card"><div class="card-title"><h2>진행 상황 <span class="badge ${job.state === "failed" ? "bad" : job.state === "ok" ? "ok" : "warn"}">${UPD_STATE[job.state] || esc(job.state)}</span></h2>
      <small>${job.started ? `시작 ${esc(new Date(job.started).toLocaleString("ko-KR"))}` : ""}${job.finished ? ` · 끝 ${esc(new Date(job.finished).toLocaleString("ko-KR"))}` : ""}</small></div>
      ${job.log ? `<pre class="upd-log" id="upd-log">${esc(job.log)}</pre>` : '<p class="muted" style="margin:0">곧 시작합니다…</p>'}</section>` : ""}

    ${changes ? `<section class="section"><div class="section-head"><h2>바뀌는 점</h2></div><section class="card" style="gap:0">${changes}</section></section>` : ""}

    <p class="muted" style="margin:0;font-size:13px">업데이트하는 동안 1~2분쯤 화면이 끊깁니다. 백업 암호를 정해 두었다면 시작 전에 자동으로 백업합니다 (백업 · 복구 화면의 <i>before-update</i> 파일). 연결 설정과 데이터는 그대로 유지됩니다.</p>`;
  const lg = $("#upd-log");
  if (lg) lg.scrollTop = lg.scrollHeight;
  clearTimeout(updTimer);
  if (busy) updTimer = setTimeout(() => pollUpdate(st.current), 2000);
}

/** 업데이트 중: 서버가 다시 뜨고 버전이 바뀔 때까지 지켜본다 */
async function pollUpdate(oldVersion) {
  if (view.dataset.route !== "update") return;
  try {
    const h = await (await fetch("/api/health", { cache: "no-store" })).json();
    if (h.version !== oldVersion) {
      toast(`v${h.version}(으)로 업데이트했습니다`);
      setTimeout(() => location.reload(), 800);
      return;
    }
    await renderUpdate();
  } catch (_) {
    // 다시 시작하는 중이라 응답이 없음
    updTimer = setTimeout(() => pollUpdate(oldVersion), 2000);
  }
}

view.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-uact]");
  if (!b) return;
  const st = view._upd;
  if (b.dataset.uact === "check") {
    b.disabled = true;
    try { await renderUpdate(true); toast(view._upd.available ? `새 버전 v${view._upd.latest}이(가) 있습니다` : "최신 버전입니다"); }
    catch (err) { toast(err.message, true); b.disabled = false; }
    return;
  }
  if (b.dataset.uact === "apply") {
    if (!await confirmBox(`v${st.latest}(으)로 업데이트`, "1~2분쯤 HomeOps가 다시 시작됩니다. 진행할까요?", "업데이트", false)) return;
    b.disabled = true;
    try {
      const r = await api("/api/update/apply", { method: "POST", body: { confirm: true } });
      toast(r.message + (r.backup ? " · 백업 완료" : ""));
      await renderUpdate();
    } catch (err) { toast(err.message, true); b.disabled = false; }
  }
});

/* ---------- 라우팅 ---------- */
const ROUTES = { infra: renderInfra, hubs: renderHubs, integration: renderIntegration, log: renderLog, settings: renderSettings, backup: renderBackup, update: () => renderUpdate(true) };  // 업데이트 화면은 열 때마다 GitHub 확인

async function route() {
  const name = (location.hash.replace(/^#\/?/, "") || "integration").split("?")[0];
  const fn = ROUTES[name] || renderIntegration;
  document.querySelectorAll("[data-route]").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
  if (!view.innerHTML || view.dataset.route !== name) view.innerHTML = '<p class="skeleton">불러오는 중…</p>';
  view.dataset.route = name;
  try {
    await fn();
  } catch (e) {
    if (!(e instanceof ApiError && e.message === "로그인이 필요합니다")) {
      view.innerHTML = `<div class="empty">불러오지 못했습니다: ${esc(e.message)} <button class="linklike" data-refresh>다시 시도</button></div>`;
    }
  }
}

window.addEventListener("hashchange", () => { view.innerHTML = ""; route(); view.focus(); });

(async () => {
  api("/api/health").then((h) => setVersionLabel(h.version, false)).catch(() => {});
  try {
    const st = await api("/api/auth/status");
    if (st.needs_setup) { showSetup(); return; }
    await api("/api/auth/me");
    showApp();
    route();
    checkUpdateQuietly();
  } catch (_) { showLogin(); }
})();

/** 로그인 후 새 버전이 있으면 왼쪽 아래 버전 옆에 표시 (서버가 6시간마다만 GitHub 확인) */
function checkUpdateQuietly() {
  api("/api/update").then((u) => setVersionLabel(u.current, u.available, u.latest)).catch(() => {});
}
