# 部署到 PythonAnywhere（GitHub 一推送，网页就更新）

线上地址：**https://eternity0628.pythonanywhere.com** （免费计划，出网白名单不含 DeepSeek，线上固定走规则引擎）

一条链路：

```
git push main
   └─ GitHub Actions（.github/workflows/deploy-pythonanywhere.yml）
        └─ POST https://<用户名>.pythonanywhere.com/api/deploy   (X-Deploy-Token)
             ├─ git fetch --depth=1 + reset --hard origin/main
             ├─ pip install -r pythonanywhere/requirements.txt
             └─ uvicorn --reload 监听到文件变化，自动重启 worker
```

为什么是这条链路：PythonAnywhere 免费帐号没有常驻任务，也不保证能开 SSH，但它**允许出网访问 github.com 和 api.pythonanywhere.com**。
所以让 PA 自己拉代码，是免费方案里最稳的一种，也顺便成为答辩里「自动部署」的证据。

重载怎么来的：启动命令带 `--reload --reload-dir backend`，`git reset --hard` 改写文件后 uvicorn 自己重启 worker。
（试过 PythonAnywhere 的 web app reload API，免费账号的 custom-command 应用返回 `403 You do not have permission to perform this action.`，于是放弃了那条路。）

## 一、实际采用的形态：custom-command + uvicorn --uds

免费帐号只能有 **1 个 web app**。本帐号上那个 app（`eternity0628.pythonanywhere.com`）创建时选的是 **custom command**，
配置页的 **Command 字段是只读的**——网页上改不了，只能改它指向的脚本内容。所以实际做法是：

1. Bash console 里克隆代码、建虚拟环境（每条独立执行）：

   ```bash
   git clone --depth 1 https://github.com/Eternity070628/Nudge.git ~/nudge
   python3.10 -m venv ~/.virtualenvs/nudge
   ~/.virtualenvs/nudge/bin/pip install -q -r ~/nudge/backend/requirements.txt
   ```

2. 备份原来的启动脚本，然后让 `~/start_opc.sh`（Command 指向的那个）启动 Nudge：

   ```bash
   cp ~/start_opc.sh ~/start_opc.sh.bak.$(date +%Y%m%d)
   cat > ~/start_opc.sh <<'EOF'
   #!/bin/bash
   export NUDGE_DATA="$HOME/nudge/backend/data"
   export NUDGE_DISABLE_LLM="1"
   export NUDGE_DEPLOY_TOKEN="<随机长 token>"
   export PA_USERNAME="<用户名>"
   export PA_DOMAIN="<用户名>.pythonanywhere.com"
   cd "$HOME/nudge"
   exec "$HOME/.virtualenvs/nudge/bin/uvicorn" --app-dir "$HOME/nudge/backend" --uds "$DOMAIN_SOCKET" app.main:app
   EOF
   chmod +x ~/start_opc.sh
   ```

   要点：
   - **必须监听 `$DOMAIN_SOCKET`**（PA 注入的环境变量），不能自己挑端口；
   - 必须带 `--reload --reload-dir "$HOME/nudge/backend"`：custom-command 应用没有 WSGI 文件，也没有可用的 reload API，改动后的重启只能靠 uvicorn 自己的 reloader；
   - 同名的 `~/start_nudge.sh` 内容相同，留作换 app 或本地调试用。

3. Web 页点绿色 **Reload**，然后验证：

   ```bash
   curl -s https://<用户名>.pythonanywhere.com/api/health
   # {"ok":true,"llm":false,"model":"deepseek-v4.1-flash","time":"..."}
   ```

   `llm:false` 是预期的：免费版出网白名单里没有 api.deepseek.com，线上走规则引擎。

4. 不切 web app 也能先自测：在 console 里用临时 socket 起一次，不占用线上入口。

   ```bash
   DOMAIN_SOCKET=/tmp/nudge.sock nohup bash ~/start_opc.sh > /tmp/nudge.log 2>&1 &
   curl -s --unix-socket /tmp/nudge.sock http://localhost/api/health
   pkill -f 'uds /tmp/nudge.sock'
   ```

## 二、让 GitHub 推送触发部署

仓库 Settings → Secrets and variables → Actions → New repository secret，加两个：

| Name | Value |
|---|---|
| `PA_DEPLOY_URL` | `https://<用户名>.pythonanywhere.com/api/deploy` |
| `PA_DEPLOY_TOKEN` | 与启动脚本里的 `NUDGE_DEPLOY_TOKEN` 完全一致 |

之后每次 push 到 `main`，Actions 里的 `deploy-pythonanywhere` 会跑，日志里能看到 `HTTP 200` 与：

```json
{"ok":true,"before":"c4a678a","after":"cbfcaf1","pip":"skipped","reload":"uvicorn-reload"}
```

验证方式：改 README 一个字 → push → 等 30 秒 → 刷新页面。也可以在 Actions 页面点 **Run workflow** 手动触发。

依赖安装的策略：**只有 `requirements.txt` 真的变了才会装**（钩子里用 `git diff --name-only before after` 判断）。
PythonAnywhere 免费版的 web app 进程拉 PyPI 会偶发 `Network is unreachable`，而每次部署都重装一遍既慢又吵。
真需要强制装，把启动脚本里的 `NUDGE_DEPLOY_PIP` 设成 `1`；强制跳过设成 `0`。

安全注意：`NUDGE_DEPLOY_TOKEN` 是随机长 token，只存在 PA 的脚本和 GitHub Secret 里；接口用 `hmac.compare_digest` 比对，
没配 token 直接 404，错了返回 403，且只能把代码 reset 到 `origin/main`，不能执行任意命令。

## 三、手动部署 / 兜底

PA 的 Bash console 里：

```bash
bash ~/nudge/pythonanywhere/deploy.sh
```

免费帐号还能加一个 Scheduled task（Dashboard → Tasks，每天一次）跑同一行，作为 webhook 不可用时的兜底。

## 四、免费版要知道的事

| 项 | 说明 |
|---|---|
| 闲置休眠 | 一段时间没人访问会睡，首次请求慢 1–2 秒，之后正常 |
| 出网白名单 | github.com、PyPI、api.pythonanywhere.com 可访问；DeepSeek / MaaS 不行，所以默认 `NUDGE_DISABLE_LLM=1` 走规则引擎 |
| 数据库 | `~/nudge/backend/data/nudge.db`，不在 git 里，`git reset --hard` 不会删；备份就下载这个文件 |
| CPU 配额 | 每天 100 秒左右，演示前别跑压测 |
| 自定义域名 | 免费版只能用 `<用户名>.pythonanywhere.com` |
| 并发 console | 最多 2 个，长时间挂着会占用 |

想开 LLM 有两条路：把模型域名加进 PA 白名单（付费），或换一个可访问的 OpenAI 兼容网关，加 `MAAS_BASE_URL` 环境变量。

## 五、排错

- **一直转圈 / 502**：看 Web 页的 error log（`/var/log/<用户名>.pythonanywhere.com.error.log`），最常见是 `$DOMAIN_SOCKET` 没被透传、venv 里缺依赖、`app-dir` 写错。
- **`/api/deploy` 返回 403**：token 不一致（启动脚本里的 vs GitHub secret）。
- **`/api/deploy` 返回 200 但页面没变**：确认启动命令里还有 `--reload`；再看 `https://<用户名>.pythonanywhere.com/api/health` 的 `commit` 字段是不是最新提交。reload 之后 worker 重启要 2–5 秒，别立刻刷新。
- **reload 之后整站 502**：多半是 `--reload-dir` 指到了不存在或被 git 删掉的目录，看 error log 里 uvicorn 的启动行。
- **`/api/deploy` 返回 500 且 git 报 `could not read Username`**：仓库不是公开的，或远端地址写错；公开仓库拉取不需要凭据。
- **页面 404 但 `/api/health` 正常**：静态目录被 PA 的 Static files 映射覆盖，检查映射路径（本项目由 FastAPI 自己托管静态文件，不需要单独映射）。
- **改了代码但页面没变**：看 Actions 日志；再确认响应里的 `after` 是不是最新 commit。

## 六、附：WSGI（mod_wsgi）备选形态

如果哪天能新建一个 **Manual configuration** 的 web app，可以不用 uvicorn，直接让 mod_wsgi 加载 ASGI 包装：

```python
# /var/www/<用户名>_pythonanywhere_com_wsgi.py
import os, runpy
os.environ["NUDGE_DEPLOY_TOKEN"] = "<随机长 token>"
application = runpy.run_path("/home/<用户名>/nudge/pythonanywhere/wsgi.py")["application"]
```

`pythonanywhere/wsgi.py` 会用 `a2wsgi.ASGIMiddleware` 包住 FastAPI app，并默认 `NUDGE_DATA=backend/data`、`NUDGE_DISABLE_LLM=1`。
这种形态下 mod_wsgi 会自己感知 WSGI 文件的变化，不需要 reloader。

## 七、和评审的关系

- 「部署上线」加分项：一个可直接访问的 URL + 一条自动部署链路（push 即上线）。
- 「真实用户验证」：把链接发给同学，`/api/feedback` 的三键反馈会写进 `feedback` 表，`/api/dashboard` 的 `feedback` 字段可截图当证据。
- 答辩一句话：push → Actions → PA 自己拉代码、自己重载，全程不需要登录服务器。
