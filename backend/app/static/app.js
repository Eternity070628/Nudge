const $ = (id) => document.getElementById(id);
const state = { draft: null, samples: [], payload: null, user: null };
const CAT = { competition: "竞赛", scholarship: "奖学金", lecture: "讲座", exam: "考试", affairs: "办事", activity: "活动", other: "其他" };
const URG = { overdue: "已过期", today: "今天截止", urgent: "天内截止", soon: "本周", later: "稍后", unknown: "待确认" };

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

async function api(path, opts) {
  const init = Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {});
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = "请求失败 (" + res.status + ")";
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}

function fmt(iso) {
  if (!iso) return "未识别";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const p = (n) => (n < 10 ? "0" : "") + n;
  return d.getFullYear() + "/" + p(d.getMonth() + 1) + "/" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
}

function confChip(v) {
  const cls = v >= 0.85 ? "c-hi" : v >= 0.7 ? "c-mid" : "c-lo";
  return el("span", "conf " + cls, "置信度 " + Math.round((v || 0) * 100) + "%");
}

function field(label, valueNode, conf, quote) {
  const row = el("div", "field");
  row.appendChild(el("div", "k", label));
  const v = el("div", "v");
  if (typeof valueNode === "string") v.appendChild(document.createTextNode(valueNode));
  else v.appendChild(valueNode);
  if (conf !== undefined) v.appendChild(confChip(conf));
  if (quote) v.appendChild(el("div", "quote", "原文：" + quote));
  row.appendChild(v);
  return row;
}

function markEdited(draft, field, row) {
  const message = "[人工修改] " + field + " 已人工修改，原文 evidence 仅作参考";
  if (!draft.warnings.includes(message)) draft.warnings.push(message);
  const badge = row.querySelector(".edited-badge");
  if (badge) badge.classList.remove("hidden");
}

function editRow(label, inputNode, conf, quote) {
  const row = el("div", "field");
  row.appendChild(el("div", "k", label));
  const v = el("div", "v");
  v.appendChild(inputNode);
  if (conf !== undefined) v.appendChild(confChip(conf));
  if (quote) v.appendChild(el("div", "quote", "原文：" + quote));
  v.appendChild(el("span", "edited-badge hidden", "已人工修改"));
  row.appendChild(v);
  return row;
}

function renderDraft(payload) {
  state.payload = payload;
  const d = payload.draft;
  const box = $("draft");
  box.innerHTML = "";
  box.classList.remove("hidden");

  const head = el("h3", null, d.title || "（未识别标题）");
  box.appendChild(head);

  const badges = el("div", "rowline");
  badges.appendChild(el("span", "badge cat", CAT[d.category] || "其他"));
  badges.appendChild(el("span", "badge", "重要性 " + d.importance + "/5"));
  badges.appendChild(el("span", "badge", "总体可信度 " + Math.round(d.overall_confidence * 100) + "%"));
  if (d.needs_review.length) badges.appendChild(el("span", "badge", "待确认 " + d.needs_review.length + " 项"));
  box.appendChild(badges);

  const deadlineInput = document.createElement("input");
  deadlineInput.type = "datetime-local";
  deadlineInput.className = "edit-input";
  deadlineInput.value = d.deadline.end ? d.deadline.end.slice(0, 16) : "";
  const deadlineRow = editRow("截止时间", deadlineInput, d.deadline.confidence, d.evidence.deadline);
  deadlineInput.onchange = () => {
    const value = deadlineInput.value.trim();
    d.deadline.end = value ? (value.length === 16 ? value + ":00" : value) : null;
    markEdited(d, "deadline", deadlineRow);
  };
  box.appendChild(deadlineRow);

  const materialsInput = document.createElement("textarea");
  materialsInput.className = "edit-input";
  materialsInput.rows = 3;
  materialsInput.value = d.materials.map((m) => m.name).join("\n");
  const materialsRow = editRow("需要材料", materialsInput, d.confidence.materials, d.evidence.materials);
  materialsInput.oninput = () => {
    d.materials = materialsInput.value.split(/[\n,，、]+/).map((name) => name.trim()).filter(Boolean)
      .map((name) => ({ name, required: true, note: "" }));
    markEdited(d, "materials", materialsRow);
  };
  box.appendChild(materialsRow);

  const submissionBox = el("div", "edit-stack");
  const channelSelect = document.createElement("select");
  channelSelect.className = "edit-input";
  [["web", "线上"], ["email", "邮箱"], ["offline", "线下"], ["unknown", "未识别"]].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    channelSelect.appendChild(option);
  });
  channelSelect.value = d.submission.channel || "unknown";
  const targetInput = document.createElement("input");
  targetInput.className = "edit-input";
  targetInput.placeholder = "URL / 邮箱 / 地点";
  const targetValue = () => d.submission.url || d.submission.email || d.submission.location || "";
  targetInput.value = targetValue();
  const submissionRow = editRow("提交方式", submissionBox, d.confidence.submission, d.evidence.submission);
  const syncSubmission = () => {
    const value = targetInput.value.trim();
    d.submission.channel = channelSelect.value;
    d.submission.url = channelSelect.value === "web" ? value : "";
    d.submission.email = channelSelect.value === "email" ? value : "";
    d.submission.location = channelSelect.value === "offline" ? value : "";
    markEdited(d, "submission", submissionRow);
  };
  channelSelect.onchange = () => { targetInput.value = targetValue(); syncSubmission(); };
  targetInput.oninput = syncSubmission;
  submissionBox.appendChild(channelSelect);
  submissionBox.appendChild(targetInput);
  box.appendChild(submissionRow);

  const audienceBox = el("div", "edit-stack");
  const gradesInput = document.createElement("input");
  gradesInput.className = "edit-input";
  gradesInput.placeholder = "年级，用顿号分隔";
  gradesInput.value = (d.audience.grades || []).join("、");
  const collegesInput = document.createElement("input");
  collegesInput.className = "edit-input";
  collegesInput.placeholder = "学院，用顿号分隔";
  collegesInput.value = (d.audience.colleges || []).join("、");
  const audienceRow = editRow("适用对象", audienceBox, d.confidence.audience, d.evidence.audience);
  const syncAudience = () => {
    d.audience.grades = gradesInput.value.split(/[、,，\s]+/).filter(Boolean);
    d.audience.colleges = collegesInput.value.split(/[、,，\s]+/).filter(Boolean);
    markEdited(d, "audience", audienceRow);
  };
  gradesInput.oninput = syncAudience;
  collegesInput.oninput = syncAudience;
  audienceBox.appendChild(gradesInput);
  audienceBox.appendChild(collegesInput);
  box.appendChild(audienceRow);

  if (d.warnings.length) {
    const w = el("div", "warn");
    d.warnings.forEach((t, i) => { if (i) w.appendChild(document.createElement("br")); w.appendChild(document.createTextNode("· " + t)); });
    box.appendChild(w);
  }

  const why = el("div", "why");
  why.appendChild(el("b", null, "为什么推荐给我："));
  why.appendChild(document.createTextNode(" " + (payload.reasons.join("；") || "暂无画像信息")));
  box.appendChild(why);

  const bar = el("div", "savebar");
  bar.appendChild(el("div", "rel", "相关度 " + Math.round(payload.relevance * 100) + "%"));
  const save = el("button", "btn primary", "确认无误，加入我的截止");
  save.onclick = () => saveDraft(save);
  bar.appendChild(save);
  box.appendChild(bar);
}

async function saveDraft(btn) {
  if (!state.payload) return;
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    const r = await api("/api/events", { method: "POST", body: JSON.stringify({ draft: state.payload.draft, user_id: state.user ? state.user.id : "" }) });
    btn.textContent = r.created ? "已加入 ✓" : "这个截止已经在列表里了";
    await loadBoard();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "保存失败，重试";
    alert(e.message);
  }
}

async function loadHealth() {
  try {
    const h = await api("/api/health");
    const model = h.model || "deepseek-v4.1-flash";
    const broken = h.llm_error && h.llm_error.error;
    $("engine").textContent = h.llm
      ? "大模型已接入 · " + model
      : (broken ? "模型不可用 · 打开模型设置看原因" : "规则模式 · 未配模型 Key");
    $("llm-note").textContent = h.llm
      ? "抽取由 " + model + " 补充，规则做证据校验"
      : "未配置模型 Key，抽取全部由本地规则完成";
  } catch (e) {
    $("engine").textContent = "后端未启动";
  }
}

async function loadSettings() {
  try {
    const s = await api("/api/settings");
    $("setting-base").value = s.base_url || "";
    $("setting-model").value = s.model || "";
    $("setting-key").value = "";
    $("setting-status").textContent = s.has_key
      ? "已保存 Key（尾号 " + s.key_hint + "），留空不会覆盖"
      : "尚未保存 Key，当前走规则模式";
  } catch (e) {
    $("setting-status").textContent = "读取设置失败：" + e.message;
  }
}

async function testConnection() {
  const btn = $("setting-test");
  const box = $("setting-status");
  btn.disabled = true;
  btn.textContent = "连接中…";
  box.textContent = "正在请求 " + ($("setting-base").value.trim() || "默认地址") + " …";
  try {
    const r = await api("/api/llm-test?kind=chat");
    if (r.ok) {
      box.textContent = "连接成功 · " + r.model + " 回复：" + (r.reply || "（空）");
    } else if (r.reason === "no_key") {
      box.textContent = "还没有 Key：先在上面填好 Key 并保存，再测试";
    } else {
      box.textContent = "连接失败 " + (r.status || "") + "：" + (r.error || r.body || "未知错误");
    }
  } catch (e) {
    box.textContent = "请求失败：" + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "测试连接";
  }
}

function openSettings() {
  const dialog = $("settings-dialog");
  if (!dialog.open) dialog.showModal();
  loadSettings();
}

async function saveSettings(event) {
  event.preventDefault();
  const btn = $("setting-save");
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    const s = await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        base_url: $("setting-base").value.trim(),
        model: $("setting-model").value.trim(),
        api_key: $("setting-key").value.trim(),
      }),
    });
    $("setting-key").value = "";
    $("setting-status").textContent = s.has_key
      ? "已保存，Key 尾号 " + s.key_hint + "，点「测试连接」验证一次"
      : "已保存，但还没有 Key";
    await loadHealth();
  } catch (e) {
    $("setting-status").textContent = "保存失败：" + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "保存";
  }
}

async function loadSamples() {
  try {
    state.samples = await api("/api/samples");
    const box = $("samples");
    state.samples.forEach((s) => {
      const c = el("span", "chip", s.label);
      c.onclick = () => { $("notice").value = s.text; $("notice").focus(); };
      box.appendChild(c);
    });
  } catch (e) {}
}

async function loadBoard() {
  try {
    const data = await api("/api/dashboard");
    state.user = data.user || state.user;
    renderStats(data.stats);
    renderConflicts(data.conflicts);
    renderEvents(data.events);
    $("brief").textContent = "📌 " + data.brief.brief;
    $("ics").href = "/api/calendar/" + ((data.user && data.user.token) || "") + ".ics";
    const active = data.active_count !== undefined ? data.active_count : data.events.filter((e) => !e.done_at).length;
    $("list-count").textContent = active + " 项";
    $("board-hint").textContent = data.stats.saved_minutes + " 分钟已省下";
  } catch (e) {
    if (e.message === "请先登录") location.href = "/";
    else $("board-hint").textContent = "无法连接后端";
  }
}

function renderStats(s) {
  const box = $("stats");
  box.innerHTML = "";
  const cards = [
    [s.upcoming, "待办截止", false],
    [s.urgent_7d, "7 天内到期", true],
    [s.materials, "待交材料", false],
    [s.saved_minutes + "′", "预计省下时间", false],
  ];
  cards.forEach((c) => {
    const n = el("div", "stat" + (c[2] ? " hot" : ""));
    n.appendChild(el("div", "n", String(c[0])));
    n.appendChild(el("div", "l", c[1]));
    box.appendChild(n);
  });
}

function renderConflicts(list) {
  const box = $("conflict");
  box.innerHTML = "";
  list.forEach((c) => {
    const w = el("div", "warn");
    w.appendChild(el("b", null, "⚠ 负载预警 · " + c.date));
    w.appendChild(document.createElement("br"));
    w.appendChild(document.createTextNode("当天有 " + c.count + " 个截止：" + c.titles.join(" / ")));
    w.appendChild(document.createElement("br"));
    w.appendChild(document.createTextNode(c.advice));
    box.appendChild(w);
  });
}

function renderEvents(list) {
  const box = $("events");
  box.innerHTML = "";
  if (!list.length) {
    const p = el("div", "tiny", "还没有数据。先在左边粘贴一条通知，或点「载入示例数据」。");
    box.appendChild(p);
    return;
  }
  list.forEach((e) => {
    const done = Boolean(e.done || e.done_at);
    const row = el("div", "ev " + (done ? "done " : "") + (e.urgency || "later"));
    const left = el("div");
    left.appendChild(el("div", "t", e.title));
    const meta = [CAT[e.category] || "其他", e.submission.channel === "offline" ? "需线下" : "", (e.checklist || []).length ? e.checklist.length + " 项待办" : ""].filter(Boolean).join(" · ");
    left.appendChild(el("div", "m", meta));
    const right = el("div", "d");
    const d = e.days_left;
    const big = done ? "已完成" : d === null ? "?" : d < 0 ? "过期" : d === 0 ? "今天" : d + " 天";
    right.appendChild(el("b", null, big));
    right.appendChild(el("span", null, fmt(e.deadline_end).slice(5)));
    const toggle = el("span", "x", done ? "撤销" : "标记完成");
    toggle.title = done ? "恢复这条截止" : "办完了？点一下标记完成";
    toggle.style.cursor = "pointer";
    toggle.onclick = async () => {
      await api("/api/events/" + e.id + (done ? "/undone" : "/done"), { method: "POST" });
      loadBoard();
    };
    const remove = el("span", "del", "删除");
    remove.title = "从我的看板删除";
    remove.style.cursor = "pointer";
    remove.onclick = async () => {
      if (!confirm("删除这条截止？")) return;
      await api("/api/events/" + e.id, { method: "DELETE" });
      loadBoard();
    };
    right.appendChild(toggle);
    right.appendChild(remove);
    row.appendChild(left);
    row.appendChild(right);
    box.appendChild(row);
  });
}

async function doExtract() {
  const text = $("notice").value.trim();
  if (text.length < 10) { alert("先把通知正文粘贴进来（至少 10 个字）"); return; }
  const btn = $("extract");
  btn.disabled = true;
  btn.textContent = "四个 Agent 在处理…";
  try {
    const payload = await api("/api/extract", { method: "POST", body: JSON.stringify({ text: text, source_type: "text" }) });
    renderDraft(payload);
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "抽取为事件";
  }
}

async function doSeed() {
  const btn = $("seed");
  btn.disabled = true;
  btn.textContent = "正在解析 6 条示例…";
  try {
    const r = await api("/api/seed", { method: "POST" });
    btn.textContent = "已载入 " + r.added + " 条";
    await loadBoard();
  } catch (e) {
    btn.textContent = "载入失败";
  } finally {
    setTimeout(() => { btn.disabled = false; btn.textContent = "载入示例数据"; }, 1600);
  }
}

$("extract").onclick = doExtract;
$("seed").onclick = doSeed;

// demo mode: /?demo=1 auto-fills sample #1 and runs the four agents
async function demoMode() {
  const params = new URLSearchParams(location.search);
  if (!params.has("demo")) return;
  try {
    const r = await api("/api/samples");
    const list = Array.isArray(r) ? r : r.samples;
    const idx = Math.max(0, Number(params.get("demo")) - 1);
    const s = list[idx] || list[0];
    $("notice").value = s.text;
    await doExtract();
  } catch (e) {}
}

function showAuth() {
  state.user = null;
  $("app-shell").classList.add("hidden");
  $("admin-screen").classList.add("hidden");
  $("auth-screen").classList.remove("hidden");
  switchAuthTab("login");
  ["login-password", "register-password", "register-confirm", "reset-password", "reset-confirm"].forEach((id) => {
    $(id).value = "";
  });
  const dialog = $("settings-dialog");
  if (dialog.open) dialog.close();
}

function startApp() {
  $("samples").innerHTML = "";
  $("draft").classList.add("hidden");
  $("draft").innerHTML = "";
  $("notice").value = "";
  $("stats").innerHTML = "";
  $("events").innerHTML = "";
  $("conflict").innerHTML = "";
  $("brief").textContent = "";
  state.payload = null;
  loadHealth();
  loadSettings();
  loadSamples();
  loadBoard().then(demoMode);
}

function enterApp(user) {
  state.user = user;
  $("auth-screen").classList.add("hidden");
  $("admin-screen").classList.add("hidden");
  $("app-shell").classList.remove("hidden");
  $("user-name").textContent = user.name || user.email || "";
  $("admin-btn").classList.toggle("hidden", !user.is_admin);
  $("settings-btn").classList.toggle("hidden", !user.is_admin);
  startApp();
}

async function loadAdminUsers() {
  const box = $("admin-users");
  try {
    const data = await api("/api/admin/users");
    $("admin-count").textContent = data.users.length + " 人";
    box.innerHTML = "";
    data.users.forEach((u) => {
      const row = el("div", "user-row");
      row.appendChild(el("div", "user-main", (u.name || "未命名") + (u.is_admin ? " · 管理员" : "")));
      row.appendChild(el("div", "user-meta", (u.email || "无邮箱") + " · " + (u.event_count || 0) + " 个事件"));
      row.appendChild(el("div", "user-time", (u.created_at || "").slice(0, 10)));
      if (!u.is_admin && u.id !== "u_demo") {
        const remove = el("button", "btn ghost btn-mini", "删除");
        remove.type = "button";
        remove.onclick = async () => {
          if (!confirm("删除用户并清理其事件和反馈？")) return;
          try { await api("/api/admin/users/" + u.id, { method: "DELETE" }); loadAdminUsers(); }
          catch (e) { alert(e.message); }
        };
        row.appendChild(remove);
      } else {
        row.appendChild(el("span", "user-time", "内置账号"));
      }
      box.appendChild(row);
    });
  } catch (e) {
    $("admin-count").textContent = e.message;
  }
}

function enterAdmin(user) {
  state.user = user;
  $("auth-screen").classList.add("hidden");
  $("app-shell").classList.add("hidden");
  $("admin-screen").classList.remove("hidden");
  $("admin-name").textContent = (user.name || "管理员") + " · " + (user.email || "");
  loadAdminUsers();
}

function switchAuthTab(name) {
  document.querySelectorAll("[data-auth-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.authTab === name);
  });
  ["login", "register", "reset"].forEach((key) => {
    $(key + "-form").classList.toggle("hidden", key !== name);
  });
}

function startCountdown(button) {
  let left = 60;
  button.disabled = true;
  button.textContent = left + "s 后重发";
  const timer = setInterval(() => {
    left -= 1;
    if (left <= 0) {
      clearInterval(timer);
      button.disabled = false;
      button.textContent = "发送验证码";
      return;
    }
    button.textContent = left + "s 后重发";
  }, 1000);
}

async function sendCode(emailId, purpose, statusId, button) {
  const email = $(emailId).value.trim();
  if (!email) { $(statusId).textContent = "先填邮箱"; return; }
  button.disabled = true;
  button.textContent = "发送中…";
  try {
    const data = await api("/api/auth/send-code", {
      method: "POST",
      body: JSON.stringify({ email, purpose }),
    });
    if (data.dev) {
      $(statusId).textContent =
        (data.notice || "开发模式：未真实发信") +
        (data.dev_code ? "，验证码 " + data.dev_code + "（已填入）" : "，请查看服务端日志");
      if (data.dev_code) {
        $(purpose === "register" ? "register-code" : "reset-code").value = data.dev_code;
      }
    } else {
      $(statusId).textContent = "验证码已发送到 " + email + "，10 分钟内有效";
    }
    startCountdown(button);
  } catch (e) {
    $(statusId).textContent = e.message;
    button.disabled = false;
    button.textContent = "发送验证码";
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const status = $("login-status");
  status.textContent = "登录中…";
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: $("login-email").value.trim(), password: $("login-password").value }),
    });
    if (data.user.is_admin) location.href = "/admin";
    else location.href = "/app";
  } catch (e) {
    status.textContent = e.message;
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const status = $("register-status");
  status.textContent = "注册中…";
  try {
    const data = await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        nickname: $("register-name").value.trim(),
        email: $("register-email").value.trim(),
        password: $("register-password").value,
        confirm: $("register-confirm").value,
        code: $("register-code").value.trim(),
      }),
    });
    location.href = "/app";
  } catch (e) {
    status.textContent = e.message;
  }
}

async function handleReset(event) {
  event.preventDefault();
  const status = $("reset-status");
  status.textContent = "重置中…";
  try {
    await api("/api/auth/reset", {
      method: "POST",
      body: JSON.stringify({
        email: $("reset-email").value.trim(),
        code: $("reset-code").value.trim(),
        password: $("reset-password").value,
        confirm: $("reset-confirm").value,
      }),
    });
    $("login-email").value = $("reset-email").value.trim();
    status.textContent = "密码已重置，请登录";
    switchAuthTab("login");
  } catch (e) {
    status.textContent = e.message;
  }
}

async function handleDemo() {
  try {
    const data = await api("/api/auth/demo", { method: "POST", body: JSON.stringify({}) });
    location.href = "/app";
  } catch (e) {
    $("login-status").textContent = e.message;
  }
}

async function handleLogout() {
  try { await api("/api/auth/logout", { method: "POST", body: JSON.stringify({}) }); } catch (e) {}
  location.href = "/";
}

async function loadMailStatus() {
  const node = $("auth-mail");
  if (!node) return;
  try {
    const s = await api("/api/auth/mail-status");
    if (s.mode === "graph") {
      node.textContent = "验证码由 " + s.sender + " 通过 Microsoft Graph 真实发出";
    } else if (s.mode === "smtp") {
      node.textContent = "验证码由 " + s.sender + " 通过邮箱 SMTP 真实发出";
    } else if (s.mode === "dev") {
      node.textContent = "开发模式：未真实发信，验证码只显示在本页和服务端日志";
    } else {
      node.textContent = "邮箱服务未授权：注册 / 重置密码暂不可用";
    }
    node.dataset.mode = s.mode || "";
  } catch (e) {
    node.textContent = "";
  }
}

async function initAuth() {
  const path = location.pathname;
  loadMailStatus();
  try {
    const data = await api("/api/auth/me");
    if (path === "/") {
      location.replace(data.user.is_admin ? "/admin" : "/app");
      return;
    }
    if (path === "/admin") {
      if (!data.user.is_admin) { location.replace("/app"); return; }
      enterAdmin(data.user);
      return;
    }
    enterApp(data.user);
  } catch (e) {
    if (path === "/") showAuth();
    else location.replace("/");
  }
}

const themePicker = $("theme-picker");
const themeTrigger = $("theme-trigger");
const themeMenu = $("theme-menu");
const themeLabel = $("theme-label");
const themeOptions = Array.from(document.querySelectorAll(".theme-option"));
const themeNames = { system: "跟随系统", light: "浅色", dark: "深色" };

function applyTheme(theme) {
  const value = themeNames[theme] ? theme : "system";
  document.documentElement.dataset.theme = value;
  themeLabel.textContent = themeNames[value];
  themeOptions.forEach((option) => {
    option.setAttribute("aria-selected", String(option.dataset.theme === value));
  });
  try { localStorage.setItem("nudge-theme", value); } catch (e) {}
}

function closeThemeMenu() {
  themeMenu.hidden = true;
  themeTrigger.setAttribute("aria-expanded", "false");
}

function openThemeMenu() {
  themeMenu.hidden = false;
  themeTrigger.setAttribute("aria-expanded", "true");
  const selected = themeOptions.find((option) => option.getAttribute("aria-selected") === "true");
  if (selected) selected.focus();
}

applyTheme(document.documentElement.dataset.theme || "system");

themeTrigger.onclick = () => {
  if (themeMenu.hidden) openThemeMenu();
  else closeThemeMenu();
};

themeOptions.forEach((option) => {
  option.onclick = () => {
    applyTheme(option.dataset.theme);
    closeThemeMenu();
    themeTrigger.focus();
  };
});

document.addEventListener("click", (event) => {
  if (!themePicker.contains(event.target)) closeThemeMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeThemeMenu();
    themeTrigger.focus();
  }
});

themeTrigger.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    openThemeMenu();
  }
});

themeMenu.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  event.preventDefault();
  const current = themeOptions.indexOf(document.activeElement);
  const delta = event.key === "ArrowDown" ? 1 : -1;
  const next = (current + delta + themeOptions.length) % themeOptions.length;
  themeOptions[next].focus();
});

$("settings-btn").onclick = openSettings;
$("setting-cancel").onclick = () => $("settings-dialog").close();
$("setting-test").onclick = testConnection;
$("settings-form").onsubmit = saveSettings;

$("admin-btn").onclick = () => { location.href = "/admin"; };
$("admin-back").onclick = () => { location.href = "/app"; };
$("logout-btn").onclick = handleLogout;
$("admin-logout").onclick = handleLogout;
$("login-form").onsubmit = handleLogin;
$("register-form").onsubmit = handleRegister;
$("reset-form").onsubmit = handleReset;
$("demo-login").onclick = handleDemo;
$("register-send").onclick = () => sendCode("register-email", "register", "register-status", $("register-send"));
$("reset-send").onclick = () => sendCode("reset-email", "reset", "reset-status", $("reset-send"));

document.querySelectorAll("[data-auth-tab]").forEach((button) => {
  button.onclick = () => switchAuthTab(button.dataset.authTab);
});

document.querySelectorAll(".show-pass").forEach((button) => {
  button.onclick = () => {
    const input = $(button.dataset.target);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "隐藏" : "显示";
  };
});

initAuth();
