# Nudge 在华为云码道里的提示词手册

> 这份手册是「怎么让码道把这个项目做出来」的操作剧本，不是作文。
> 每一节是一段**可以直接整段复制**的提示词，按顺序发。
> 每段都写了「发之前贴什么」「发完怎么验收」——验收不过就别往下走，否则错误会累积。
>
> **本手册只给规格和验收，不给实现。** 每一行代码都应该由码道写出来：这是赛制要求的「核心 AI 编程工具」痕迹，也是答辩时你能讲清楚「哪一段是它写的、哪里是我纠的」的底气。

---

## 0. 三条使用纪律

1. **一轮只干一件事。** 把「抽取 + 校验 + 前端」塞进一轮，码道会给你一个能跑但全是坑的东西，你还没法定位。
2. **贴文件，不要描述文件。** 改已有代码时，把当前文件内容贴进去，比说「那个 extractor 你记得吧」可靠一百倍。
3. **每轮结束都要它自证。** 固定追加一句：「列出你改了哪些文件、每个文件改了什么、以及你用什么命令验证过、输出是什么。」

> 赛制要求提交**码道使用痕迹**：每轮结束后截图（对话 + 代码 diff + 运行结果），存到 `codearts_proof/`，命名 `01-骨架.png`、`02-extractor.png`……
> 最后把这些截图 + 导出的对话 md 一起打包，这是白送的分数。

---

## 1. 开场：项目总纲（只发一次，作为长期上下文）

```text
你是我的结对编程工程师，我们要在 3 天内做一个能跑、能演示、能答辩的 AI Agent 应用，叫 Nudge（校园截止管家）。

【它是什么】
把学生收到的自然语言通知（教务通知、竞赛报名、奖学金评审、讲座），变成结构化事件：标题、截止时间、适用对象、材料清单、提交方式；再按用户画像算相关度，最后编排成日程、材料 checklist 和 D-7/D-3/D-1 提醒，并对同一天多个截止做撞车预警。

【硬约束，请始终遵守】
1. 技术栈：Python 3.12 + FastAPI + SQLite + 原生 HTML/CSS/JS 单页。不要引入 Node、npm、React、构建工具、ORM、Docker 之外的重依赖。前端必须零构建、双击可用。
2. 所有业务代码在 nudge/backend 下，前端静态文件在 backend/app/static/。不要新建第二个项目根目录。
3. 中文注释，函数短小，单个函数不超过 60 行。每个抽取规则都要能说清「它匹配什么、给多少置信度」。
4. 抽取结果必须带 evidence（原文引文），引文必须逐字来自原文；找不到证据就留空并标记需确认，绝对不许编造日期。
5. 不确定的地方返回空值 + 原因，不要用「大概是」糊过去。
6. 每轮结束时，列出：改了哪些文件、每个文件的变化、你运行了什么命令、输出是什么。

【工作方式】
我说「做第 N 步」，你就只做第 N 步；做完等我验收，不要顺手把后面的也写了。
如果你认为我的要求有更好的做法，先用三句话说明，再按我说的做——除非那会导致跑不起来。
```

---

## 2. 第 1 步：项目骨架 + 数据契约

**发之前**：什么都不用贴，空目录即可。

```text
做第 1 步：搭骨架和契约，不写业务逻辑。

1. 创建目录 nudge/backend/app/{agents,services,static}、nudge/backend/data、nudge/eval、nudge/docs。
2. 写 backend/app/models.py，用 Pydantic 定义这些结构（字段名就用我给的名字）：
   - Deadline: start, end, raw, confidence
   - Material: name, required, note
   - Audience: grades(list[str]), majors(list[str]), colleges(list[str]), raw
   - Submission: channel(字面量 "web"|"email"|"offline"|"unknown"), url, email, location
   - EventDraft: title, category(字面量 "competition"|"scholarship"|"lecture"|"affairs"|"exam"|"activity"|"other"),
     deadline, audience, materials(list[Material]), submission, evidence(dict[str,str]),
     source, importance(int), confidence(dict[str,float]), overall_confidence(float),
     needs_review(list[str]), warnings(list[str])
   - ExtractRequest: text, source_type, url, published_at
   - EventCreate: draft, user_id
3. 写 backend/app/config.py：MAAS_BASE_URL、MAAS_API_KEY、MAAS_MODEL(默认 "pangu-pro")、DB_PATH、REMIND_DAYS=[7,3,1]、LOAD_WARN_THRESHOLD=2、TZ="Asia/Shanghai"。
4. 写 backend/app/main.py：一个 FastAPI 实例 + GET /api/health 返回 {"ok": true, "llm": <bool>}，暂时不接数据库。
5. 写 backend/requirements.txt，只包含 fastapi、uvicorn、pydantic。

验收标准：python -m uvicorn app.main:app --port 8000 能起来，访问 /api/health 返回 ok。
```

---

## 3. 第 2 步：Extractor（最重要的一步，值得花两轮）

**发之前**：贴 models.py。

```text
做第 2 步：写 backend/app/agents/extractor.py，输入一段中文通知原文，输出 EventDraft。

先写纯规则版本，不要调用任何大模型。要求：

【截止时间】
- 支持这些线索词：截止时间、截止日期、报名截止、提交截止、申报截止、截至、截止、截稿日期、"X 前/之前"、即日起至 X、"活动时间/讲座时间/时间："。
- 日期支持：2026年11月14日 / 11月14日 / 2026-11-14 / 可带 23:59 或 17:00。
- 区间写法「报名时间：2026年11月10日 9:00 至 2026年11月20日 12:00」要取**后者**作为截止。
- 「24:00」要换算成**次日 00:00**，不能报错也不能丢。
- 没写年份时，补当前年份；如果算出来已经过去超过 30 天，认为说的是明年。
- 相对时间（今天/明天/本周五/下周一二/月底）按「通知发布时间」解析，不是按现在。
- 完全找不到就返回空 Deadline，confidence=0，并在 warnings 里写"未识别到截止时间"。

【其他字段】
- title：第一行，去掉「关于」前缀保留原意，去掉结尾的"的通知/公告"，超过 46 字截断加省略号。
- category：按关键词计分选最高：竞赛类(大赛/竞赛/比赛/挑战赛)、奖学金类(奖学金/助学金/评优)、讲座类(讲座/报告会/沙龙/宣讲)、考试类(考试/补考/四六级)、办事类(办理/盖章/证明/转专业/缴费/评教)、活动类(志愿服务/献血/公益活动)。打平时优先级：竞赛 > 奖学金 > 讲座 > 考试 > 办事 > 活动。
- audience：**只在**含「对象/面向/申请资格/参赛资格」的句子里找年级(20xx级/大一~大四/研一~研三)和学院；不要把「可跨学院」「请登录教务系统」当成学院名。
- materials：找「提交材料/需提交/材料清单/须提供」后面编号或顿号分隔的条目，最多 8 条；过滤掉"提交方式/提交地点/联系方式/注意事项"这类标题行。
- submission：出现邮箱→email（记下邮箱）；出现 http 链接→web；出现"提交至/交至/现场/地点/携带/窗口"→offline；出现"系统/在线提交/网上报名"→web；都没有→unknown。
- importance：1-5，出现 学分/保研/推免/评优/国家级/强制 加一分，最高 5。
- evidence：**每个字段都要给出原文中逐字存在的片段**（deadline/title/category/audience/materials/submission 六个键），没有证据就给空串。
- confidence：每个字段给 0-1 的置信度，规则越明确越高；材料是按编号推断的就给 0.7 左右。

导出一个 extract(text: str, published_at: str | None = None) -> EventDraft。
另外写一个 rule_extract(text, anchor_date) 内部函数，方便单测。

验收标准：给我 3 条你自造的通知（一条竞赛、一条奖学金、一条讲座），跑出结果并打印每个字段 + evidence。我要看到 evidence 是原文里真实存在的句子。
```

> **常见跑偏**：它会把「提交方式：邮箱」整段塞进 materials；会把「跨学院」当学院名；会把「24:00」抛异常。
> 发现一次就单独发一条：「c06 的 24:00 没解析，修 _parse_date_token，并补一条单测」。

---

## 4. 第 3 步：Verifier（反幻觉的关键）

```text
做第 3 步：写 backend/app/agents/verifier.py。

输入：原文 text + 上一步的 EventDraft。
输出：修正后的 EventDraft（补齐 overall_confidence、needs_review、warnings）。

规则：
1. 字段权重：title 0.12、category 0.08、deadline 0.34、audience 0.10、materials 0.22、submission 0.14。
2. 对六个字段逐个检查 evidence：如果 evidence 非空但**不是原文的子串**（逐字比对，允许去掉首尾空白），把该字段 confidence 降到 0.3，并在 warnings 里写「<字段> 的证据不在原文中，已降级」。
3. deadline 为空 → deadline.confidence = 0.25，needs_review 加 "deadline"。
4. 任一字段 confidence < 0.7 → 加入 needs_review。
5. overall_confidence = 按权重加权平均（缺失字段按 0 计）。
6. 不要在这里改字段内容，只做校验和打分——改内容会让证据链断掉。

验收标准：构造一条「evidence 写了原文没有的日期」的假数据，跑一遍，看 overall_confidence 明显下降且 warnings 有提示。
```

---

## 5. 第 4 步：Matcher + Planner

```text
做第 4 步：写 matcher.py 和 planner.py。

matcher.match(draft, user) -> (float, list[str])：
- 基数 0.3。
- 用户兴趣命中事件类别 +0.25；年级在 audience.grades 里 +0.25，明确不匹配 -0.15；
  院系命中 +0.15，明确不匹配 -0.20；importance >= 4 +0.10。
- 结果夹在 0~1。
- 同时返回**人话理由**，例如「你的兴趣里有「竞赛」」「面向 2024级，正好覆盖你」，理由要能直接显示在界面上。

planner.py：
- days_left(event, now)：按天算，可为负。
- urgency：overdue / today / urgent(≤3天) / soon(≤7天) / later。
- build_checklist(draft)：材料条目 + 「确认提交入口（<url 或邮箱或地点>）」+ 「提交后保留凭证」，每项带 done 字段。
- build_reminders(deadline, remind_days=[7,3,1])：每个提醒日生成 {at, channel, text}，另外加一条「提前 12 小时」的兜底提醒。
- detect_conflicts(events)：同一天 ≥2 个截止 → {date, count, titles, advice}，advice 要给出可执行建议（例如「建议最晚提前 3 天完成 1 件」）。
- weekly_brief(events)：生成一段 80 字内的中文周报，必须包含「本周N个截止 + 最近的是哪个 + 建议先做哪个」。

验收标准：给我看 6 条不同日期的事件跑出来的 urgency 分布、checklist、撞车预警、周报文本。
```

---

## 6. 第 5 步：数据库与 API

```text
做第 5 步：写 db.py 和完整路由。

db.py（sqlite3，不要 ORM）：
- 表 users(id, name, grade, college, major, interests_json, calendar_token)
- 表 events(id, title, category, deadline_start, deadline_end, payload_json, source_json, created_at)
- 表 user_events(user_id, event_id, relevance, reasons_json, status, created_at)
- 表 feedback(id, user_id, event_id, kind, created_at)
- init() 建表；插入示例用户 u_demo（张同学 / 2024级 / 计算机学院 / 兴趣：竞赛、编程、奖学金 / token=demo-token-2026）。
- save_event(draft, user_id, relevance, reasons)：dedup_key = sha1(title + deadline_end)[:16]，重复就返回 (event, False)。
- list_events(user_id)：按 deadline_end 升序，附带 days_left、urgency、checklist。

路由：
- POST /api/extract {text, source_type} → {draft, relevance, reasons, checklist, preview_urgency}
- POST /api/events {draft, user_id} → 落库
- GET /api/events?user_id=
- POST /api/events/{id}/done?user_id=
- GET /api/dashboard?user_id= → {stats:{upcoming,urgent_7d,materials,saved_minutes}, conflicts, brief, events}
- GET /api/weekly?user_id=
- POST /api/feedback {user_id,event_id,kind}，kind ∈ useful|not_relevant|wrong_deadline
- GET /api/samples → 6 条示例通知
- POST /api/seed → 把 6 条示例跑一遍四 Agent 后落库

saved_minutes 的计算要写清楚口径（每个事件按节省 12 分钟计），别写成魔法数不解释。

验收标准：用 curl 依次调 /api/seed、/api/dashboard，把 JSON 贴给我看；我要看到 stats 和 conflicts 有真实数字。
```

---


## 6.5 设计规格：不用设计稿，码道也能做出能看的界面

**怎么用**：第 6 步之前，先把下面的规格整段发给码道，让它确认「已理解，开始实现」。

```text
下面是 Nudge 前端的完整设计规格。请先复述你对布局、色彩、状态三部分的理解（不超过 10 行），
我说「开始」你再写代码。规格里没写的，按你的判断补，但不要引入外部资源。

【画布与栅格】
- 设计基准 1440 宽；内容最大宽 1400，左右内边距 48；顶部 header 高 72。
- 主体两栏：左 1fr、右 1.15fr，栏间距 20；窗口 <980px 塌成单栏（左栏在上），内边距 20。
- header：44×44 圆角 12 的渐变方块（字母 N，深色字）+ 主标题 20px/700 + 一行 slogan 12px muted；右侧引擎状态胶囊。

【色彩 token（写成 CSS 变量，禁止散落硬编码）】
--bg:#0a0d14  --panel:rgba(20,26,40,.72)  --line:rgba(255,255,255,.07)
--text:#e8ecf4  --muted:#8b95a8  --faint:#5b6478
--accent:#f7b267  --accent2:#f4845f  --grad:linear-gradient(135deg,#f7b267,#f4845f)
--ok:#4ade80  --warn:#fbbf24  --bad:#f87171  --info:#60a5fa
- 背景：--bg 上叠两团 520px 径向光晕（左上 accent 8%、右下 #4a6cf7 10%），blur 120px，纯 CSS，不用图片。
- 主色只用于：主按钮、步骤序号、强调数字、证据竖线、链接 hover。其余一律中性灰，别通篇发光。

【字体】
- font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif；数字加 font-variant-numeric:tabular-nums。
- 标签 11px/1.4 + letter-spacing .04em + muted；正文 13px/1.65；卡片标题 15px/600；
  统计数字 30px/700（后缀单位 14px muted）；页脚 11.5px faint。

【组件】
1. 面板：--panel 底 + 1px --line 边 + 圆角 18 + backdrop-filter blur(10px) + inset 高光 + 大投影；内边距 22。
2. 面板头：22px 步骤圆标（accent 10% 底 / accent 文字 / 1px accent 22% 边）+ 14px/600 标题；右侧计数 12px muted。
3. textarea：最小高 168，底 rgba(0,0,0,.35)，1px --line，圆角 12，padding 14；focus 边框 rgba(247,178,103,.55)
   + 外发光 0 0 0 3px rgba(247,178,103,.12)，不要 outline。
4. chips：高 30、圆角 999、padding 0 12、12px；hover 变 accent 12% 底 + accent 35% 边。
5. 按钮：主按钮高 40、圆角 11、--grad 底、#1a1206 字 600、hover 提亮 6%、active 下压 1px；
   次按钮透明底 + 1px --line + 正文色。禁用态 40% 不透明 + cursor:not-allowed。
6. 统计卡：4 列 grid gap 10；padding 14 16；数字 30px/700；风险值用色（7 天内到期 >0 用 --warn，逾期用 --bad）。
7. 事件行：左侧 3px 竖条按紧急度上色（逾期 bad / 今天 #fb923c / ≤3天 warn / ≤7天 info / 其他 rgba(255,255,255,.14)）；
   padding 12 14；hover 底 rgba(255,255,255,.03)；标题 13.5px/500 最多两行省略；
   meta 行 11.5px muted（类别 · N 项待办 · 截止）；右侧天数 15px/700 + 日期 11.5px muted。
8. 置信度徽标：11px、padding 2 7、圆角 6；≥85% 绿底 12%/绿字，70-85% 黄，<70% 红；字段行末尾还要有黄色「需确认」小徽标。
9. 原文证据：2px rgba(247,178,103,.35) 左竖线 + 11.5px muted，最多两行、超出渐变淡出；title 属性放全文。
10. 撞车预警条：rgba(248,113,113,.08) 底 + rgba(248,113,113,.25) 边 + 圆角 12，左 ⚠，正文 12.5px，给出可执行建议。
11. 周报条：rgba(247,178,103,.06) 底 + 18% 边；首行 11px accent 小标题「本周简报」，正文 12.5px。
12. 页脚链接行 12px muted；「订阅到手机日历（.ics）」hover 变 accent 加下划线。

【状态】
- 空闲：结果卡隐藏；右栏统计为 0 + 空态（纯 CSS 虚线圆 + 「把通知贴进来，或点上面的示例」）。
- 加载：按钮文字改「抽取中…」并禁用；结果区骨架屏 3 条灰条 shimmer 1.4s。
- 成功：结果卡 220ms 淡入上移 6px，自动 scrollIntoView({block:"nearest"})。
- 失败：结果区红底条 + 具体原因 + 保留用户输入，不要静默失败。
- 需确认：字段行右侧黄点，顶部汇总「N 项需要你确认」。
- 已完成事件：整行 45% 透明 + 标题删除线 + 「已完成」，可撤销。

【动效与禁止】
- 只允许三处动效：面板入场 400ms 淡入上移 8px；行 hover 120ms；按钮 active 1px。
- 禁止：无限循环动画、弹跳、外部字体/CDN/图标库/图片、紫色渐变、圆角 >24px、纯黑背景、卡片套卡片超过两层。

【可访问性】
- 按钮有 aria-label；结果区 aria-live="polite"；正文对比度 ≥7:1、muted ≥4.5:1；Ctrl/Cmd+Enter 触发抽取；Tab 顺序左→右。

【文案风格】
- 中文、短句、动词开头。按钮「抽取为事件」「载入示例数据」；
- 空态「把通知贴进来，或点上面的示例」；
- 失败「没抽到截止时间：这段文字里没有可识别的日期，请补一句『11 月 20 日截止』」。
```

---

## 7. 第 6 步：前端（零构建单页）

```text
做第 6 步：按 6.5 的设计规格，写 static/index.html + style.css + app.js。原生 JS，不要框架、不要打包。

页面结构（左右两栏，最大宽 1400px）：
左栏「① 粘贴一条通知」：textarea + 示例 chips + 两个按钮（抽取为事件 / 载入示例数据）+ 抽取结果卡片 + 四步流程说明。
右栏「② 你真正要做什么」：4 个统计卡（待办截止 / 7 天内到期 / 待交材料 / 预计省下时间）、撞车预警条、按截止时间排序的事件列表、周报、.ics 订阅链接。

抽取结果卡片必须展示：
- 标题、类别、重要性、总体可信度（百分比）、待确认项数
- 每个字段一行：截止时间 / 需要材料 / 提交方式 / 适用对象
- 每个字段下面一行小字「原文：<evidence>」，这是反幻觉的视觉证据
- 置信度用颜色区分（≥85% 绿、70-85% 黄、<70% 红）
- 底部：相关度百分比 + 「确认无误，加入我的截止」按钮

交互：点「抽取为事件」调 /api/extract 渲染卡片；点确认调 /api/events 后刷新看板。
视觉：深色底（#0a0d14）+ 琥珀色主色（#f7b267 → #f4845f 渐变）+ 玻璃质感卡片，圆角 14-20px，不要 Bootstrap。

另外加一个演示模式：URL 带 ?demo=2 时，自动填入第 2 条示例并跑一遍抽取（录屏用一镜到底）。

验收标准：给出页面截图，并说明你用什么方式截的图（我希望是 headless Chrome 命令行，不要装 Playwright）。
```

> **常见跑偏**：引入 Tailwind CDN 或 npm 包。直接说：「不要 CDN，手写 CSS，我要断网也能演示。」

---


## 7.5 前端验收与打磨：让「能跑」变成「能看」

**发之前**：什么都别贴，让它自己审视自己的产出。

```text
现在做前端自检，不要重写。逐条对照下面 12 项，输出一张表：项目｜是否通过｜证据（文件:行号）。

1. 所有颜色都来自 CSS 变量，grep 一次，硬编码 hex 出现次数为 0（验证脚本输出给我）。
2. 桌面 1440 宽下两栏比例接近 1:1.15，内容不溢出、不出现横向滚动条。
3. 980px 以下塌成单栏，且顺序是「输入 → 结果 → 看板」。
4. 空态、加载态、错误态、需确认态，四种状态都能手动触发，并截图给我。
5. 置信度颜色分档正确（≥85 绿 / 70-85 黄 / <70 红），且 <70 的字段同时出现在 needs_review 汇总里。
6. 每条 evidence 都是原文子串：写个临时脚本对 6 条示例跑一遍，打印不一致的条目（应为空）。
7. 键盘可达：Tab 能走完所有按钮，Ctrl/Cmd+Enter 能触发抽取。
8. 断网（DevTools Offline）刷新后页面仍正常渲染，无 CDN 请求失败。
9. 抽到无截止时间的通知时，界面显示「需确认」而不是 1970 年或空白。
10. 点击「确认无误，加入我的截止」后，右栏统计与列表立即更新，无需刷新页面。
11. 事件完成后可撤销，撤销后统计回滚。
12. 字号层级只有 4 档（30/15/13/11.5），没有 12px、14px 之类的碎片字号。

最后回答两个问题：你认为最丑的一处是哪里？为什么？
```

**打磨一轮**（可选，但答辩前值得做）：

```text
只改视觉，不改结构、不改逻辑。按优先级改三件事，每件给出前后各一张截图：
1. 层级：把「标题 / 数值 / 说明」的对比拉开——该大的更大、该淡的更淡，不要所有字都 13px。
2. 留白：面板内边距、卡片间距统一成 4 的倍数；同一屏内出现两种以上间距体系的地方收敛掉。
3. 克制：主色出现的地方不超过 6 处；删掉任何「为了好看」但无信息量的装饰。

改完告诉我：动了哪几个 CSS 变量/类，为什么。
```

> **别让它自由发挥审美**。码道在「结构对不对」上很强，在「好不好看」上很容易滑向紫渐变 + 大圆角 + 发光。
> 你要做的是给约束（规格），然后只对偏差发指令。

---

## 8. 第 7 步：日历订阅 + 部署

```text
做第 7 步：导出日历 + 部署。

1. services/ics.py：生成标准 RFC5545 文本，VCALENDAR + 每个事件一个 VEVENT（DTSTART/DTEND/SUMMARY/DESCRIPTION），
   加 VALARM 提前 1 天提醒；长行按 73 字节折行（续行以空格开头）；中文用 UTF-8，DTSTAMP 用 UTC。
2. 路由 GET /api/calendar/{token}.ics：按 token 找用户，返回 text/calendar。
3. 写 Dockerfile（python:3.12-slim，装 requirements，暴露 8000，CMD uvicorn）。
4. 写 docs/deploy.md：华为云 ECS 上从 0 到可访问的步骤（安全组开 8000、docker build/run、用 IP 访问、以及可选绑定域名）。
5. 写 .dockerignore 和 .gitignore（排除 data/*.db、__pycache__）。

验收标准：把 .ics 内容贴出来，我要能看到 BEGIN:VCALENDAR、VEVENT、VALARM；并用手机日历实际订阅一次验证。
```

---


## 8.5 可选：截图 / PDF 上传（做之前先想清楚值不值）

> 加分点，但也是容易翻车的一步。**先做文字版把全链路跑通，再回来加这一步**；
> 如果 11/18 还没跑通 OCR，直接放弃——答辩时说「截图入口做了降级提示」不丢分，现场解析超时才丢分。

```text
做可选功能：支持粘贴截图（PNG/JPG）或上传 PDF，先转成文字再走已有的 extract 流程。

硬约束：
1. 不许引入需要联网下载大模型的依赖（不要 torch、不要 paddle 全家桶）。优先调用华为云 OCR/MaaS 的 HTTP 接口，用环境变量配 key。
2. 没配 key 时，前端上传按钮可见但点击后提示「当前未配置 OCR，请直接粘贴文字」，并且这条提示要能被评委看懂是在诚实降级，不是 bug。
3. 图片不超过 5MB，只接受 png/jpg/jpeg/pdf；后端校验 content-type，超限返回 413 带中文原因。
4. OCR 结果先回显在一个可编辑的 textarea 里，让用户改错字，再点「抽取为事件」——不要 OCR 完直接抽取。
5. 解析失败要有明确错误：「这张图里没识别出文字，换一张清晰点的截图试试」。

验收：上传一张真实通知截图，走完「上传 → 回显文字 → 抽取 → 入看板」，并截图；
再断掉 key 试一次，确认降级提示正确。
```

---

## 9. 第 8 步：评测与调优（答辩的硬通货）

```text
做第 8 步：建评测集和评测脚本。

1. eval/eval_set.json：20 条中文校园通知，字段 {id, label, text, expect:{deadline_end, category, channel}}。
   要求覆盖不同句式：截止时间：/ 报名截止：/ 截稿日期：/ 「A 至 B」区间 / 24:00 跨天 / 「X 前」/ 活动时间：/ 没有明确截止（期望 null）。
   文本要有真实感：带「各学院：」「一、二、三、」编号、材料清单、邮箱、地点。
2. eval/run_eval.py：跑 extract+verify，逐条对比，输出 markdown 表格 + 汇总：
   截止时间完全正确率、误差≤1天率、类别准确率、提交渠道准确率；写进 eval/report.md。退出码：全对 0，否则 1。
3. 跑一遍，把失败用例逐条给我：期望 vs 实际，你判断是哪个规则没覆盖。

不许为了让数字好看而改期望值；改的是抽取规则，不是答案。
```

> 这一步是做给评委看的：**你有度量，所以你的「准确率」才有意义**。
> 答辩时说「20 条自建集，截止时间 20/20；但这是自建集，下一步扩到真实通知」，比吹「99% 准确」可信十倍。

---

## 10. 第 9 步：材料产出

```text
做第 9 步：产出提交材料，不要写代码。

1. 更新 README.md：一句话定位、四个 Agent 分工表（含 mermaid 图）、目录结构、运行命令、API 表、评测结果、三分钟演示脚本、已知限制、和赛制的对应关系。
2. 写 docs/pitch.md：一页纸 PPT 提纲，8 页，每页给「标题 + 3 个要点 + 一句口播」。
3. 写 docs/demo-script.md：3 分钟逐秒脚本，含「说什么 / 屏幕上做什么 / 万一失败怎么圆」。
4. 写 docs/codearts-proof.md：说明码道使用痕迹怎么整理（每步截图 + 对话导出 + 关键 diff 片段）。

所有文案要求：中文、短句、不吹牛、每个数字都能在代码或评测里找到出处。
```

---

## 11. 卡住时的三种追问模板

**它改坏了**：
```text
刚才那轮让 /api/dashboard 报 500。把完整 traceback 贴出来给我看，先定位再改，不要重写整个文件。
修完告诉我：根因是什么、改了几行、怎么验证的。
```

**它开始瞎编**：
```text
你刚才说「已支持 PDF 解析」，但代码里没有 PDF 相关依赖和函数。请把这条声明撤回，并且以后只描述你实际写过的代码。
如果需要 PDF，先告诉我需要装什么、改动哪些文件，等我确认。
```

**它做丑了**：
```text
这版界面问题在层级：标题、正文、说明几乎一样重，视觉上糊成一片。
只改 CSS，不改 DOM 结构和 JS：把标题提到 15px/600，正文保持 13px，说明降到 11.5px 且用 muted 色；
主色出现的地方砍到 6 处以内。改完给我截图对比。
```

**它偷懒只做一半**：
```text
你说完成了，但我对照验收清单，第 4 项（四种状态可触发）和第 10 项（加入后免刷新更新）没做。
请只补这两项，并逐项告诉我怎么手动验证，不要顺手改别的。
```

**它想跑偏技术栈**：
```text
停。我们说好零构建、不引入 Node。请用原生 JS 实现同样的效果，并说明为什么原来的方案在你看来更好——我要评估取舍，但先按约束做。
```

---

## 12. 码道痕迹清单（提交前对着勾）

- [ ] 每轮对话截图，含时间戳，存 `codearts_proof/0X-<步骤>.png`
- [ ] 导出的对话 md（码道一般支持导出，没有就自己复制成 md）
- [ ] 3-5 段关键 diff 截图：extractor 正则、verifier 证据校验、planner 撞车逻辑
- [ ] 一次「码道写错 → 我发现 → 修正」的完整闭环截图（**这个最能体现人机协作**，评委爱看）
- [ ] 最终代码里 `.codearts` 或相关配置文件若存在，一并保留
