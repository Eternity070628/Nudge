const $ = (id) => document.getElementById(id);
const state = { draft: null, samples: [], payload: null };
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

  box.appendChild(field("截止时间", fmt(d.deadline.end) + (d.deadline.raw ? "" : "（原文无明确时间）"),
    d.deadline.confidence, d.evidence.deadline));

  const matBox = el("div", "mats");
  if (d.materials.length) d.materials.forEach((m) => matBox.appendChild(el("div", "mat", m.name)));
  else matBox.appendChild(el("div", "mat", "未识别到材料清单"));
  box.appendChild(field("需要材料", matBox, d.confidence.materials, d.evidence.materials));

  const sub = d.submission || {};
  const subText = { web: "线上系统提交", email: "邮件提交 " + (sub.email || ""), offline: "线下提交 " + (sub.location || ""), unknown: "未识别提交方式" }[sub.channel] || "未识别";
  box.appendChild(field("提交方式", subText, d.confidence.submission, d.evidence.submission));

  const aud = d.audience || {};
  const audText = [aud.raw, (aud.grades || []).join(" / "), (aud.colleges || []).join(" / ")].filter(Boolean).join("；") || "未写明";
  box.appendChild(field("适用对象", audText, d.confidence.audience, d.evidence.audience));

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
    const r = await api("/api/events", { method: "POST", body: JSON.stringify({ draft: state.payload.draft, user_id: "u_demo" }) });
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
    $("engine").textContent = h.llm ? "大模型已接入 · " + model : "规则模式 · 未配模型 Key";
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
    const data = await api("/api/dashboard?user_id=u_demo");
    renderStats(data.stats);
    renderConflicts(data.conflicts);
    renderEvents(data.events);
    $("brief").textContent = "📌 " + data.brief.brief;
    $("ics").href = "/api/calendar/demo-token-2026.ics?user_id=u_demo";
    $("list-count").textContent = data.events.length + " 项";
    $("board-hint").textContent = data.stats.saved_minutes + " 分钟已省下";
  } catch (e) {
    $("board-hint").textContent = "无法连接后端";
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
  list.slice(0, 9).forEach((e) => {
    const row = el("div", "ev " + (e.urgency || "later"));
    const left = el("div");
    left.appendChild(el("div", "t", e.title));
    const meta = [CAT[e.category] || "其他", e.submission.channel === "offline" ? "需线下" : "", (e.checklist || []).length ? e.checklist.length + " 项待办" : ""].filter(Boolean).join(" · ");
    left.appendChild(el("div", "m", meta));
    const right = el("div", "d");
    const d = e.days_left;
    const big = d === null ? "?" : d < 0 ? "过期" : d === 0 ? "今天" : d + " 天";
    right.appendChild(el("b", null, big));
    right.appendChild(el("span", null, fmt(e.deadline_end).slice(5)));
    const done = el("span", "x", "标记完成");
    done.title = "办完了？点一下从列表移除";
    done.style.cursor = "pointer";
    done.onclick = async () => { await api("/api/events/" + e.id + "/done?user_id=u_demo", { method: "POST" }); loadBoard(); };
    right.appendChild(done);
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

$("settings-btn").onclick = openSettings;
$("setting-cancel").onclick = () => $("settings-dialog").close();
$("setting-test").onclick = testConnection;
$("settings-form").onsubmit = saveSettings;

loadHealth();
loadSettings();
loadSamples();
loadBoard().then(demoMode);
