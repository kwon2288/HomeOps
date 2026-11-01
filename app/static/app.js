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
    if (f.type === "select") return `<label class="${cls}">${esc(f.label)}<select name="${f.name}">${f.options.map((o) => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
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

/** 버튼 클릭 → 확인 → API 호출 → 새로 고침 */
async function act(btn, { title, message, path, method = "POST", confirm = true, done = "완료했습니다", reload = true }) {
  if (confirm && !(await confirmBox(title, message))) return;
  btn.disabled = true;
  try {
    const r = await api(path, { method, body: confirm ? { confirm: true } : {} });
    const extra = r && r.result && typeof r.result === "string" ? ` (${r.result})` : "";
    toast(done + extra);
    if (reload) setTimeout(route, 800);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

function statusBadge(sys, okLabel = "온라인") {
  if (!sys.configured) return '<span class="badge"><span class="dot"></span>연결 전</span>';
  if (sys.online) return `<span class="badge ok"><span class="dot ok"></span>${okLabel}</span>`;
  return `<span class="badge bad" title="${esc(sys.error || "")}"><span class="dot bad"></span>오류</span>`;
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
    showApp();
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
    showApp();
    route();
  } catch (err) {
    $("#login-err").textContent = err.message;
  }
});

$("#logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  showLogin();
});

/* ---------- 인프라 ---------- */
async function renderInfra() {
  const d = await api("/api/infra");
  view.innerHTML = `
    <header class="page-head"><div><h1>인프라</h1><p>Synology NAS · Proxmox VE · Portainer</p></div>
      <button class="btn accent" data-refresh>새로 고침</button></header>
    <div class="grid wide">${nasPanel(d.nas)}${pvePanel(d.proxmox)}${ptnPanel(d.portainer)}</div>`;
}

function notConfigured(name, how) {
  return `<section class="card"><div class="card-head"><div class="card-title"><h2>${esc(name)}</h2></div>
    <span class="badge"><span class="dot"></span>연결 전</span></div>
    <div class="howto"><b class="howto-title">연결 방법</b>${how}</div></section>`;
}

function errorPanel(name, sys) {
  return `<section class="card"><div class="card-head"><div class="card-title"><h2>${esc(name)}</h2></div>${statusBadge(sys)}</div>
    <div class="empty">연결하지 못했습니다: ${esc(sys.error)}</div></section>`;
}

function nasPanel(sys) {
  if (!sys.configured) return notConfigured("Synology NAS", "DSM 주소와 2단계 인증이 없는 전용 계정을 <a href=\"#/settings\">연결 설정</a>에서 입력하세요.");
  if (!sys.online) return errorPanel("Synology NAS", sys);
  const n = sys.data;
  const vol = n.volumes[0] || {};
  return `<section class="card">
    <div class="card-head"><div class="card-title"><h2>Synology NAS</h2><small>${esc(n.model)} · ${esc(String(n.version || "").startsWith("DSM") ? n.version : "DSM " + (n.version || "—"))} · 가동 ${uptime(n.uptime)}</small></div>${statusBadge(sys)}</div>
    <dl class="metrics">
      <div class="metric"><dt>볼륨 사용률</dt><dd>${pct(vol.used_pct)}</dd>${bar(vol.used_pct)}</div>
      <div class="metric"><dt>CPU</dt><dd>${pct(n.cpu_pct)}</dd>${bar(n.cpu_pct)}</div>
      <div class="metric"><dt>메모리</dt><dd>${pct(n.mem_pct)}</dd>${bar(n.mem_pct)}</div>
      <div class="metric"><dt>디스크 상태</dt><dd>${esc(dash(n.disk_health))}</dd></div>
    </dl>
    <div class="rows"><span class="rows-title">볼륨</span>
      ${n.volumes.map((v) => `<div class="row"><div class="row-main"><b>${esc(v.name)}</b><small>${v.status === "normal" ? "정상" : esc(v.status)} · ${dash(v.total_tb, "TB")}</small></div><span class="pill ${v.used_pct >= 85 ? "warn" : ""}">${pct(v.used_pct)}</span></div>`).join("")}
    </div>
    <div class="rows"><span class="rows-title">디스크</span>
      ${n.disks.map((x) => `<div class="row"><div class="row-main"><b>${esc(x.name)}</b><small>${esc(x.model)} · ${dash(x.temp, "°C")}</small></div><span class="pill ${x.status === "normal" ? "ok" : "warn"}">${x.status === "normal" ? "정상" : esc(x.status || "—")}</span></div>`).join("")}
    </div>
    <div class="actions"><button class="btn danger" data-act="nas-reboot">재부팅</button></div>
  </section>`;
}

function pvePanel(sys) {
  if (!sys.configured) return notConfigured("Proxmox VE", "Datacenter → Permissions → API Tokens 에서 토큰을 만들고 <a href=\"#/settings\">연결 설정</a>에서 입력하세요.");
  if (!sys.online) return errorPanel("Proxmox VE", sys);
  const p = sys.data;
  const node = p.nodes[0] || {};
  const guests = p.guests.map((g) => {
    const running = g.status === "running";
    const key = `${esc(g.node)}|${esc(g.type)}|${g.vmid}`;
    return `<div class="row"><div class="row-main"><b>${esc(g.name)}</b><small>${g.type === "lxc" ? "LXC" : "VM"} ${g.vmid} · ${esc(g.node)} · ${running ? `CPU ${pct(g.cpu_pct)} · 메모리 ${pct(g.mem_pct)}` : "중지됨"}</small></div>
      <div class="row-act">${running
        ? `<button class="btn sm" data-act="pve-reboot" data-k="${key}">재시작</button><button class="btn sm danger" data-act="pve-shutdown" data-k="${key}">종료</button>`
        : `<button class="btn sm" data-act="pve-start" data-k="${key}">시작</button>`}
        <button class="btn sm" data-act="pve-snap" data-k="${key}">스냅샷</button><button class="btn sm" data-act="pve-backup" data-k="${key}">백업</button></div></div>`;
  }).join("");
  return `<section class="card">
    <div class="card-head"><div class="card-title"><h2>Proxmox VE</h2><small>${esc(node.name || "")} · PVE ${esc(p.version)} · 가동 ${uptime(node.uptime)}</small></div>${statusBadge(sys)}</div>
    <dl class="metrics">
      <div class="metric"><dt>노드 CPU</dt><dd>${pct(node.cpu_pct)}</dd>${bar(node.cpu_pct)}</div>
      <div class="metric"><dt>노드 메모리</dt><dd>${pct(node.mem_pct)}</dd>${bar(node.mem_pct)}</div>
      <div class="metric"><dt>루트 디스크</dt><dd>${pct(node.disk_pct)}</dd>${bar(node.disk_pct)}</div>
      <div class="metric"><dt>실행 중 VM/LXC</dt><dd>${p.running} / ${p.guests.length}</dd></div>
    </dl>
    <div class="rows"><span class="rows-title">VM · LXC</span>${guests || '<div class="empty">게스트가 없습니다</div>'}</div>
  </section>`;
}

function ptnPanel(sys) {
  if (!sys.configured) return notConfigured("Portainer", "My account → Access tokens 에서 토큰을 만들고 <a href=\"#/settings\">연결 설정</a>에서 입력하세요.");
  if (!sys.online) return errorPanel("Portainer", sys);
  const p = sys.data;
  const rows = p.containers.map((c) => {
    const running = c.state === "running";
    const key = `${c.endpoint}|${esc(c.id)}|${esc(c.name)}`;
    return `<div class="row"><div class="row-main"><b>${esc(c.name)}</b><small>${esc(c.image)} · ${esc(c.status)}${c.stack ? ` · 스택 ${esc(c.stack)}` : ""}</small></div>
      <div class="row-act">${running
        ? `<button class="btn sm" data-act="ct-restart" data-k="${key}">재시작</button><button class="btn sm danger" data-act="ct-stop" data-k="${key}">중지</button>`
        : `<button class="btn sm" data-act="ct-start" data-k="${key}">시작</button>`}
        <button class="btn sm" data-act="ct-logs" data-k="${key}">로그</button></div></div>`;
  }).join("");
  const stacks = p.stacks.map((s) => `<div class="row"><div class="row-main"><b>${esc(s.name)}</b><small>엔드포인트 ${s.endpoint}</small></div>
    <div class="row-act"><span class="pill ${s.active ? "ok" : ""}">${s.active ? "실행 중" : "중지"}</span>
    <button class="btn sm ${s.active ? "danger" : ""}" data-act="${s.active ? "stack-stop" : "stack-start"}" data-k="${s.id}|${s.endpoint}|${esc(s.name)}">${s.active ? "중지" : "시작"}</button></div></div>`).join("");
  return `<section class="card">
    <div class="card-head"><div class="card-title"><h2>Portainer</h2><small>Portainer ${esc(p.version)}</small></div>${statusBadge(sys)}</div>
    <dl class="metrics">
      <div class="metric"><dt>실행 중</dt><dd>${p.running}</dd></div>
      <div class="metric"><dt>중지됨</dt><dd>${p.stopped}</dd></div>
      <div class="metric"><dt>스택</dt><dd>${p.stacks.length}</dd></div>
      <div class="metric"><dt>전체 컨테이너</dt><dd>${p.containers.length}</dd></div>
    </dl>
    <div class="rows"><span class="rows-title">컨테이너 (중지된 것 먼저)</span>${rows || '<div class="empty">컨테이너가 없습니다</div>'}</div>
    ${stacks ? `<div class="rows"><span class="rows-title">스택</span>${stacks}</div>` : ""}
  </section>`;
}

/* ---------- 스마트홈 허브 ---------- */
const ROLE_OPTIONS = ["HomeKit 홈 허브", "Thread 보더 라우터", "Matter 컨트롤러", "Matter 브리지", "Zigbee 코디네이터", "음성 비서", "브리지", "디스플레이", "가전 허브"];
const PLATFORM_OPTIONS = ["HomeKit", "Google Home", "SmartThings", "Aqara", "Homey", "LG ThinQ", "Hubitat", "Home Assistant", "기타"];
let pingCache = {};

async function renderHubs() {
  const [hubs, devices, platforms, backups] = await Promise.all([
    api("/api/hubs"), api("/api/registry/devices"), api("/api/registry/platforms"), api("/api/hubs/hubitat/backups"),
  ]);
  const cards = [
    ...(hubs.hubitat.length ? hubs.hubitat.map(hubitatCard) : ['<article class="card"><div class="card-head"><div class="card-title"><b>Hubitat</b></div><span class="badge"><span class="dot"></span>연결 전</span></div><div class="howto"><b class="howto-title">연결 방법</b>허브마다 Maker API 앱을 설치하고 <a href="#/settings">연결 설정</a>에서 허브를 추가하세요.</div></article>']),
    haCard(hubs.home_assistant),
    hbCard(hubs.homebridge),
  ].join("");
  const online = hubs.hubitat.filter((h) => h.online).length + (hubs.home_assistant.online ? 1 : 0) + (hubs.homebridge.online ? 1 : 0);
  const total = hubs.hubitat.length + (hubs.home_assistant.configured ? 1 : 0) + (hubs.homebridge.configured ? 1 : 0);
  view.innerHTML = `
    <header class="page-head"><div><h1>스마트홈 허브</h1><p>API로 관리하는 허브와, 연동은 안 되지만 역할을 기록해 두는 기기</p></div>
      <button class="btn accent" data-refresh>새로 고침</button></header>
    <section class="section"><div class="section-head"><h2>허브 상태 · API 연동</h2><span class="muted" style="font-size:13px">${total}개 중 ${online}개 응답</span></div>
      <div class="grid">${cards}</div>
      ${backups.length ? `<details class="card"><summary style="cursor:pointer;font-size:14px">Hubitat 백업 파일 ${backups.length}개</summary>
        <div class="rows">${backups.map((b) => `<div class="row"><div class="row-main"><b class="mono">${esc(b.file)}</b><small>${(b.size / 1048576).toFixed(1)} MB · ${new Date(b.mtime * 1000).toLocaleString("ko-KR")}</small></div>
        <a class="btn sm" style="display:inline-flex;align-items:center;text-decoration:none" href="/api/hubs/hubitat/backups/${encodeURIComponent(b.file)}" download>받기</a></div>`).join("")}</div></details>` : ""}
    </section>
    <section class="section"><div class="section-head"><div><h2>수동 등록 기기</h2><p>API 연동은 없지만 IP를 넣으면 응답 여부(ping)를 확인합니다</p></div>
      <div class="chips"><button class="btn" data-act="ping-all">전체 응답 확인</button><button class="btn accent" data-act="dev-add">+ 기기 등록</button></div></div>
      <div class="grid mid">${devices.map(manualCard).join("") || '<div class="empty">등록된 기기가 없습니다</div>'}</div>
    </section>
    <section class="section"><div class="section-head"><div><h2>플랫폼 역할</h2><p>플랫폼마다 무엇을 맡기는지</p></div>
      <button class="btn" data-act="pf-add">플랫폼 추가</button></div>
      <div class="table-wrap"><table class="stack-table full" style="min-width:860px"><thead><tr><th scope="col">플랫폼</th><th scope="col">용도</th><th scope="col">주요 기능 · 담당 기기</th><th scope="col">허브 · 연결 경로</th><th scope="col"><span class="muted">편집</span></th></tr></thead>
      <tbody>${platforms.map((p) => `<tr><th scope="row">${esc(p.name)}</th><td><span class="tag">${esc(p.use)}</span></td><td>${esc(p.features)}</td><td>${esc(p.path)}</td>
        <td class="cell-actions" style="white-space:nowrap"><button class="btn sm" data-act="pf-edit" data-k="${p.id}">편집</button> <button class="btn sm danger" data-act="pf-del" data-k="${p.id}" aria-label="${esc(p.name)} 삭제">삭제</button></td></tr>`).join("")}</tbody></table></div>
    </section>`;
  view._devices = devices;
  view._platforms = platforms;
}

function hubitatCard(h) {
  const d = h.data || {};
  const fw = d.firmware || "—";
  const mem = d.free_memory_kb != null ? `${Math.round(d.free_memory_kb / 1024)} MB` : "—";
  return `<article class="card"><div class="card-head"><div class="card-title"><b>${esc(d.name)}</b><small>${esc(d.role ? d.role + " · " : "")}${esc(String(d.url || "").replace(/^https?:\/\//, ""))}</small></div>${statusBadge(h)}</div>
    <dl class="kv"><div><dt>펌웨어</dt><dd>${esc(fw)}</dd></div><div><dt>기기</dt><dd>${dash(d.device_count)}</dd></div>
    <div><dt>여유 메모리</dt><dd>${mem}</dd></div><div><dt>내부 온도</dt><dd>${dash(d.temperature_c, "°C")}</dd></div></dl>
    <div class="actions"><button class="btn" data-act="hub-backup" data-k="${esc(d.id)}|${esc(d.name)}">백업</button>
    <button class="btn danger" data-act="hub-reboot" data-k="${esc(d.id)}|${esc(d.name)}">재부팅</button></div></article>`;
}

function haCard(sys) {
  const d = sys.data || {};
  return `<article class="card"><div class="card-head"><div class="card-title"><b>Home Assistant</b><small>HA OS${d.location ? " · " + esc(d.location) : ""}</small></div>${statusBadge(sys)}</div>
    ${sys.configured ? `<dl class="kv"><div><dt>Core</dt><dd>${dash(d.version)}</dd></div><div><dt>엔티티</dt><dd>${dash(d.entity_count)}</dd></div>
    <div><dt>업데이트</dt><dd>${dash(d.update_count)}</dd></div><div><dt>상태</dt><dd>${sys.online ? "정상" : esc(sys.error)}</dd></div></dl>
    <div class="actions"><button class="btn" data-act="ha-backup">백업</button><button class="btn danger" data-act="ha-restart">재시작</button></div>`
    : '<div class="howto"><b class="howto-title">연결 방법</b>프로필 → 보안 → 장기 액세스 토큰을 만들어 <a href="#/settings">연결 설정</a>에서 입력하세요.</div>'}</article>`;
}

function hbCard(sys) {
  const d = sys.data || {};
  return `<article class="card"><div class="card-head"><div class="card-title"><b>Homebridge</b><small>config-ui-x</small></div>${statusBadge(sys, d.running === false ? "정지됨" : "온라인")}</div>
    ${sys.configured ? `<dl class="kv"><div><dt>버전</dt><dd>${dash(d.version)}</dd></div><div><dt>플러그인</dt><dd>${dash(d.plugin_count)}</dd></div>
    <div><dt>액세서리</dt><dd>${d.insecure_mode ? dash(d.accessory_count) : "insecure 모드 필요"}</dd></div><div><dt>상태</dt><dd>${sys.online ? (d.running ? "실행 중" : "정지") : esc(sys.error)}</dd></div></dl>
    <div class="actions"><button class="btn danger" data-act="hb-restart">재시작</button></div>`
    : '<div class="howto"><b class="howto-title">연결 방법</b>Homebridge UI 계정을 <a href="#/settings">연결 설정</a>에서 입력하세요. 액세서리 목록은 insecure 모드(-I)에서만 보입니다.</div>'}</article>`;
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
const PATH_FIELDS = [
  { name: "src", label: "출발", required: true, placeholder: "예: SmartThings" },
  { name: "dst", label: "도착", required: true, placeholder: "예: Hubitat Main" },
  { name: "via", label: "연동 방식", full: true, placeholder: "예: HubiThings Replica" },
  { name: "check_ref", label: "상태 확인 대상", full: true, placeholder: "hubitat:main · homeassistant · homebridge (비우면 확인 안 함)" },
];

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
  const d = await api("/api/smarthome");
  view._sm = d;
  drawIntegration();
}

function drawIntegration() {
  const d = view._sm;
  const rooms = ["전체", ...new Set(d.devices.map((x) => x.room))];
  if (!rooms.includes(roomFilter)) roomFilter = "전체";
  const shown = d.devices.filter((x) => roomFilter === "전체" || x.room === roomFilter);
  const statusChip = { ok: '<span class="badge ok">응답 중</span>', down: '<span class="badge bad">응답 없음</span>', unknown: '<span class="badge">연결 전</span>', unchecked: '<span class="badge">확인 안 함</span>' };
  const away = (d.mode || "").toLowerCase() === "away";
  view.innerHTML = `
    <header class="page-head"><div><h1>스마트홈 연동</h1><p>플랫폼 간 연동 경로와 기기 제어</p></div>
      <div class="chips">
        <span class="chip"><span class="dot ${away ? "warn" : "ok"}"></span>모드 · ${esc(d.mode || "—")}</span>
        <span class="chip">HSM · ${esc(d.hsm || "—")}</span>
        <button class="btn accent" data-refresh>새로 고침</button></div></header>
    <section class="section"><div class="section-head"><div><h2>연동 경로</h2><p>어느 플랫폼이 어떤 방식으로 어디에 연결되는지</p></div>
      <button class="btn" data-act="path-add">경로 추가</button></div>
      <div class="table-wrap"><table class="stack-table" style="min-width:720px"><thead><tr><th scope="col">출발</th><th scope="col">연동 방식</th><th scope="col">도착</th><th scope="col">상태</th><th scope="col"><span class="muted">편집</span></th></tr></thead>
      <tbody>${d.paths.map((p) => `<tr><th scope="row">${esc(p.src)}</th><td><span class="path-arrow" aria-hidden="true">→ </span>${esc(p.via)}</td><td><span class="path-arrow" aria-hidden="true">→ </span>${esc(p.dst)}</td>
        <td>${statusChip[p.status] || statusChip.unknown}</td>
        <td class="cell-actions" style="white-space:nowrap"><button class="btn sm" data-act="path-edit" data-k="${p.id}">편집</button> <button class="btn sm danger" data-act="path-del" data-k="${p.id}">삭제</button></td></tr>`).join("")}</tbody></table></div>
    </section>
    <div class="split">
      <section class="section grow"><div class="section-head"><h2>기기 제어</h2>
        <div class="filters" role="group" aria-label="방 필터">${rooms.map((r) => `<button type="button" data-room="${esc(r)}" aria-pressed="${r === roomFilter}">${esc(r)}</button>`).join("")}</div></div>
        <div class="legend"><span><span class="src HE">HE</span>Hubitat</span><span><span class="src HA">HA</span>Home Assistant</span><span><span class="src HB">HB</span>Homebridge → HomeKit 노출</span></div>
        <div class="list">${shown.map(deviceRow).join("") || '<div class="empty" style="border:none">표시할 기기가 없습니다. <a href="#/settings">연결 설정</a>에서 Hubitat Maker API나 Home Assistant를 연결하세요.</div>'}</div>
        <span class="muted" style="font-size:12px">표시 ${shown.length}개 · 전체 ${d.devices.length}개</span>
      </section>
      <aside class="rail" aria-labelledby="al-h"><h2 id="al-h" style="margin:0;font-size:17px">확인 필요</h2>
        ${d.alerts.map((a) => `<div class="alert ${a.kind}"><span class="ico" aria-hidden="true">${a.kind === "down" ? "×" : "!"}</span><div><b>${esc(a.title)}</b><p>${esc(a.body)}</p></div></div>`).join("") || '<div class="empty">지금은 확인할 것이 없습니다</div>'}
      </aside>
    </div>`;
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

const SECTION_DEFS = [
  {
    key: "home_assistant", group: "hub", title: "Home Assistant", sub: "REST API · 장기 액세스 토큰",
    help: "HA 프로필 → 보안 → <b>장기 액세스 토큰</b>을 만들어 붙여 넣으세요. 백업은 HA OS(Supervisor) 백업을 씁니다.",
    fields: [
      { name: "url", label: "주소", ph: "http://192.168.0.x:8123", full: true },
      { name: "token", label: "장기 액세스 토큰", secret: true, full: true },
      { name: "verify_ssl", label: "HTTPS 인증서 검증", type: "bool", def: true },
    ],
  },
  {
    key: "homebridge", group: "hub", title: "Homebridge", sub: "config-ui-x 로그인",
    help: "Homebridge UI에 로그인하는 계정입니다. HomeKit 노출 배지와 액세서리 수는 Homebridge를 <b>insecure 모드(-I)</b>로 실행해야 보입니다.",
    fields: [
      { name: "url", label: "주소", ph: "http://192.168.0.x:8581", full: true },
      { name: "username", label: "아이디", ph: "admin" },
      { name: "password", label: "비밀번호", secret: true },
      { name: "verify_ssl", label: "HTTPS 인증서 검증", type: "bool", def: true },
    ],
  },
  {
    key: "synology", group: "infra", title: "Synology NAS", sub: "DSM Web API",
    help: "2단계 인증을 끈 <b>HomeOps 전용 계정</b>을 만들어 쓰세요. 재부팅·스토리지 조회에는 관리자 그룹 권한이 필요합니다.",
    fields: [
      { name: "url", label: "주소", ph: "https://192.168.0.x:5001", full: true },
      { name: "username", label: "아이디", ph: "homeops" },
      { name: "password", label: "비밀번호", secret: true },
      { name: "verify_ssl", label: "HTTPS 인증서 검증 (자체 서명 인증서면 끄기)", type: "bool", def: false },
    ],
  },
  {
    key: "proxmox", group: "infra", title: "Proxmox VE", sub: "API 토큰",
    help: "Datacenter → Permissions → <b>API Tokens</b>에서 만든 토큰입니다. 토큰 ID는 <code>사용자@realm!토큰이름</code> 형식이에요. 권장 권한: VM.Audit, VM.PowerMgmt, VM.Snapshot, VM.Backup, Datastore.Audit, Datastore.AllocateSpace, Sys.Audit",
    fields: [
      { name: "url", label: "주소", ph: "https://192.168.0.x:8006", full: true },
      { name: "token_id", label: "토큰 ID", ph: "homeops@pve!dashboard" },
      { name: "token_secret", label: "토큰 Secret", secret: true },
      { name: "backup_storage", label: "백업 저장소", ph: "local", def: "local" },
      { name: "verify_ssl", label: "HTTPS 인증서 검증 (자체 서명 인증서면 끄기)", type: "bool", def: false },
    ],
  },
  {
    key: "portainer", group: "infra", title: "Portainer", sub: "Access Token",
    help: "Portainer → My account → <b>Access tokens</b>에서 만든 토큰입니다.",
    fields: [
      { name: "url", label: "주소", ph: "https://192.168.0.x:9443", full: true },
      { name: "api_key", label: "Access Token", secret: true, full: true },
      { name: "verify_ssl", label: "HTTPS 인증서 검증 (자체 서명 인증서면 끄기)", type: "bool", def: false },
    ],
  },
];

function inputHtml(f, value, idPrefix) {
  const id = `${idPrefix}-${f.name}`;
  if (f.type === "bool") {
    const on = value === undefined || value === null ? f.def : value;
    return `<label class="field full" style="flex-direction:row;align-items:center;gap:10px;color:var(--text)"><input type="checkbox" name="${f.name}" ${on ? "checked" : ""} style="width:20px;height:20px;accent-color:var(--accent)">${esc(f.label)}</label>`;
  }
  const isSet = f.secret && value === MASK;
  const v = f.secret ? "" : (value ?? f.def ?? "");
  const ph = isSet ? "저장됨 · 바꿀 때만 입력" : (f.ph || "");
  return `<label class="field${f.full ? " full" : ""}" for="${id}"><span class="field-label">${esc(f.label)}${isSet ? ' <span class="badge ok">저장됨</span>' : ""}</span>
    <input id="${id}" name="${f.name}" ${f.secret ? 'type="password" autocomplete="new-password"' : 'autocomplete="off"'} ${f.type === "number" ? 'inputmode="numeric"' : ""} value="${esc(v)}" placeholder="${esc(ph)}"></label>`;
}

function readForm(form, fields) {
  const out = {};
  for (const f of fields) {
    const el = form.elements[f.name];
    if (f.type === "bool") out[f.name] = el.checked;
    else out[f.name] = el.value.trim();
  }
  return out;
}

function sectionCard(def, value) {
  const configured = value !== null && value !== undefined;
  return `<form class="card" data-section="${def.key}" novalidate>
    <div class="card-head"><div class="card-title"><h2>${esc(def.title)}</h2><small>${esc(def.sub)}</small></div>
      ${configured ? '<span class="badge ok"><span class="dot ok"></span>저장됨</span>' : '<span class="badge"><span class="dot"></span>연결 전</span>'}</div>
    <div class="howto">${def.help}</div>
    <div class="form-grid">${def.fields.map((f) => inputHtml(f, configured ? value[f.name] : undefined, def.key)).join("")}</div>
    <p class="test-result" role="status" aria-live="polite"></p>
    <div class="actions">
      <button type="button" class="btn" data-sact="test">연결 테스트</button>
      <button type="button" class="btn primary" data-sact="save">저장</button>
      ${configured ? '<button type="button" class="btn danger" data-sact="remove">연결 해제</button>' : ""}
    </div></form>`;
}

const HUB_FIELDS = [
  { name: "name", label: "이름", ph: "Hubitat Main" },
  { name: "id", label: "ID (영문 소문자)", ph: "main" },
  { name: "role", label: "역할", ph: "예: Zigbee 전용" },
  { name: "url", label: "허브 주소", ph: "http://192.168.0.80" },
  { name: "app_id", label: "Maker API App ID", ph: "예: 12", type: "number" },
  { name: "token", label: "Maker API Access Token", secret: true },
  { name: "login_user", label: "허브 로그인 아이디 (로그인 보안을 켠 경우만)", ph: "비워 두면 사용 안 함" },
  { name: "login_password", label: "허브 로그인 비밀번호", secret: true },
];

function hubForm(h, i) {
  const v = {
    name: h.name, id: h.id, role: h.role, url: h.url,
    app_id: h.maker_api ? h.maker_api.app_id : "", token: h.maker_api ? h.maker_api.token : "",
    login_user: h.login ? h.login.username : "", login_password: h.login ? h.login.password : "",
  };
  const isNew = !h.orig_id;
  return `<form class="card" data-hub="${i}" novalidate>
    <div class="card-head"><div class="card-title"><h2>${esc(h.name || "새 허브")}</h2><small>${esc(h.url || "주소 입력 전")}</small></div>
      ${isNew ? '<span class="badge warn">저장 전</span>' : '<span class="badge ok"><span class="dot ok"></span>저장됨</span>'}</div>
    <div class="form-grid">${HUB_FIELDS.map((f) => inputHtml(f, v[f.name], `hub${i}`)).join("")}</div>
    <p class="test-result" role="status" aria-live="polite"></p>
    <div class="actions">
      <button type="button" class="btn" data-sact="hub-test">연결 테스트</button>
      <button type="button" class="btn primary" data-sact="hub-save">저장</button>
      <button type="button" class="btn danger" data-sact="hub-remove">삭제</button>
    </div></form>`;
}

function readHub(form, i) {
  const r = readForm(form, HUB_FIELDS);
  const appId = r.app_id ? Number(r.app_id) : null;
  return {
    orig_id: view._hubs[i].orig_id || null,
    id: r.id, name: r.name, role: r.role, url: r.url,
    maker_api: appId || r.token ? { app_id: appId || 0, token: r.token } : null,
    login: r.login_user ? { username: r.login_user, password: r.login_password } : null,
  };
}

async function renderSettings() {
  const [s, me] = await Promise.all([api("/api/settings"), api("/api/auth/me")]);
  view._settings = s;
  view._hubs = s.hubitat.map((h) => ({ ...h, orig_id: h.id }));
  drawSettings(me);
}

function drawSettings(me) {
  const s = view._settings;
  me = me || view._me;
  view._me = me;
  const byGroup = (g) => SECTION_DEFS.filter((d) => d.group === g).map((d) => sectionCard(d, s[d.key])).join("");
  view.innerHTML = `
    <header class="page-head"><div><h1>연결 설정</h1><p>허브와 서버의 주소·토큰을 입력하세요. 토큰과 비밀번호는 암호화되어 저장되고 화면에 다시 표시되지 않습니다.</p></div>
      <a class="btn" style="display:inline-flex;align-items:center;text-decoration:none" href="#/log">작업 기록</a></header>

    <section class="section"><div class="section-head"><div><h2>Hubitat 허브</h2>
      <p>허브마다 Apps → Add Built-In App → <b>Maker API</b>를 설치하고, "Allow Access via Local IP Address"를 켠 뒤 관리할 기기를 고르세요. 예시 URL의 <code>/apps/api/<b>App ID</b>/…?access_token=<b>토큰</b></code>을 아래에 넣습니다.</p></div>
      <button type="button" class="btn accent" data-sact="hub-add">+ 허브 추가</button></div>
      <div class="grid wide">${view._hubs.map(hubForm).join("") || '<div class="empty">아직 허브가 없습니다. "+ 허브 추가"를 누르세요.</div>'}</div>
    </section>

    <section class="section"><div class="section-head"><h2>스마트홈 서비스</h2></div>
      <div class="grid wide">${byGroup("hub")}</div></section>

    <section class="section"><div class="section-head"><h2>인프라</h2></div>
      <div class="grid wide">${byGroup("infra")}</div></section>

    <section class="section"><div class="section-head"><h2>알림 · 계정</h2></div>
      <div class="grid wide">
        <form class="card" data-section="alerts" novalidate>
          <div class="card-title"><h2>알림 기준</h2><small>스마트홈 연동 화면의 "확인 필요"</small></div>
          <div class="form-grid">${inputHtml({ name: "battery_warn", label: "배터리 경고 기준 (%)", type: "number" }, s.alerts.battery_warn, "alerts")}</div>
          <p class="test-result" role="status" aria-live="polite"></p>
          <div class="actions"><button type="button" class="btn primary" data-sact="save">저장</button></div>
        </form>
        <form class="card" id="pw-form" novalidate>
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
    </section>`;
}

function setResult(form, ok, msg) {
  const p = form.querySelector(".test-result");
  p.textContent = msg;
  p.className = "test-result " + (ok ? "ok" : "bad");
}

async function saveHubs(btn, message) {
  const forms = [...view.querySelectorAll("form[data-hub]")];
  const hubs = forms.map((f) => readHub(f, Number(f.dataset.hub)));
  btn.disabled = true;
  try {
    const s = await api("/api/settings/hubitat", { method: "PUT", body: hubs });
    view._settings = s;
    view._hubs = s.hubitat.map((h) => ({ ...h, orig_id: h.id }));
    drawSettings();
    toast(message);
  } catch (err) {
    const form = btn.closest("form");
    if (form) setResult(form, false, err.message);
    toast(err.message, true);
  } finally {
    btn.disabled = false;
  }
}

view.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-sact]");
  if (!btn) return;
  const form = btn.closest("form");
  const a = btn.dataset.sact;

  if (a === "hub-add") {
    // 입력 중인 다른 허브 값은 그대로 두고 카드만 추가
    view.querySelectorAll("form[data-hub]").forEach((f) => {
      const i = Number(f.dataset.hub);
      const prev = view._hubs[i];
      const cur = { ...readHub(f, i), orig_id: prev.orig_id };
      // 비워 둔 비밀값은 "저장됨" 표시를 유지
      if (cur.maker_api && !cur.maker_api.token && prev.maker_api && prev.maker_api.token === MASK) cur.maker_api.token = MASK;
      if (cur.login && !cur.login.password && prev.login && prev.login.password === MASK) cur.login.password = MASK;
      view._hubs[i] = cur;
    });
    const n = view._hubs.length + 1;
    view._hubs.push({ id: n === 1 ? "main" : `hub${n}`, name: "", role: "", url: "http://", maker_api: null, login: null, orig_id: null });
    drawSettings();
    const last = view.querySelector("form[data-hub]:last-of-type input[name=name]");
    if (last) last.focus();
    return;
  }
  if (a === "hub-save") return saveHubs(btn, "허브 설정을 저장했습니다");
  if (a === "hub-remove") {
    const i = Number(form.dataset.hub);
    const h = view._hubs[i];
    if (h.orig_id && !(await confirmBox("허브를 삭제할까요?", `${h.name || h.id} 연결 설정을 지웁니다. 허브 자체에는 영향이 없습니다.`, "삭제"))) return;
    form.remove();
    if (!h.orig_id) { view._hubs.splice(i, 1); drawSettings(); return; }
    return saveHubs(btn, "허브를 삭제했습니다");
  }
  if (a === "hub-test") {
    const hub = readHub(form, Number(form.dataset.hub));
    btn.disabled = true; setResult(form, true, "연결하는 중…");
    try {
      const r = await api("/api/settings/test/hubitat", { method: "POST", body: hub });
      setResult(form, r.ok, r.message);
    } catch (err) { setResult(form, false, err.message); } finally { btn.disabled = false; }
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

  const key = form.dataset.section;
  const def = SECTION_DEFS.find((d) => d.key === key);
  const fields = def ? def.fields : [{ name: "battery_warn", type: "number" }];
  const body = readForm(form, fields);
  if (key === "alerts") body.battery_warn = Number(body.battery_warn);

  if (a === "test") {
    btn.disabled = true; setResult(form, true, "연결하는 중…");
    try {
      const r = await api(`/api/settings/test/${key}`, { method: "POST", body });
      setResult(form, r.ok, r.message);
    } catch (err) { setResult(form, false, err.message); } finally { btn.disabled = false; }
    return;
  }
  if (a === "save" || a === "remove") {
    if (a === "remove" && !(await confirmBox("연결을 해제할까요?", `${def.title} 연결 정보를 지웁니다.`, "해제"))) return;
    btn.disabled = true;
    try {
      view._settings = await api(`/api/settings/${key}`, { method: "PUT", body: a === "remove" ? null : body });
      drawSettings();
      toast(a === "remove" ? `${def.title} 연결을 해제했습니다` : "저장했습니다");
    } catch (err) {
      setResult(form, false, err.message);
    } finally { btn.disabled = false; }
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
      await api(`/api/smarthome/devices/${source}/${encodeURIComponent(hub)}/${encodeURIComponent(id)}/${next ? "on" : "off"}`, { method: "POST" });
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
    case "nas-reboot": return act(btn, { title: "NAS를 재부팅할까요?", message: "NAS의 모든 서비스가 잠시 중단됩니다.", path: "/api/infra/nas/reboot", done: "재부팅을 요청했습니다" });
    case "pve-start": return act(btn, { path: `/api/infra/proxmox/${k[0]}/${k[1]}/${k[2]}/power/start`, confirm: false, done: "시작을 요청했습니다" });
    case "pve-reboot": return act(btn, { title: `${k[2]}번 게스트를 재시작할까요?`, message: "게스트 OS에 재시작 신호를 보냅니다.", path: `/api/infra/proxmox/${k[0]}/${k[1]}/${k[2]}/power/reboot`, done: "재시작을 요청했습니다" });
    case "pve-shutdown": return act(btn, { title: `${k[2]}번 게스트를 종료할까요?`, message: "정상 종료(shutdown) 신호를 보냅니다.", path: `/api/infra/proxmox/${k[0]}/${k[1]}/${k[2]}/power/shutdown`, done: "종료를 요청했습니다" });
    case "pve-snap": return act(btn, { path: `/api/infra/proxmox/${k[0]}/${k[1]}/${k[2]}/snapshot`, confirm: false, done: "스냅샷을 요청했습니다", reload: false });
    case "pve-backup": return act(btn, { path: `/api/infra/proxmox/${k[0]}/${k[2]}/backup`, confirm: false, done: "백업 작업을 시작했습니다", reload: false });
    case "ct-start": return act(btn, { path: `/api/infra/portainer/${k[0]}/containers/${k[1]}/start`, confirm: false, done: `${k[2]} 시작` });
    case "ct-restart": return act(btn, { title: `${k[2]} 컨테이너를 재시작할까요?`, message: "잠시 서비스가 끊길 수 있습니다.", path: `/api/infra/portainer/${k[0]}/containers/${k[1]}/restart`, done: `${k[2]} 재시작` });
    case "ct-stop": return act(btn, { title: `${k[2]} 컨테이너를 중지할까요?`, message: "다시 시작하기 전까지 서비스가 멈춥니다.", path: `/api/infra/portainer/${k[0]}/containers/${k[1]}/stop`, done: `${k[2]} 중지` });
    case "ct-logs":
      try { const r = await api(`/api/infra/portainer/${k[0]}/containers/${k[1]}/logs?tail=300`); showText(`${k[2]} 로그 (최근 300줄)`, r.logs); }
      catch (err) { toast(err.message, true); }
      return;
    case "stack-start": return act(btn, { path: `/api/infra/portainer/stacks/${k[0]}/start?endpoint=${k[1]}`, confirm: false, done: `${k[2]} 시작` });
    case "stack-stop": return act(btn, { title: `${k[2]} 스택을 중지할까요?`, message: "스택의 모든 컨테이너가 멈춥니다.", path: `/api/infra/portainer/stacks/${k[0]}/stop?endpoint=${k[1]}`, done: `${k[2]} 중지` });
    case "hub-backup": return act(btn, { path: `/api/hubs/hubitat/${encodeURIComponent(k[0])}/backup`, confirm: false, done: `${k[1]} 백업 저장` });
    case "hub-reboot": return act(btn, { title: `${k[1]}를 재부팅할까요?`, message: "재부팅하는 동안(약 1~2분) 이 허브의 자동화가 멈춥니다.", path: `/api/hubs/hubitat/${encodeURIComponent(k[0])}/reboot`, done: "재부팅을 요청했습니다" });
    case "ha-backup": return act(btn, { path: "/api/hubs/home-assistant/backup", confirm: false, done: "HA 백업", reload: false });
    case "ha-restart": return act(btn, { title: "Home Assistant를 재시작할까요?", message: "재시작하는 동안 HA 자동화와 연동이 멈춥니다.", path: "/api/hubs/home-assistant/restart", done: "재시작을 요청했습니다" });
    case "hb-restart": return act(btn, { title: "Homebridge를 재시작할까요?", message: "재시작하는 동안 HomeKit에서 Homebridge 기기가 응답 없음으로 보입니다.", path: "/api/hubs/homebridge/restart", done: "재시작을 요청했습니다" });
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
    case "path-add": return saveRow("paths", null, PATH_FIELDS);
    case "path-edit": return saveRow("paths", k[0], PATH_FIELDS, view._sm.paths.find((x) => String(x.id) === k[0]));
    case "path-del": { const x = view._sm.paths.find((v) => String(v.id) === k[0]); return deleteRow("paths", k[0], x ? `${x.src} → ${x.dst}` : "이"); }
  }
});

/* ---------- 라우팅 ---------- */
const ROUTES = { infra: renderInfra, hubs: renderHubs, integration: renderIntegration, log: renderLog, settings: renderSettings };

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
  try {
    const st = await api("/api/auth/status");
    if (st.needs_setup) { showSetup(); return; }
    await api("/api/auth/me");
    showApp();
    route();
  } catch (_) { showLogin(); }
})();
