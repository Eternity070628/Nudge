const $ = (id) => document.getElementById(id);
const state = { draft: null, payload: null, user: null, settings: null, passwordMethod: "old", adminSelected: new Set() };
const CAT = { competition: "竞赛", scholarship: "奖学金", lecture: "讲座", exam: "考试", affairs: "办事", activity: "活动", other: "其他" };
const CAMPUS = { haidian: "海淀校区", shahe: "沙河校区", hainan: "海南校区", unknown: "未识别" };
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
  const status = el("div", "field-status");
  if (conf !== undefined) status.appendChild(confChip(conf));
  status.appendChild(el("span", "edited-badge hidden", "已人工修改"));
  v.appendChild(status);
  if (quote) v.appendChild(el("div", "quote", "原文：" + quote));
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
  badges.appendChild(el("span", "badge", "校区 " + (CAMPUS[d.campus] || CAMPUS.unknown)));
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

const AGENTS = ["extractor", "verifier", "matcher", "planner"];

function setAgent(name, stateName, text) {
  const node = document.querySelector('.agent-step[data-agent="' + name + '"]');
  if (!node) return;
  node.dataset.state = stateName;
  const label = node.querySelector(".agent-state");
  if (label) label.textContent = text;
}

function resetRunbook() {
  AGENTS.forEach((name) => setAgent(name, "idle", "待命"));
  $("runbook-state").textContent = "待命";
}

function runbookStart() {
  AGENTS.forEach((name) => setAgent(name, "running", "处理中"));
  $("runbook-state").textContent = "四个 Agent 正在处理…";
}

function runbookDone(payload) {
  const d = payload.draft;
  setAgent("extractor", "done",
    "已抽取 " + (d.title ? "标题" : "标题缺失") + " / " + (d.deadline.end ? "截止" : "截止缺失")
    + " / " + (d.materials.length ? d.materials.length + " 项材料" : "无材料"));
  setAgent("verifier", d.needs_review.length ? "warn" : "done",
    "待确认 " + d.needs_review.length + " 项 · " + d.warnings.length + " 条提醒");
  setAgent("matcher", "done", "相关度 " + Math.round((payload.relevance || 0) * 100) + "%");
  setAgent("planner", "done", "生成 " + (payload.checklist || []).length + " 项待办");
  $("runbook-state").textContent = "本轮运行完成";
}

function runbookFail(message) {
  AGENTS.forEach((name) => setAgent(name, "fail", "已停止"));
  $("runbook-state").textContent = "运行失败：" + message;
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
    state.settings = s;
    $("setting-base").value = s.base_url || "";
    $("setting-model").value = s.model || "";
    $("setting-key").value = "";
    $("setting-email").textContent = s.email || "未绑定邮箱";
    $("setting-campus").value = s.campus && s.campus !== "unknown" ? s.campus : "haidian";
    $("setting-status").textContent = s.has_key
      ? "已保存 Key（尾号 " + s.key_hint + "），留空不会覆盖"
      : "尚未保存 Key，当前走规则模式";
    $("campus-section").classList.toggle("hidden", !!s.is_admin);
    const readonly = !!s.readonly;
    $("settings-readonly").classList.toggle("hidden", !readonly);
    $("settings-readonly").textContent = readonly
      ? "演示账号为只读模式：可以查看全部设置，但不能修改。注册自己的账号后即可编辑。"
      : "";
    document.querySelectorAll("#settings-dialog input, #settings-dialog select, #settings-dialog button").forEach((node) => {
      if (node.id === "setting-close") return;
      node.disabled = readonly;
    });
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

function setPasswordMethod(method) {
  state.passwordMethod = method;
  document.querySelectorAll("#password-method [data-method]").forEach((button) => {
    button.classList.toggle("active", button.dataset.method === method);
  });
  $("pw-old-wrap").classList.toggle("hidden", method !== "old");
  $("pw-code-wrap").classList.toggle("hidden", method !== "code");
}

function openSettings() {
  const dialog = $("settings-dialog");
  if (!dialog.open) dialog.showModal();
  setPasswordMethod("old");
  ["setting-campus-status", "setting-email-status", "setting-password-status"].forEach((id) => {
    setAuthStatus(id, "");
  });
  loadSettings();
}

async function sendSettingsCode(target, statusId, button) {
  if (state.settings && state.settings.readonly) return;
  const body = { target };
  if (target === "new") {
    body.new_email = $("setting-new-email").value.trim();
    if (!body.new_email) {
      setAuthStatus(statusId, "请先填写新邮箱", "error");
      return;
    }
  }
  button.disabled = true;
  button.textContent = "发送中…";
  try {
    const data = await api("/api/settings/code", { method: "POST", body: JSON.stringify(body) });
    if (data.dev) {
      const notice = data.notice || "开发模式：未真实发信";
      setAuthStatus(statusId, notice + (data.dev_code ? "，验证码 " + data.dev_code + "（已填入）" : "，请查看服务端日志"), "info");
      if (data.dev_code) {
        const targetId = target === "new" ? "setting-new-code" : target === "password" ? "setting-pw-code" : "setting-old-code";
        $(targetId).value = data.dev_code;
      }
    } else {
      setAuthStatus(statusId, "验证码已发送，10 分钟内有效", "success");
    }
    startCountdown(button);
  } catch (e) {
    setAuthStatus(statusId, "发送失败：" + e.message, "error");
    button.disabled = false;
    button.textContent = "发送验证码";
  }
}

async function saveCampus(button) {
  button.disabled = true;
  try {
    const s = await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ campus: $("setting-campus").value }),
    });
    state.settings = Object.assign({}, state.settings, s);
    if (state.user) state.user.campus = s.campus;
    setAuthStatus("setting-campus-status", "默认校区已保存为 " + (s.campus_label || s.campus), "success");
  } catch (e) {
    setAuthStatus("setting-campus-status", "保存失败：" + e.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function saveEmail(button) {
  const body = {
    old_code: $("setting-old-code").value.trim(),
    new_email: $("setting-new-email").value.trim(),
    new_code: $("setting-new-code").value.trim(),
  };
  if (!body.old_code || !body.new_email || !body.new_code) {
    setAuthStatus("setting-email-status", "原邮箱验证码、新邮箱、新邮箱验证码都要填写", "error");
    return;
  }
  button.disabled = true;
  try {
    const r = await api("/api/settings/email", { method: "POST", body: JSON.stringify(body) });
    state.user = Object.assign({}, state.user, r.user, { campus: state.user.campus });
    $("setting-email").textContent = r.user.email;
    $("setting-old-code").value = "";
    $("setting-new-email").value = "";
    $("setting-new-code").value = "";
    setAuthStatus("setting-email-status", "邮箱已更换为 " + r.user.email, "success");
  } catch (e) {
    setAuthStatus("setting-email-status", "更换失败：" + e.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function savePassword(button) {
  const method = state.passwordMethod || "old";
  const password = $("setting-new-password").value;
  const confirm = $("setting-new-confirm").value;
  if (password.length < 8) {
    setAuthStatus("setting-password-status", "新密码至少 8 位", "error");
    return;
  }
  if (password !== confirm) {
    setAuthStatus("setting-password-status", "两次输入的新密码不一致，已拒绝提交", "error");
    return;
  }
  const body = {
    method,
    old_password: method === "old" ? $("setting-old-password").value : "",
    code: method === "code" ? $("setting-pw-code").value.trim() : "",
    password,
    confirm,
  };
  if (method === "old" && !body.old_password) {
    setAuthStatus("setting-password-status", "请填写原密码", "error");
    return;
  }
  if (method === "code" && !body.code) {
    setAuthStatus("setting-password-status", "请填写邮箱验证码", "error");
    return;
  }
  button.disabled = true;
  try {
    await api("/api/settings/password", { method: "POST", body: JSON.stringify(body) });
    ["setting-old-password", "setting-pw-code", "setting-new-password", "setting-new-confirm"].forEach((id) => {
      $(id).value = "";
    });
    setAuthStatus("setting-password-status", "密码已修改，下次登录请使用新密码", "success");
  } catch (e) {
    setAuthStatus("setting-password-status", "修改失败：" + e.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function saveSettings(event) {
  event.preventDefault();
  if (state.settings && state.settings.readonly) return;
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
    state.settings = Object.assign({}, state.settings, s);
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
  runbookStart();
  try {
    const payload = await api("/api/extract", { method: "POST", body: JSON.stringify({ text: text, source_type: "text" }) });
    renderDraft(payload);
    runbookDone(payload);
  } catch (e) {
    runbookFail(e.message);
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
  $("draft").classList.add("hidden");
  $("draft").innerHTML = "";
  $("notice").value = "";
  $("stats").innerHTML = "";
  $("events").innerHTML = "";
  $("conflict").innerHTML = "";
  $("brief").textContent = "";
  state.payload = null;
  resetRunbook();
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
  $("settings-btn").classList.remove("hidden");
  startApp();
}

function updateCompareButton() {
  const button = $("admin-compare");
  const count = state.adminSelected.size;
  button.textContent = "对比选中 (" + count + ")";
  button.disabled = count === 0;
}

async function loadAdminUsers() {
  const box = $("admin-users");
  try {
    const data = await api("/api/admin/users");
    $("admin-count").textContent = data.users.length + " 人";
    box.innerHTML = "";
    data.users.forEach((u) => {
      const row = el("div", "user-row");
      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "user-check";
      check.title = "加入对比";
      check.checked = state.adminSelected.has(u.id);
      check.onchange = () => {
        if (check.checked) state.adminSelected.add(u.id);
        else state.adminSelected.delete(u.id);
        updateCompareButton();
      };
      row.appendChild(check);
      row.appendChild(el("div", "user-main", (u.name || "未命名") + (u.is_admin ? " · 管理员" : "")));
      row.appendChild(el("div", "user-email", u.email || "无邮箱"));
      row.appendChild(el("div", "user-count", (u.event_count || 0) + " 个事件"));
      row.appendChild(el("div", "user-time", (u.created_at || "").slice(0, 10)));
      const actions = el("div", "user-actions");
      const view = el("button", "btn ghost btn-mini", "查看");
      view.type = "button";
      view.onclick = () => loadAdminCompare([u.id]);
      actions.appendChild(view);
      if (!u.is_admin && u.id !== "u_demo") {
        const remove = el("button", "btn ghost btn-mini", "删除");
        remove.type = "button";
        remove.onclick = async () => {
          if (!confirm("删除用户并清理其事件和反馈？")) return;
          try {
            await api("/api/admin/users/" + u.id, { method: "DELETE" });
            state.adminSelected.delete(u.id);
            loadAdminUsers();
          } catch (e) { alert(e.message); }
        };
        actions.appendChild(remove);
      }
      row.appendChild(actions);
      box.appendChild(row);
    });
    updateCompareButton();
  } catch (e) {
    $("admin-count").textContent = e.message;
  }
}

function compareColumn(data) {
  const col = el("div", "compare-col");
  const head = el("div", "compare-head");
  head.appendChild(el("b", null, data.user.name || "未命名"));
  head.appendChild(el("span", "tiny", data.user.email || "无邮箱"));
  col.appendChild(head);
  const model = el("div", "detail-model");
  model.textContent = "模型：" + (data.model.model || "未配置")
    + " · 接口：" + (data.model.base_url || "未配置")
    + " · Key：" + (data.model.has_key ? "已配置（不显示）" : "未配置");
  col.appendChild(model);
  const list = el("div", "detail-events");
  if (!data.events.length) {
    list.appendChild(el("div", "tiny", "这个用户还没有事件。"));
  } else {
    data.events.forEach((e) => {
      const item = el("div", "detail-event");
      item.appendChild(el("span", null, e.title || "未命名事件"));
      item.appendChild(el("span", "tiny",
        (e.deadline_end || "未识别").slice(0, 16) + (e.done_at ? " · 已完成" : "")));
      list.appendChild(item);
    });
  }
  col.appendChild(list);
  return col;
}

async function loadAdminCompare(ids) {
  const box = $("admin-detail");
  box.classList.remove("hidden");
  box.innerHTML = "";
  try {
    const data = await api("/api/admin/users/detail?ids=" + encodeURIComponent(ids.join(",")));
    const head = el("div", "detail-head");
    head.appendChild(el("b", null, ids.length > 1 ? "用户对比 · " + data.users.length + " 人" : "用户详情"));
    const close = el("button", "btn ghost btn-mini", "关闭");
    close.type = "button";
    close.onclick = () => box.classList.add("hidden");
    head.appendChild(close);
    box.appendChild(head);
    const grid = el("div", "compare-grid" + (data.users.length > 1 ? " multi" : ""));
    data.users.forEach((item) => grid.appendChild(compareColumn(item)));
    box.appendChild(grid);
  } catch (e) {
    box.textContent = e.message;
  }
}

function enterAdmin(user) {
  state.user = user;
  state.adminSelected = new Set();
  $("auth-screen").classList.add("hidden");
  $("app-shell").classList.add("hidden");
  $("admin-screen").classList.remove("hidden");
  $("admin-name").textContent = (user.name || "管理员") + " · " + (user.email || "");
  updateCompareButton();
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

function setAuthStatus(target, message, type = "") {
  const node = typeof target === "string" ? $(target) : target;
  if (!node) return;
  node.textContent = message;
  node.classList.remove("error", "success", "info");
  if (type) node.classList.add(type);
}

async function sendCode(emailId, purpose, statusId, button) {
  const email = $(emailId).value.trim();
  if (!email) {
    setAuthStatus(statusId, "请先填写邮箱，再发送验证码", "error");
    return;
  }
  button.disabled = true;
  button.textContent = "发送中…";
  try {
    const data = await api("/api/auth/send-code", {
      method: "POST",
      body: JSON.stringify({ email, purpose }),
    });
    if (data.dev) {
      const notice = data.notice || "开发模式：未真实发信";
      setAuthStatus(
        statusId,
        notice + (data.dev_code ? "，验证码 " + data.dev_code + "（已填入）" : "，请查看服务端日志"),
        "info"
      );
      if (data.dev_code) {
        $(purpose === "register" ? "register-code" : "reset-code").value = data.dev_code;
      }
    } else {
      setAuthStatus(statusId, "验证码已发送到 " + email + "，10 分钟内有效", "success");
    }
    startCountdown(button);
  } catch (e) {
    setAuthStatus(statusId, "发送失败：" + e.message, "error");
    button.disabled = false;
    button.textContent = "发送验证码";
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const status = $("login-status");
  setAuthStatus(status, "登录中…", "info");
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: $("login-email").value.trim(), password: $("login-password").value }),
    });
    if (data.user.is_admin) location.href = "/admin";
    else location.href = "/app";
  } catch (e) {
    setAuthStatus(status, "登录失败：" + e.message, "error");
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const status = $("register-status");
  const password = $("register-password").value;
  const confirm = $("register-confirm").value;
  if (password !== confirm) {
    setAuthStatus(status, "两次输入的密码不一致，已拒绝注册", "error");
    return;
  }
  setAuthStatus(status, "注册中…", "info");
  try {
    await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        nickname: $("register-name").value.trim(),
        email: $("register-email").value.trim(),
        password,
        confirm,
        code: $("register-code").value.trim(),
      }),
    });
    location.href = "/app";
  } catch (e) {
    setAuthStatus(status, "注册失败：" + e.message, "error");
  }
}

async function handleReset(event) {
  event.preventDefault();
  const status = $("reset-status");
  const password = $("reset-password").value;
  const confirm = $("reset-confirm").value;
  if (password !== confirm) {
    setAuthStatus(status, "两次输入的密码不一致，已拒绝重置密码", "error");
    return;
  }
  setAuthStatus(status, "重置中…", "info");
  try {
    await api("/api/auth/reset", {
      method: "POST",
      body: JSON.stringify({
        email: $("reset-email").value.trim(),
        code: $("reset-code").value.trim(),
        password,
        confirm,
      }),
    });
    $("login-email").value = $("reset-email").value.trim();
    setAuthStatus(status, "密码已重置，请使用新密码登录", "success");
    switchAuthTab("login");
  } catch (e) {
    setAuthStatus(status, "重置失败：" + e.message, "error");
  }
}

async function handleDemo() {
  try {
    await api("/api/auth/demo", { method: "POST", body: JSON.stringify({}) });
    location.href = "/app";
  } catch (e) {
    setAuthStatus("login-status", "演示账号登录失败：" + e.message, "error");
  }
}

async function handleLogout() {
  try { await api("/api/auth/logout", { method: "POST", body: JSON.stringify({}) }); } catch (e) {}
  location.href = "/";
}

async function initAuth() {
  const path = location.pathname;
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

const themeNames = { system: "跟随系统", light: "浅色", dark: "深色" };
const themePickers = [];

function syncThemePickers() {
  const value = document.documentElement.dataset.theme || "system";
  themePickers.forEach((picker) => {
    picker.label.textContent = themeNames[value] || themeNames.system;
    picker.options.forEach((option) => {
      option.setAttribute("aria-selected", String(option.dataset.theme === value));
    });
  });
}

function applyTheme(theme) {
  const value = themeNames[theme] ? theme : "system";
  document.documentElement.dataset.theme = value;
  try { localStorage.setItem("nudge-theme", value); } catch (e) {}
  syncThemePickers();
}

function closeThemeMenu(picker) {
  picker.menu.hidden = true;
  picker.trigger.setAttribute("aria-expanded", "false");
}

function closeAllThemeMenus() {
  themePickers.forEach(closeThemeMenu);
}

function openThemeMenu(picker) {
  closeAllThemeMenus();
  picker.menu.hidden = false;
  picker.trigger.setAttribute("aria-expanded", "true");
  const selected = picker.options.find((option) => option.getAttribute("aria-selected") === "true");
  if (selected) selected.focus();
}

function setupThemePicker(root) {
  const picker = {
    root,
    trigger: root.querySelector(".theme-trigger"),
    menu: root.querySelector(".theme-menu"),
    label: root.querySelector(".theme-label"),
    options: Array.from(root.querySelectorAll(".theme-option")),
  };
  picker.trigger.onclick = () => {
    if (picker.menu.hidden) openThemeMenu(picker);
    else closeThemeMenu(picker);
  };
  picker.options.forEach((option) => {
    option.onclick = () => {
      applyTheme(option.dataset.theme);
      closeThemeMenu(picker);
      picker.trigger.focus();
    };
  });
  picker.trigger.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openThemeMenu(picker);
    }
  });
  picker.menu.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const current = picker.options.indexOf(document.activeElement);
    const delta = event.key === "ArrowDown" ? 1 : -1;
    const next = (current + delta + picker.options.length) % picker.options.length;
    picker.options[next].focus();
  });
  themePickers.push(picker);
}

document.querySelectorAll("[data-theme-picker]").forEach(setupThemePicker);
applyTheme(document.documentElement.dataset.theme || "system");

document.addEventListener("click", (event) => {
  themePickers.forEach((picker) => {
    if (!picker.root.contains(event.target)) closeThemeMenu(picker);
  });
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const open = themePickers.filter((picker) => !picker.menu.hidden);
  if (!open.length) return;
  closeAllThemeMenus();
  open[0].trigger.focus();
});

$("settings-btn").onclick = openSettings;
$("admin-settings").onclick = openSettings;
$("setting-close").onclick = () => $("settings-dialog").close();
$("setting-test").onclick = testConnection;
$("settings-form").onsubmit = saveSettings;
$("setting-campus-save").onclick = () => saveCampus($("setting-campus-save"));
$("setting-email-save").onclick = () => saveEmail($("setting-email-save"));
$("setting-password-save").onclick = () => savePassword($("setting-password-save"));
$("setting-old-send").onclick = () => sendSettingsCode("old", "setting-email-status", $("setting-old-send"));
$("setting-new-send").onclick = () => sendSettingsCode("new", "setting-email-status", $("setting-new-send"));
$("setting-pw-send").onclick = () => sendSettingsCode("password", "setting-password-status", $("setting-pw-send"));
document.querySelectorAll("#password-method [data-method]").forEach((button) => {
  button.onclick = () => setPasswordMethod(button.dataset.method);
});
$("admin-compare").onclick = () => {
  const ids = Array.from(state.adminSelected);
  if (ids.length) loadAdminCompare(ids);
};

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
