# Nudge · 校园截止管家

> **Not an alarm. A nudge.**
> 闹钟只负责响，Nudge 负责让你现在就动。

线上运行：**https://eternity0628.pythonanywhere.com** 

把「群里转发的通知」变成「今天该做什么」的 AI Agent。
面向高校学生：教务通知、竞赛报名、奖学金材料、讲座、四六级、在读证明——一句话或一张截图丢进来，10 秒内变成带截止时间、材料清单和提醒计划的待办。

---

## 1. 为什么不是又一个待办 App

学生真正的问题不是「没有日历」，而是：

1. **通知是自然语言**，截止时间藏在「11月20日17:00前」「本周五」里；
2. **信息在群里刷过去**，没人会手动录入；
3. **材料清单比截止时间更致命**——截止前 3 天才发现要学院盖章；
4. **同一天撞车**（11/20 既有四六级又有国奖），计划直接崩。

所以 Nudge 的定位是：**不是闹钟，是管家**。
它回答的不是「几点截止」，而是「**11/20 这天你有 3 个截止、2 个要盖章，建议 15 日前办完**」。

## 2. 四个 Agent 怎么分工

```mermaid
flowchart LR
    A[通知文本 / 截图 OCR / PDF] --> B[Extractor 抽取]
    B -->|事件 JSON + 字段证据| C[Verifier 校验]
    C -->|置信度 + 需确认标记| D[Matcher 匹配]
    D -->|0-1 相关度 + 理由| E[Planner 编排]
    E --> F[日程 / 材料清单 / D-7·D-3·D-1 提醒 / 撞车预警]
    B -. 抽不出就返回空+原因，不猜 .-> C
```

| Agent | 输入 → 输出 | 关键设计 |
|---|---|---|
| **Extractor** | 通知原文 → 事件 JSON | 规则优先（快、离线、可解释），LLM 只做补充；**每个字段必须回填原文证据**；校区按「本部 / 西土城 → 海淀，昌平 → 沙河」识别；提交地点也单独校验校区，未强调时沿用事件/默认校区 |
| **Verifier** | 事件 JSON + 原文 → 置信度 | 逐字段比对证据；证据不在原文里，该字段置信度直接降到 0.3 并标「需确认」；保留上游写入的校区冲突提示 |
| **Matcher** | 事件 + 用户画像 → 相关度 | 年级/院系/兴趣加权，无关的沉底，避免「通知洪水」 |
| **Planner** | 事件 → 计划 | 材料 checklist、D-7/D-3/D-1 提醒、同日 ≥2 件撞车预警、周报 |

**一个刻意的取舍**：去重、排序、写日历、发提醒这些**确定性的活全部用代码做**，编排器是状态机而不是 LLM。
LLM 只出现在「理解自然语言」这一层——因为那才是它擅长、且错了也能被证据链抓住的地方。

## 3. 反幻觉：字段可以点回原文

界面里每个字段下面都挂着「原文：……」，来自 Extractor 的 evidence 字段。
Verifier 会检查这段引文是否**逐字**出现在通知里；不在，就降分并提示人工确认。
这让「AI 编了一个 11 月 30 日的截止时间」在结构上不可能悄悄发生。

## 4. 目录结构

```
nudge/
├─ backend/
│  ├─ app/
│  │  ├─ main.py            # FastAPI 路由
│  │  ├─ auth.py            # 登录 / 注册 / 重置 / 会话 / 管理员
│  │  ├─ models.py          # Pydantic 契约（事件 JSON 就是 API 契约）
│  │  ├─ db.py              # SQLite：users / events / feedback / settings
│  │  ├─ config.py          # .env 读取、MaaS 配置、Graph 邮箱配置
│  │  ├─ agents/
│  │  │  ├─ extractor.py    # 规则抽取 + 可选 LLM 兜底
│  │  │  ├─ verifier.py     # 证据校验 + 置信度聚合
│  │  │  ├─ matcher.py      # 画像相关度
│  │  │  ├─ planner.py      # 紧急度 / checklist / 提醒 / 撞车
│  │  │  └─ llm.py          # DeepSeek OpenAI 兼容接口
│  │  ├─ services/
│  │  │  ├─ accounts.py     # 口令哈希、会话、验证码发放与消费
│  │  │  ├─ mailer.py       # Microsoft Graph 发信 + 设备码授权 CLI
│  │  │  ├─ seed.py         # 6 条真实感示例通知
│  │  │  └─ ics.py          # 导出 .ics 日历订阅
│  │  └─ static/            # 单页前端（原生 JS，零构建）
│  └─ requirements.txt
├─ eval/
│  ├─ eval_set.json         # 20 条人工标注用例
│  ├─ run_eval.py           # 字段级准确率
│  └─ report.md             # 评测报告（自动生成）
└─ docs/
   ├─ ui.png                # 主界面
   └─ ui-draft.png          # 抽取结果（含证据链）
```

## 5. API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | /api/health | 健康检查 + LLM 可用性 |
| POST | /api/extract | 文本 → draft + 相关度 + checklist + 紧急度 |
| POST | /api/events | 确认后落库（按 title+deadline 去重） |
| GET | /api/events | 事件列表 |
| POST | /api/events/{id}/done | 标记完成 |
| GET | /api/dashboard | 统计、撞车预警、周报 |
| GET | /api/calendar/{token}.ics | 日历订阅（含 VALARM 提前 1 天） |
| POST | /api/feedback | 三键反馈（有用/无关/时间错） |
| GET | /api/settings | 读取模型接入、当前邮箱、默认校区与是否只读 |
| POST | /api/settings | 保存接入地址、模型、API Key、默认校区（Key 不回显；存了 Key 自动切 `model` 模式） |
| POST | /api/settings/code | 修改邮箱/密码时发送验证码（原邮箱 / 新邮箱 / 密码用途） |
| POST | /api/settings/email | 原邮箱验证码 + 新邮箱验证码，双重校验后更换邮箱 |
| POST | /api/settings/password | 原密码或邮箱验证码二选一，修改密码 |
| GET | /api/llm-test?kind=chat\|models | 真发一次最小请求，返回状态码/报错原文，用来排查 Key 与模型名 |
| GET | /api/admin/users/detail?ids=a,b | 管理端并排查看多个用户的事件与模型配置 |
| POST | /api/deploy | CI 钩子：git pull + 重载（需 `NUDGE_DEPLOY_TOKEN`，未配置时不存在） |

## 6. 模型接入

默认配置指向 DeepSeek：
- 接入地址：`https://api.deepseek.com`
- 模型：`deepseek-flash`（`/v1/models` 实际返回的可用 id；早期 `deepseek-v4.1-flash` 不被接口接受）
- API Key：不写进仓库。首次使用点页面右上角「设置 → 模型接入」填写；也可以设置环境变量 `MAAS_API_KEY`。

没有 Key 时自动回退纯规则，页面状态显示「规则模式」。填写后 `/api/health` 的 `llm` 变为 `true`，抽取走「规则 + 模型补充」，模型输出仍要过 `verifier` 的逐字证据校验。Key 只保存在本机 `backend/data/nudge.db`（已 gitignore），不会进入 release 源码包；这是单机演示的本地明文存储，生产环境应改用密钥管理服务。

每个用户在右上角「设置 → 模型接入」里保存自己的接入地址、模型和 Key，互不覆盖；管理员在用户详情里可以查看对应用户的接入地址、模型和「是否已配置 Key」，但不显示 Key 内容。

## 6.1 登录与多用户

进入站点先登录。支持邮箱+密码登录、昵称/邮箱/密码/验证码注册、邮箱验证码重置密码；密码框可切换明文查看。登录成功后跳转到独立的 `/app` 或 `/admin` 页面，不和登录表单共用一个滚动页；管理员邮箱登录自动进入管理端，可查看和删除用户；删除用户会清理其事件、反馈和会话。

右上角「设置」统一管理默认校区、账号邮箱、登录密码与模型接入。修改邮箱需要原邮箱验证码 + 新邮箱验证码双重校验；修改密码可以用原密码，也可以走邮箱验证码，二选一。管理员设置里不含校区，其余一致。公开演示账号 `u_demo` 能看到全部设置项，但所有写操作都被前端禁用、后端返回 403。

### 6.1.1 线上真发信：Brevo（走 443，免费额度 300 封/天）

出站 SMTP 被封死的免费主机，用 Brevo 的 HTTPS 邮件 API 就能真发：

1. 注册 https://www.brevo.com/（免费版每天 300 封）；
2. **Senders & IP → Add a sender** 填发件地址（例如学校邮箱），去那个邮箱点确认邮件里的链接——**没验证发件地址会被 400 拒绝**；
3. **SMTP & API → API Keys → Create a new API key**，复制 `xkeysib-...`；
4. 写进线上 `.env`：

```bash
MAIL_TRANSPORT=brevo
BREVO_API_KEY=xkeysib-...
BREVO_SENDER=2025212080@bupt.cn
BREVO_SENDER_NAME=Nudge
NUDGE_EMAIL_DEV=0
```

5. 点 Reload，`GET /api/auth/mail-status` 应该返回 `mode: "brevo"`、`real_sending: true`；
6. 登录页不展示发信邮箱与邮件通道说明；验证码仍会真实发出并进入收件箱。

常见报错都做了中文映射：key 错是 401、发件地址没验证是 400、超额度是 429、Brevo 侧故障是 5xx——**任何情况下都不会假装发送成功**。

两个实测坑，代码里都处理了：

- **免费主机要走出站代理**：PythonAnywhere 免费版把出站请求锁在 `proxy.server:3128` 后面，不设代理会直接 `Errno 101 Network is unreachable`。`MAIL_PROXY` 留空时会在 PythonAnywhere 上自动识别（也可显式写 `MAIL_PROXY=http://proxy.server:3128`）。
- **同域代发会被拒**：发件人用学校邮箱、收件人也填同域地址时，腾讯企业邮会回 `550 Mime from domain is a local domain`（防伪造）。Brevo 的接口是异步的，会先回 200，所以这里**在发送前就拦下并明确报错**，不会让用户以为码已经发出去了。注册时请换其它邮箱（QQ / Gmail 实测可正常进收件箱）。

![登录页发信状态](docs/login-mail-status.png)

保留 `u_demo` 公开演示账号，登录页有「进入公开演示账号」；新注册用户从空看板开始。登录态使用 HttpOnly Cookie session；密码只存 PBKDF2 哈希。

## 7. 主题

右上角「跟随系统 / 浅色 / 深色」三档，登录页、用户端和管理端都能切换；选择存浏览器 `localStorage`，刷新后保留。颜色走 `:root` 深色变量与 `[data-theme="light"]` 浅色变量；跟随系统时用 `prefers-color-scheme`，不需要刷新。下拉菜单也使用同一组主题变量，深色下不会出现系统默认白底菜单。

## 8. 线上部署

线上运行地址：**https://eternity0628.pythonanywhere.com** （PythonAnywhere 免费计划）

链路：GitHub push → Actions → PA 上的 `/api/deploy` 自己 `git reset --hard origin/main`（依赖只在 `requirements.txt` 变化时安装），uvicorn 的 `--reload` 监听到文件变化后自动重启 worker，不需要 SSH，也不需要常驻任务。

- 完整步骤、Secrets 配置、免费版限制、排错：[`docs/deploy-pythonanywhere.md`](docs/deploy-pythonanywhere.md)
- 形态说明：PA 免费帐号只能有 1 个 web app，本帐号是 **custom command** 类型（Command 字段只读），所以由 `~/start_opc.sh` 用 `uvicorn --uds "$DOMAIN_SOCKET" --reload --reload-dir backend` 拉起 Nudge；免费账号的 reload API 返回 403，重载靠 uvicorn 的 reloader
- 手动兜底：PA 上执行 `bash ~/nudge/pythonanywhere/deploy.sh`
- 线上是 PythonAnywhere 免费帐号。启动脚本里 `NUDGE_DISABLE_LLM=1` 只是「还没配 Key 时的保守默认」；页面「设置 → 模型接入」存了 Key 就以页面为准（`llm_mode=model`），`/api/health` 的 `llm` 变 `true`。实测 `api.deepseek.com` 在 PA 可出网（返回 401 = 连通），`api.modelarts-maas.com` 会被 403 拦
- 排查模型问题优先用 `GET /api/llm-test?kind=models`：能拿到模型列表说明 Key 与地址都对，只剩模型名要换

## 9. 已知限制

- **OCR 未接入**：当前只支持粘贴文本；页面提示里的「截图 OCR」是预留文案，尚未接入上传和 OCR 接口。
- **真实发信依赖外部配置**：验证码支持 Microsoft Graph / SMTP / Brevo 三条通道，由 `MAIL_TRANSPORT` 选择；没有凭据时进入开发模式，验证码只在页面/日志显示，不会假装发送成功。真实投递还受发件地址验证、免费额度、代理和校园网出站限制影响。
- **验证码只做了基本节流**：同一邮箱 + 用途 60 秒内不能重发，验证码 10 分钟有效且一次性使用；连续输错没有单独的失败次数锁定。
- **登录安全边界**：密码以 PBKDF2 哈希保存，登录态用 HttpOnly Cookie session；当前没有学校统一身份/SSO、登录失败锁定或二次验证。
- **管理端做用户列表、并排对比和删除**：可勾选多个用户同时查看事件与模型配置；删除会连带清理该用户的事件关联、反馈、会话和验证码；没有禁用/启用、角色分配、管理员重置密码；内置 `u_admin`、`u_demo` 不可删除。
- **演示账号是公开的**：`u_demo` 通过「进入公开演示账号」免密进入，示例数据共享；它只用于演示，不能当真实学生账号。
- **大模型是可选补充**：默认 DeepSeek `deepseek-flash`；没有 Key 或调用失败自动回退规则抽取。评测脚本强制规则模式，20/20 是当前自建 20 条评测集的结果，不是生产准确率。
- **单机 SQLite**：没有多实例、任务队列、备份和审计日志；数据恢复依赖 `backend/data/*.db` 本地文件。
- **范围边界**：不做爬教务系统、代提交报名、外部推送通道、权威校历解析；`.ics` 订阅需要用户自己在手机日历里点一次。
- **时区固定 Asia/Shanghai**：跨时区交换生场景未处理。
