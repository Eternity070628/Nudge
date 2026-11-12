# 部署到 PythonAnywhere（GitHub 一推送，网页就更新）

一条链路：

```
git push main
   └─ GitHub Actions（.github/workflows/deploy-pythonanywhere.yml）
        └─ POST https://<用户名>.pythonanywhere.com/api/deploy   (X-Deploy-Token)
             ├─ git fetch + reset --hard origin/main
             ├─ pip install -r pythonanywhere/requirements.txt
             └─ touch pythonanywhere/wsgi.py → mod_wsgi 重载
```

为什么是这条链路：PythonAnywhere 免费帐号没有常驻任务，也不保证能开 SSH，但它**允许出网访问 github.com**。
所以让 PA 自己拉代码、自己触发重载，是免费方案里最稳的一种，也顺便成为答辩里「自动部署」的证据。

## 一、账号与 Web App（网页操作，约 5 分钟）

1. 注册 / 登录 https://www.pythonanywhere.com （Beginner 免费计划够用）。
2. Dashboard → New console → Bash，拉代码：

   ```
   git clone https://github.com/Eternity070628/Nudge.git ~/nudge
   ```

3. Web → Add a new web app → **Manual configuration** → Python 3.10 → Next。
4. 同一页：**Source code** 填 `/home/<用户名>/nudge`，**Working directory** 同。
5. 建虚拟环境（Bash console）：

   ```
   mkvirtualenv nudge --python=/usr/bin/python3.10
   pip install -r ~/nudge/pythonanywhere/requirements.txt
   ```

   回到 Web 页，**Virtualenv** 填 `/home/<用户名>/.virtualenvs/nudge`。
6. 打开 **WSGI configuration file**（`/var/www/<用户名>_pythonanywhere_com_wsgi.py`），清空后只留三行：

   ```python
   import os, runpy
   os.environ["NUDGE_DEPLOY_TOKEN"] = "换成一串随机长 token"
   application = runpy.run_path("/home/<用户名>/nudge/pythonanywhere/wsgi.py")["application"]
   ```

   token 用 `python -c "import secrets;print(secrets.token_urlsafe(32))"` 生成，别用弱口令。
7. （可选，加速静态文件）Web → Static files：URL `/static/` → Directory `/home/<用户名>/nudge/backend/app/static`。
8. 点绿色 **Reload**，打开 `https://<用户名>.pythonanywhere.com`。
   应看到 Nudge 首页，右上角是「规则模式」——这是预期：免费帐号出网白名单里没有 api.deepseek.com。

## 二、让 GitHub 推送触发部署

仓库 Settings → Secrets and variables → Actions → New repository secret，加两个：

| Name | Value |
|---|---|
| `PA_DEPLOY_URL` | `https://<用户名>.pythonanywhere.com/api/deploy` |
| `PA_DEPLOY_TOKEN` | 与 WSGI 里那串 token 完全一致 |

之后每次 push 到 `main`，Actions 里的 `deploy-pythonanywhere` 会跑，日志里能看到 `HTTP 200` 与：

```json
{"ok":true,"before":"9231979","after":"<新提交>","pip":"ok","reload":"scheduled"}
```

验证方式：改 README 一个字 → push → 等 30 秒 → 刷新页面。也可以在 Actions 页面点 **Run workflow** 手动触发。

## 三、手动部署 / 兜底

PA 的 Bash console 里：

```
bash ~/nudge/pythonanywhere/deploy.sh
```

免费帐号还能加一个 Scheduled task（Dashboard → Tasks，每天一次）跑同一行，作为 webhook 不可用时的兜底。

## 四、免费版要知道的事

| 项 | 说明 |
|---|---|
| 闲置休眠 | 一段时间没人访问会睡，首次请求慢 1–2 秒，之后正常 |
| 出网白名单 | github.com、PyPI 可访问；DeepSeek / MaaS 不行，所以默认 `NUDGE_DISABLE_LLM=1` 走规则引擎 |
| 数据库 | `~/nudge/backend/data/nudge.db`，不在 git 里，`git reset --hard` 不会删；备份就下载这个文件 |
| CPU 配额 | 每天有秒数上限，演示前别跑压测 |
| 自定义域名 | 免费版只能用 `<用户名>.pythonanywhere.com` |

想开 LLM 有两条路：把模型域名加进 PA 白名单（付费），或换一个可访问的 OpenAI 兼容网关，在 WSGI 里加 `MAAS_BASE_URL` 环境变量。

## 五、排错

- **502 / 一直转圈**：看 Web 页的 error log（`/var/log/<用户名>.pythonanywhere.com.error.log`），最常见是 WSGI 路径写错、虚拟环境里没装 a2wsgi。
- **`/api/deploy` 返回 403**：token 不一致（WSGI 里的 vs GitHub secret）。
- **`/api/deploy` 返回 500 且 git 报 `could not read Username`**：仓库不是公开的，或远端地址写错；公开仓库拉取不需要凭据。
- **页面 404 但 `/api/health` 正常**：静态目录被 PA 的 Static files 映射覆盖，检查 `/static/` 映射路径。
- **改了代码但页面没变**：看 Actions 日志；再确认 `git log` 里部署的 commit 是不是最新的（响应的 `after` 字段）。

## 六、和评审的关系

- 「部署上线」加分项：一个可直接访问的 URL + 一条自动部署链路。
- 「真实用户验证」：把链接发给同学，`/api/feedback` 的三键反馈会写进 `feedback` 表，`/api/dashboard` 的 `feedback` 字段可截图当证据。
- 答辩一句话：push → Actions → PA 自己拉代码自己重载，全程不需要登录服务器。
