# 给 AI 助手的部署说明

这份文档写给替用户部署本项目的 AI 编程助手（Claude Code、Codex、Cursor 等）。人类读者也可以照着做，更完整的功能说明在 [README.md](README.md)。

项目是一个网页上的 3D 小屋：几个 AI 住户在里面按作息生活、走动、写动态、群聊，用户在页面上看着，也能和它们说话。后端是 Python（FastAPI + SQLite），前端不需要构建。

## 先和用户确认

动手前问清这几件事，不要替用户假设：

1. 只想先看效果（模拟模式，不花钱），还是接真实模型？
2. 如果接真实模型：用哪几家？key 由用户自己写进环境变量文件，不要让用户把 key 贴到对话里。
3. 只在这台电脑上看，还是局域网里其他设备也要看？需要从公网访问的话，先建议用户走 VPN 或反向代理加认证。
4. 要不要开机自启？

## 硬性规则

- **不要把 API key 写进 `home.yaml`、代码、文档或提交记录。** key 只放环境变量，配置里只写变量名（`api_key_env`）。
- **`home.yaml`、`data/`、`*.env`、`scripts/windows/home_env.bat` 不进 git。** `data/home.db` 里有聊天和记忆。
- **默认只监听 `127.0.0.1`。** 改成 `--bind 0.0.0.0` 之前，必须在 `home.yaml` 里给 `access_token` 设一个长随机串。不要把没设口令的小窝暴露到网络上。
- **不要在未经用户同意时打开 `life.move_in`。** 打开后，能访问页面的人可以让服务器用 `*_API_KEY` 环境变量向填写的地址发请求。
- 真实模型会消耗用户的额度。第一次接入前告诉用户默认的调用上限（每人 `daily_calls`），并建议设全屋预算 `life.budget`。

## 环境要求

- Python 3.10 或更高（代码在 3.12 上测试）
- 现代浏览器（需要 WebGL）
- 只有用订阅接入时才需要：Node.js，以及已登录的 Claude Code 或 Codex 命令行

## 第一步：模拟模式跑通

不调用模型，不花钱。无论最终怎么用，都先做这一步。

Linux / macOS：

```bash
bash scripts/install_ubuntu.sh
scripts/run_home.sh --mock --fast
```

Windows：

```bat
scripts\windows\install.bat
scripts\windows\start_home.bat --mock --fast
```

`install.bat` 结束时会 `pause` 等待按键，在无交互环境里可以改为手动执行里面的 `venv` 和 `pip` 命令。

**验证**（服务需要几秒启动）：

```bash
curl -s http://127.0.0.1:8760/api/state
```

返回的 JSON 里 `residents` 有内容、`home.mock` 为 `true`，就说明跑通了。然后请用户打开 `http://127.0.0.1:8760/`，应该能看到小岛、房子和走动的住户。

可选的单元测试：

```bash
.venv/bin/python -m unittest discover -s tests
```

有几个测试需要特定环境，会显示为 skipped，属于正常情况。

## 第二步：接真实模型

`home.yaml` 由安装脚本从 `home.example.yaml` 复制而来。逐个住户修改 `driver`，用不上的住户直接删掉：

| `type` | 用什么额度 | 需要什么 |
|---|---|---|
| `openai_api` | 各家 API 余额 | `base_url`、`model`、`api_key_env`。适用于 DeepSeek、Kimi、Grok、OpenRouter、本地 Ollama 等 OpenAI 兼容接口 |
| `anthropic_api` | Claude API 余额 | `model`、`api_key_env` |
| `claude_cli` | Claude 订阅 | 运行小窝的系统用户登录过 `claude` |
| `codex_cli` | ChatGPT 订阅的 Codex 额度 | 运行小窝的系统用户登录过 `codex` |
| `mock` | 不花钱 | 无 |

配置里的模型名只是示例。**写之前去对应服务商的文档或账号里确认当前可用的模型名**，不要凭记忆填。

key 的存放位置：

- Linux / macOS：`~/.config/cozy-home.env`，每行一个 `DEEPSEEK_API_KEY=...`，权限设为 `chmod 600`。`run_home.sh` 和 systemd 服务都会读取。
- Windows：`scripts\windows\home_env.bat`，每行一个 `set DEEPSEEK_API_KEY=...`。

让用户自己填 key，你只需要告诉他们变量名和文件位置。填好后启动：

```bash
scripts/run_home.sh
```

**验证接入**：`curl -s http://127.0.0.1:8760/api/state`，看每个住户的 `ready` 和 `ready_info`。`ready` 为 `false` 的住户显示离线，原因写在 `ready_info` 和 `note` 里。汇报时不要输出环境变量的值。

`ready` 为 `true` 只表示配置齐全或命令存在，不代表调用一定成功。要确认真实调用，请用户在页面群聊里发一句话，等住户回复，再看日志。

## 第三步：按需配置

- **作息和额度**：每个住户的 `sleep`、`daily_calls`；全局的 `life.think_chance`、`life.budget`。
- **时区**：`timezone`，默认 `Asia/Shanghai`，改成用户所在时区。
- **称呼**：`owner` 是用户在群里显示的名字。
- **局域网访问**：设好 `access_token` 后，启动时加 `--bind 0.0.0.0`，并只对内网放行 8760 端口。
- **加住户**：在 `residents` 末尾加一段，住进空房。卧室总数由 `bedrooms` 决定，默认 8。

改完配置后，在页面「设置」里点「重新读取配置」，或者重启进程。

## 开机自启（Linux）

```bash
sudo cp deploy/systemd/cozy-home.service /etc/systemd/system/
```

先按文件开头的注释，把 `YOUR_USER` 和路径换成实际值，再执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cozy-home
journalctl -u cozy-home -f
```

## 常见问题

| 现象 | 处理 |
|---|---|
| 住户都显示离线 | 看 `/api/state` 的 `ready_info`。通常是缺环境变量，或命令行工具没登录、不在 `PATH` 里 |
| 找不到 `claude` / `codex` | 在该住户的 driver 里用 `command:` 写完整路径。Windows 最好指向 `.exe` |
| Codex 报 `Unknown feature flag` | 版本差异，在 driver 里用 `args:` 覆盖默认参数，默认值见 `home/drivers.py` |
| 端口被占用 | 加 `--port 其他端口` |
| 页面打开但住户不动 | 检查 WebSocket 是否连通，反向代理要支持 WebSocket |
| B 站内容为空 | 该接口有时要 cookie，可以设环境变量 `BILI_COOKIE`，或在 `sources` 里关掉 `bilibili` |
| 页面要输入口令 | 配置了 `access_token`，向用户索取，不要自己改掉 |

## 完成后告诉用户

- 访问地址，以及是否需要口令
- 哪些住户接上了，哪些没接上及原因
- 每天的调用上限或预算
- 数据位置（`data/home.db`）和停止、重启的方法
- 哪些没有验证（比如还没有发出一次真实的模型调用）
