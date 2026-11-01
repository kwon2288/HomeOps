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
/** 아무것도 연결하지 않았을 때: 바로 추가할 수 있는 종류 버튼 */
function emptyStart(title, desc, types) {
  return `<section class="card onboarding"><div class="card-title"><h2>${esc(title)}</h2><small>${esc(desc)}</small></div>
    <div class="picker">${types.map((k) => {
      const t = CONN_TYPES.find((c) => c.key === k);
      return `<a class="pick" href="#/settings?add=${k}"><b>+ ${esc(t.title)}</b><small>${esc(t.desc)}</small></a>`;
    }).join("")}</div></section>`;
}

function addMore(types, configured) {
  const rest = types.filter((k) => !configured.includes(k) || k === "hubitat");
  return rest.length ? `<div class="chips">${rest.map((k) => {
    const t = CONN_TYPES.find((c) => c.key === k);
    return `<a class="btn" style="display:inline-flex;align-items:center;text-decoration:none" href="#/settings?add=${k}">+ ${esc(t.title)}</a>`;
  }).join("")}</div>` : "";
}

async function renderInfra() {
  const d = await api("/api/infra");
  const keys = [["synology", d.nas, nasPanel], ["proxmox", d.proxmox, pvePanel], ["portainer", d.portainer, ptnPanel]];
  const on = keys.filter(([, sys]) => sys.configured);
  view.innerHTML = on.length ? `
    <header class="page-head"><div><h1>인프라</h1><p>${on.map(([k]) => esc(CONN_TYPES.find((c) => c.key === k).title)).join(" · ")}</p></div>
      <button class="btn accent" data-refresh>새로 고침</button></header>
    <div class="grid wide">${on.map(([, sys, fn]) => fn(sys)).join("")}</div>
    ${addMore(["synology", "proxmox", "portainer"], on.map(([k]) => k))}`
    : `<header class="page-head"><div><h1>인프라</h1><p>아직 연결한 인프라가 없어요.</p></div></header>
    ${emptyStart("인프라 연결하기", "쓰는 것만 골라 연결하면 이 화면에 나타납니다.", ["synology", "proxmox", "portainer"])}`;
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
    ...hubs.hubitat.map(hubitatCard),
    hubs.home_assistant.configured ? haCard(hubs.home_assistant) : "",
    hubs.homebridge.configured ? hbCard(hubs.homebridge) : "",
  ].join("");
  const configured = [...(hubs.hubitat.length ? ["hubitat"] : []), ...(hubs.home_assistant.configured ? ["home_assistant"] : []),
    ...(hubs.homebridge.configured ? ["homebridge"] : [])];
  const online = hubs.hubitat.filter((h) => h.online).length + (hubs.home_assistant.online ? 1 : 0) + (hubs.homebridge.online ? 1 : 0);
  const total = hubs.hubitat.length + (hubs.home_assistant.configured ? 1 : 0) + (hubs.homebridge.configured ? 1 : 0);
  view.innerHTML = `
    <header class="page-head"><div><h1>스마트홈 허브</h1><p>API로 관리하는 허브와, 연동은 안 되지만 역할을 기록해 두는 기기</p></div>
      ${total ? '<button class="btn accent" data-refresh>새로 고침</button>' : ""}</header>
    ${total ? `<section class="section"><div class="section-head"><h2>허브 상태</h2><span class="muted" style="font-size:13px">${total}개 중 ${online}개 응답</span></div>
      <div class="grid">${cards}</div>
      ${addMore(["hubitat", "home_assistant", "homebridge"], configured)}`
      : `<section class="section">${emptyStart("허브 연결하기", "Hubitat, Home Assistant, Homebridge 중 쓰는 것만 연결하세요.", ["hubitat", "home_assistant", "homebridge"])}`}
      ${backups.length ? `<details class="card"><summary style="cursor:pointer;font-size:14px">Hubitat 백업 파일 ${backups.length}개</summary>
        <div class="rows">${backups.map((b) => `<div class="row"><div class="row-main"><b class="mono">${esc(b.file)}</b><small>${(b.size / 1048576).toFixed(1)} MB · ${new Date(b.mtime * 1000).toLocaleString("ko-KR")}</small></div>
        <a class="btn sm" style="display:inline-flex;align-items:center;text-decoration:none" href="/api/hubs/hubitat/backups/${encodeURIComponent(b.file)}" download>받기</a></div>`).join("")}</div></details>` : ""}
    </section>
    <section class="section"><div class="section-head"><div><h2>수동 등록 기기</h2><p>API 연동은 없지만 IP를 넣으면 응답 여부(ping)를 확인합니다</p></div>
      <div class="chips">${devices.some((d) => d.ip) ? '<button class="btn" data-act="ping-all">전체 응답 확인</button>' : ""}<button class="btn accent" data-act="dev-add">+ 기기 등록</button></div></div>
      <div class="grid mid">${devices.map(manualCard).join("") || '<div class="empty">Apple TV, HomePod, Nest Hub, Aqara 허브처럼 API로 연결하지 않는 기기를 역할과 함께 적어 둘 수 있어요. "+ 기기 등록"을 누르세요.</div>'}</div>
    </section>
    <section class="section"><div class="section-head"><div><h2>플랫폼 역할</h2><p>플랫폼마다 무엇을 맡기는지</p></div>
      <button class="btn" data-act="pf-add">플랫폼 추가</button></div>
      ${platforms.length ? "" : '<div class="empty">플랫폼마다 무엇을 맡기는지 정리해 두는 표입니다. "플랫폼 추가"로 시작하세요.</div>'}
      <div class="table-wrap" ${platforms.length ? "" : "hidden"}><table class="stack-table full" style="min-width:860px"><thead><tr><th scope="col">플랫폼</th><th scope="col">용도</th><th scope="col">주요 기능 · 담당 기기</th><th scope="col">허브 · 연결 경로</th><th scope="col"><span class="muted">편집</span></th></tr></thead>
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
  const hasSource = d.sources.hubitat > 0 || d.sources.home_assistant;
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
    ? emptyStart("기기 제어", "Hubitat(Maker API)이나 Home Assistant를 연결하면 방별 기기 목록과 켜기/끄기가 여기에 나타납니다.", ["hubitat", "home_assistant"])
    : `<div class="split">
      <section class="section grow"><div class="section-head"><h2>기기 제어</h2>
        ${d.devices.length ? `<div class="filters" role="group" aria-label="방 필터">${rooms.map((r) => `<button type="button" data-room="${esc(r)}" aria-pressed="${r === roomFilter}">${esc(r)}</button>`).join("")}</div>` : ""}</div>
        ${d.devices.length ? '<div class="legend"><span><span class="src HE">HE</span>Hubitat</span><span><span class="src HA">HA</span>Home Assistant</span><span><span class="src HB">HB</span>Homebridge → HomeKit 노출</span></div>' : ""}
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
    <input id="${id}" name="${f.name}" ${f.secret ? 'type="password" autocomplete="new-password"' : 'autocomplete="off"'} ${f.type === "number" ? 'inputmode="numeric"' : ""} ${f.type === "time" ? 'type="time"' : ""} value="${esc(v)}" placeholder="${esc(ph)}"></label>`;
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
const HUB_HELP = '허브 웹 → Apps → Add Built-In App → <b>Maker API</b>를 설치하고, "Allow Access via Local IP Address"를 켠 뒤 관리할 기기를 고르세요. 예시 URL의 <code>/apps/api/<b>App ID</b>/…?access_token=<b>토큰</b></code>을 넣으면 됩니다.';

// 추가할 수 있는 연결 종류 (고르기 화면)
const CONN_TYPES = [
  { key: "hubitat", group: "스마트홈", title: "Hubitat 허브", desc: "기기 제어 · 모드 · 허브 백업 · 재부팅", multi: true },
  { key: "home_assistant", group: "스마트홈", title: "Home Assistant", desc: "엔티티 제어 · 백업 · 재시작" },
  { key: "homebridge", group: "스마트홈", title: "Homebridge", desc: "HomeKit 노출 확인 · 재시작" },
  { key: "synology", group: "인프라", title: "Synology NAS", desc: "볼륨 · 디스크 · 리소스 · 재부팅" },
  { key: "proxmox", group: "인프라", title: "Proxmox VE", desc: "VM · LXC 전원 · 스냅샷 · 백업" },
  { key: "portainer", group: "인프라", title: "Portainer", desc: "컨테이너 · 스택 · 로그" },
];

function hubValues(h) {
  return {
    name: h.name, id: h.id, role: h.role, url: h.url,
    app_id: h.maker_api ? h.maker_api.app_id : "", token: h.maker_api ? h.maker_api.token : "",
    login_user: h.login ? h.login.username : "", login_password: h.login ? h.login.password : "",
  };
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

function shortUrl(u) { return String(u || "").replace(/^https?:\/\//, "").replace(/\/$/, ""); }

/** 연결 하나의 카드: 접힌 상태(요약) 또는 편집 상태(입력 폼) */
function connCard({ cardKey, typeLabel, title, sub, isNew, editing, help, fields, values }) {
  if (!editing) {
    return `<article class="card conn" data-card="${esc(cardKey)}">
      <div class="card-head"><div class="card-title"><span class="type-label">${esc(typeLabel)}</span><b>${esc(title)}</b><small>${esc(sub || "")}</small></div>
        <span class="badge ok"><span class="dot ok"></span>저장됨</span></div>
      <p class="test-result" role="status" aria-live="polite"></p>
      <div class="actions"><button type="button" class="btn" data-sact="test">연결 테스트</button>
        <button type="button" class="btn" data-sact="edit">편집</button>
        <button type="button" class="btn danger" data-sact="remove">삭제</button></div></article>`;
  }
  return `<form class="card conn editing" data-card="${esc(cardKey)}" novalidate>
    <div class="card-head"><div class="card-title"><span class="type-label">${esc(typeLabel)}</span><h2>${esc(isNew ? `${cardKey.startsWith("hub:") ? "Hubitat 허브" : title} 추가` : title)}</h2></div>
      ${isNew ? '<span class="badge warn">새 연결</span>' : ""}</div>
    <div class="howto">${help}</div>
    <div class="form-grid">${fields.map((f) => inputHtml(f, values[f.name], cardKey.replace(/\W/g, ""))).join("")}</div>
    <p class="test-result" role="status" aria-live="polite"></p>
    <div class="actions"><button type="button" class="btn" data-sact="test">연결 테스트</button>
      <button type="button" class="btn primary" data-sact="save">저장</button>
      <button type="button" class="btn" data-sact="cancel">취소</button></div></form>`;
}

function typePicker(compact) {
  const s = view._settings;
  const groups = ["스마트홈", "인프라"];
  return groups.map((g) => `<div class="picker-group"><span class="rows-title">${g}</span><div class="picker">
    ${CONN_TYPES.filter((t) => t.group === g).map((t) => {
      const added = !t.multi && (s[t.key] || view._adding.has(t.key));
      return `<button type="button" class="pick" data-add="${t.key}" ${added ? "disabled" : ""}>
        <b>${esc(t.title)}</b><small>${added ? "추가됨" : esc(t.desc)}</small></button>`;
    }).join("")}</div></div>`).join("") + (compact ? "" : "");
}

async function renderSettings() {
  const [s, me] = await Promise.all([api("/api/settings"), api("/api/auth/me")]);
  view._settings = s;
  view._me = me;
  view._hubs = s.hubitat.map((h) => ({ ...h, orig_id: h.id }));
  view._editing = new Set();
  view._adding = new Set();
  drawSettings();
  // 다른 화면의 "+ 추가" 버튼으로 들어온 경우 (#/settings?add=종류)
  const add = new URLSearchParams(location.hash.split("?")[1] || "").get("add");
  history.replaceState(null, "", "#/settings");
  if (add && CONN_TYPES.some((t) => t.key === add) && (add === "hubitat" || !s[add])) startAdd(add);
}

function drawSettings() {
  const s = view._settings;
  const me = view._me;
  const cards = [];
  view._hubs.forEach((h, i) => {
    const key = `hub:${i}`;
    const isNew = !h.orig_id;
    cards.push(connCard({
      cardKey: key, typeLabel: "Hubitat 허브", title: h.name || h.id, sub: `${shortUrl(h.url)}${h.role ? " · " + h.role : ""}`,
      isNew, editing: isNew || view._editing.has(key), help: HUB_HELP, fields: HUB_FIELDS, values: hubValues(h),
    }));
  });
  for (const def of SECTION_DEFS) {
    const v = s[def.key];
    const adding = view._adding.has(def.key);
    if (!v && !adding) continue;
    cards.push(connCard({
      cardKey: def.key, typeLabel: def.group === "infra" ? "인프라" : "스마트홈", title: def.title, sub: v ? shortUrl(v.url) : "",
      isNew: !v, editing: !v || view._editing.has(def.key), help: def.help, fields: def.fields, values: v || {},
    }));
  }
  const empty = cards.length === 0;
  const savedCount = view._hubs.filter((h) => h.orig_id).length + SECTION_DEFS.filter((d) => s[d.key]).length;

  view.innerHTML = `
    <header class="page-head"><div><h1>연결 설정</h1><p>${empty ? "쓰는 시스템만 골라서 연결하세요." : `연결 ${savedCount}개 · 토큰과 비밀번호는 암호화되어 저장됩니다.`}</p></div>
      <div class="chips">${empty ? "" : '<button type="button" class="btn primary" data-sact="add">+ 연결 추가</button>'}</div></header>

    ${empty ? `<section class="card onboarding"><div class="card-title"><h2>무엇부터 연결할까요?</h2>
        <small>하나만 연결해도 바로 쓸 수 있고, 나머지는 나중에 "+ 연결 추가"로 언제든 붙일 수 있어요.</small></div>
        ${typePicker()}</section>`
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
      <a class="btn" style="display:inline-flex;align-items:center;text-decoration:none" href="#/log">작업 기록</a></div>`;
}

function setResult(form, ok, msg) {
  const p = form.querySelector(".test-result");
  p.textContent = msg;
  p.className = "test-result " + (ok ? "ok" : "bad");
}

/** 편집 중인 허브 폼의 입력값을 view._hubs 에 옮겨 둔다 (다시 그려도 입력이 남도록) */
function keepHubInputs() {
  view.querySelectorAll('form[data-card^="hub:"]').forEach((f) => {
    const i = Number(f.dataset.card.split(":")[1]);
    const prev = view._hubs[i];
    const cur = { ...readHub(f, i), orig_id: prev.orig_id };
    if (cur.maker_api && !cur.maker_api.token && prev.maker_api && prev.maker_api.token === MASK) cur.maker_api.token = MASK;
    if (cur.login && !cur.login.password && prev.login && prev.login.password === MASK) cur.login.password = MASK;
    view._hubs[i] = cur;
  });
}

/** 저장된 허브 목록 + 바꾼 허브 하나로 저장 */
async function saveHubList(hubs, btn, message) {
  btn.disabled = true;
  try {
    const s = await api("/api/settings/hubitat", { method: "PUT", body: hubs });
    view._settings = s;
    const pending = view._hubs.filter((h) => !h.orig_id && !hubs.includes(h));
    view._hubs = [...s.hubitat.map((h) => ({ ...h, orig_id: h.id })), ...pending];
    view._editing = new Set([...view._editing].filter((k) => !k.startsWith("hub:")));
    drawSettings();
    toast(message);
    return true;
  } catch (err) {
    const form = btn.closest("form, article");
    if (form) setResult(form, false, err.message);
    toast(err.message, true);
    return false;
  } finally {
    btn.disabled = false;
  }
}

function startAdd(type) {
  keepHubInputs();
  if (type === "hubitat") {
    const n = view._hubs.length + 1;
    const ids = new Set(view._hubs.map((h) => h.id));
    let id = n === 1 ? "main" : `hub${n}`;
    while (ids.has(id)) id += "x";
    view._hubs.push({ id, name: "", role: "", url: "http://", maker_api: null, login: null, orig_id: null });
  } else {
    view._adding.add(type);
  }
  drawSettings();
  const key = type === "hubitat" ? `hub:${view._hubs.length - 1}` : type;
  const card = view.querySelector(`[data-card="${key}"]`);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "start" });
    const first = card.querySelector("input:not([type=checkbox])");
    if (first) first.focus({ preventScroll: true });
  }
}

view.addEventListener("click", async (e) => {
  const pick = e.target.closest("[data-add]");
  if (pick && view.dataset.route === "settings") {
    if (dlg.open) dlg.close("cancel");
    startAdd(pick.dataset.add);
    return;
  }
  const btn = e.target.closest("[data-sact]");
  if (!btn) return;
  const a = btn.dataset.sact;
  const card = btn.closest("[data-card]");
  const form = btn.closest("form") || card;

  if (a === "add") {
    keepHubInputs();
    dlg.innerHTML = `<form method="dialog" class="dlg"><h2>연결 추가</h2><p>추가할 시스템을 고르세요.</p>${typePicker()}
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
  const isHub = key.startsWith("hub:");
  const i = isHub ? Number(key.split(":")[1]) : -1;
  const def = isHub ? null : SECTION_DEFS.find((d) => d.key === key);
  const editing = card.tagName === "FORM";

  if (a === "edit") { keepHubInputs(); view._editing.add(key); drawSettings(); return; }
  if (a === "cancel") {
    keepHubInputs();
    if (isHub) {
      if (!view._hubs[i].orig_id) view._hubs.splice(i, 1);
      else view._hubs[i] = { ...view._settings.hubitat.find((h) => h.id === view._hubs[i].orig_id), orig_id: view._hubs[i].orig_id };
    } else {
      view._adding.delete(key);
    }
    view._editing.delete(key);
    drawSettings();
    return;
  }

  // 입력값(편집 중) 또는 저장된 값(접힌 카드)
  let body;
  if (isHub) body = editing ? readHub(card, i) : { ...view._hubs[i] };
  else body = editing ? readForm(card, def.fields) : view._settings[key];

  if (a === "test") {
    btn.disabled = true; setResult(form, true, "연결하는 중…");
    try {
      const r = await api(`/api/settings/test/${isHub ? "hubitat" : key}`, { method: "POST", body });
      setResult(form, r.ok, r.message);
    } catch (err) { setResult(form, false, err.message); } finally { btn.disabled = false; }
    return;
  }
  if (a === "save") {
    if (isHub) {
      const saved = view._hubs.filter((h, j) => h.orig_id && j !== i);
      const list = [...saved, body];
      view._hubs[i] = body;
      if (await saveHubList(list, btn, "허브를 저장했습니다")) { /* 다시 그려짐 */ }
      return;
    }
    btn.disabled = true;
    try {
      view._settings = await api(`/api/settings/${key}`, { method: "PUT", body });
      view._adding.delete(key);
      view._editing.delete(key);
      keepHubInputs();
      drawSettings();
      toast(`${def.title} 연결을 저장했습니다`);
    } catch (err) { setResult(form, false, err.message); } finally { btn.disabled = false; }
    return;
  }
  if (a === "remove") {
    const name = isHub ? (view._hubs[i].name || view._hubs[i].id) : def.title;
    if (!(await confirmBox("연결을 삭제할까요?", `${name} 연결 정보를 지웁니다. 장비 자체에는 영향이 없습니다.`, "삭제"))) return;
    if (isHub) {
      const list = view._hubs.filter((h, j) => h.orig_id && j !== i);
      view._hubs.splice(i, 1);
      await saveHubList(list, btn, `${name} 연결을 삭제했습니다`);
      return;
    }
    try {
      view._settings = await api(`/api/settings/${key}`, { method: "PUT", body: null });
      keepHubInputs();
      drawSettings();
      toast(`${def.title} 연결을 삭제했습니다`);
    } catch (err) { toast(err.message, true); }
  }
});

// 연결 추가 대화상자 안의 종류 버튼
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
const ROUTES = { infra: renderInfra, hubs: renderHubs, integration: renderIntegration, log: renderLog, settings: renderSettings, backup: renderBackup };

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
