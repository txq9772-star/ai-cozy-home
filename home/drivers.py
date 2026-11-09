"""接入层：住户的「大脑」从哪来。两种接入方式，统一成 generate(system, prompt) → 一段文字。

  订阅接入（access = subscription）
    claude_cli     Claude Code 无交互模式，用这台机器上登录的 Claude 订阅
    codex_cli      Codex CLI，用这台机器上登录的 ChatGPT 订阅
  API 接入（access = api）
    openai_api     OpenAI 兼容接口：DeepSeek、Kimi、Grok、OpenRouter、本地 Ollama / vLLM 等
    anthropic_api  Claude 官方 API
  mock             模拟住户：不调用模型，不花钱

小窝里只让模型「说话」：CLI 全部关掉工具、只读沙箱、不存会话，跑在一个空目录里。
刷到的标题和简介只当作资料放进提示词。命令行参数都可以在配置里覆盖（CLI 升级改了参数时用）。
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

IS_WIN = os.name == "nt"


@dataclass
class Gen:
    ok: bool
    text: str = ""
    error: str = ""
    kind: str = ""          # 出错类型：auth 未登录/key 无效，missing 没装/没配，limit 额度/限流，timeout，other
    meta: dict[str, Any] = field(default_factory=dict)


def classify(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("not logged in", "please log in", "/login", "unauthorized", "invalid api key",
                            "authentication", "401", "auth.json", "login required", "invalid_api_key", "forbidden")):
        return "auth"
    if any(k in t for k in ("usage limit", "rate limit", "rate_limit", "429", "limit reached", "quota", "insufficient",
                            "402", "credit balance", "overloaded")):
        return "limit"
    if "unknown feature flag" in t or "unknown option" in t or "unexpected argument" in t:
        return "missing"
    return "other"


def short(s: Any, n: int = 200) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "…"


class Driver:
    access = "api"
    product = ""

    def __init__(self, cfg: dict[str, Any], workdir: Path, timeout: float):
        self.cfg = cfg
        self.workdir = workdir
        self.timeout = timeout

    @property
    def label(self) -> str:
        kind = {"subscription": "订阅", "api": "API", "mock": "模拟"}.get(self.access, self.access)
        return f"{kind} · {self.product}"

    def check(self) -> tuple[bool, str]:
        return True, ""

    def generate(self, system: str, prompt: str, mode: str = "line") -> Gen:
        raise NotImplementedError


# ====================================================================== 订阅接入：命令行
class CliDriver(Driver):
    access = "subscription"
    default_command = ""

    def __init__(self, cfg, workdir, timeout):
        super().__init__(cfg, workdir, timeout)
        self.command = cfg.get("command") or self.default_command

    def resolve(self) -> str | None:
        if os.path.isabs(self.command) and os.path.exists(self.command):
            return self.command
        return shutil.which(self.command)

    def check(self) -> tuple[bool, str]:
        exe = self.resolve()
        if not exe:
            return False, f"找不到命令 {self.command}：这台机器没装，或者要在配置里写完整路径（command:）"
        return True, exe

    def run(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        exe = self.resolve()
        if not exe:
            raise FileNotFoundError(self.command)
        self.workdir.mkdir(parents=True, exist_ok=True)
        kw: dict[str, Any] = {}
        if IS_WIN:
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.run([exe, *args], input=stdin_text.encode("utf-8"), cwd=str(self.workdir),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.timeout, **kw)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


class ClaudeCli(CliDriver):
    product = "Claude Code"
    default_command = "claude"
    # --tools ""：不给任何工具；--no-chrome：不连浏览器扩展（否则会带上二十个浏览器工具，每次多一万多 token）
    # --no-session-persistence：不存会话；--strict-mcp-config：不加载你平时配的 MCP。人设走 --system-prompt-file。
    default_args = ["-p", "--output-format", "json", "--tools", "", "--no-chrome", "--no-session-persistence",
                    "--strict-mcp-config", "--disable-slash-commands", "--permission-prompts", "none"]

    def generate(self, system, prompt, mode="line"):
        args = list(self.cfg.get("args") or self.default_args) + list(self.cfg.get("extra_args") or [])
        if self.cfg.get("model"):
            args += ["--model", str(self.cfg["model"])]
        if self.cfg.get("effort"):
            args += ["--effort", str(self.cfg["effort"])]
        self.workdir.mkdir(parents=True, exist_ok=True)
        fd, sp = tempfile.mkstemp(prefix="persona-", suffix=".txt", dir=str(self.workdir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(system)
            args += ["--system-prompt-file", sp]
            t0 = time.time()
            code, out, err = self.run(args, prompt)
        except FileNotFoundError:
            return Gen(False, error=f"找不到命令 {self.command}", kind="missing")
        except subprocess.TimeoutExpired:
            return Gen(False, error="Claude Code 超时", kind="timeout")
        finally:
            try:
                os.remove(sp)
            except OSError:
                pass
        obj = None
        for line in reversed(out.strip().splitlines()):
            try:
                cand = json.loads(line)
            except ValueError:
                continue
            if isinstance(cand, dict) and cand.get("type") == "result":
                obj = cand
                break
        if obj is None:
            msg = short(err or out or f"退出码 {code}")
            return Gen(False, error=msg, kind=classify(msg))
        text = str(obj.get("result") or "")
        if obj.get("is_error") or code != 0:
            msg = short(text or obj.get("subtype") or err or f"退出码 {code}")
            return Gen(False, error=msg, kind=classify(msg + " " + err))
        usage = obj.get("usage") or {}
        meta = {"seconds": round(time.time() - t0, 1),
                "input_tokens": sum(int(usage.get(k) or 0) for k in
                                    ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
                "output_tokens": int(usage.get("output_tokens") or 0)}
        return Gen(True, text=text, meta=meta)


class CodexCli(CliDriver):
    product = "Codex"
    default_command = "codex"
    # 只读沙箱 + 关掉 shell / 浏览器 / 电脑操作 / 应用 / 插件 / 搜索；--ephemeral 不存会话；
    # --ignore-user-config 不读你的 config.toml（不加载 MCP），登录信息照常用。
    # 这些 feature 名称跟 Codex 版本走，升级后报 Unknown feature flag 就在配置里用 args 覆盖。
    default_args = ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
                    "--sandbox", "read-only",
                    "--disable", "shell_tool", "--disable", "unified_exec", "--disable", "browser_use",
                    "--disable", "computer_use", "--disable", "in_app_browser", "--disable", "apps",
                    "--disable", "plugins", "-c", "web_search=disabled"]

    def generate(self, system, prompt, mode="line"):
        args = list(self.cfg.get("args") or self.default_args) + list(self.cfg.get("extra_args") or [])
        if self.cfg.get("model"):
            args += ["--model", str(self.cfg["model"])]
        if self.cfg.get("reasoning_effort"):
            args += ["-c", f"model_reasoning_effort={self.cfg['reasoning_effort']}"]
        args.append("-")   # 从标准输入读提示词
        full = f"<角色设定>\n{system}\n</角色设定>\n\n{prompt}"
        t0 = time.time()
        try:
            code, out, err = self.run(args, full)
        except FileNotFoundError:
            return Gen(False, error=f"找不到命令 {self.command}", kind="missing")
        except subprocess.TimeoutExpired:
            return Gen(False, error="Codex 超时", kind="timeout")
        text, last_err, used_tools = "", "", False
        tokens = {"input_tokens": 0, "output_tokens": 0}
        for line in out.splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            typ = o.get("type", "")
            item = o.get("item") or {}
            it = item.get("type") or item.get("item_type") or ""
            if typ == "item.completed" and it in ("agent_message", "assistant_message"):
                text = item.get("text", "") or text
            elif typ in ("item.started", "item.completed") and it in ("command_execution", "file_change", "mcp_tool_call",
                                                                       "web_search"):
                used_tools = True
            elif typ == "turn.completed":
                u = o.get("usage") or {}
                for k in tokens:
                    tokens[k] += int(u.get(k) or 0)
            elif typ in ("turn.failed", "error"):
                e = o.get("error") or {}
                last_err = (e.get("message") if isinstance(e, dict) else str(e)) or o.get("message") or line
        if code != 0 or not text:
            msg = short(last_err or err or f"退出码 {code}")
            return Gen(False, error=msg, kind=classify(msg + " " + err))
        meta = {"seconds": round(time.time() - t0, 1), **tokens}
        if used_tools:
            meta["used_tools"] = True
        return Gen(True, text=text, meta=meta)


# ====================================================================== API 接入
class ApiDriver(Driver):
    access = "api"

    def __init__(self, cfg, workdir, timeout):
        super().__init__(cfg, workdir, timeout)
        key_env = cfg.get("api_key_env", "")
        self.key_env = key_env
        self.api_key = os.environ.get(key_env, "") if key_env else ""
        self.model = cfg.get("model", "")
        self.max_tokens = int(cfg.get("max_tokens", 400))
        self.temperature = cfg.get("temperature", 0.9)

    def _http_error(self, r: httpx.Response) -> Gen:
        body = short(r.text, 300)
        kind = "auth" if r.status_code in (401, 403) else "limit" if r.status_code in (402, 429) else "other"
        return Gen(False, error=f"HTTP {r.status_code}：{body}", kind=kind)


class OpenAIApi(ApiDriver):
    def __init__(self, cfg, workdir, timeout):
        super().__init__(cfg, workdir, timeout)
        self.base = str(cfg.get("base_url", "https://api.deepseek.com")).rstrip("/")
        host = self.base.split("//")[-1].split("/")[0]
        self.product = cfg.get("product") or {"api.deepseek.com": "DeepSeek", "api.moonshot.cn": "Kimi",
                                              "api.moonshot.ai": "Kimi", "api.x.ai": "Grok",
                                              "openrouter.ai": "OpenRouter"}.get(host, host)

    def local(self) -> bool:
        return any(h in self.base for h in ("127.0.0.1", "localhost", "192.168.", "10.", "172.16."))

    def check(self):
        if not self.api_key and not self.local():
            return False, f"缺少 API key：设置环境变量 {self.key_env or '(配置里没写 api_key_env)'}"
        if not self.model:
            return False, "配置里没写 model"
        return True, f"{self.base} · {self.model}"

    def generate(self, system, prompt, mode="line"):
        body: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens,
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        body.update(self.cfg.get("extra_body") or {})
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        t0 = time.time()
        try:
            r = httpx.post(f"{self.base}/chat/completions", json=body, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException:
            return Gen(False, error="接口超时", kind="timeout")
        except httpx.HTTPError as exc:
            return Gen(False, error=f"连不上 {self.base}：{type(exc).__name__}", kind="other")
        if r.status_code >= 400:
            return self._http_error(r)
        try:
            data = r.json()
            text = data["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError):
            return Gen(False, error=f"返回格式看不懂：{short(r.text)}", kind="other")
        u = data.get("usage") or {}
        return Gen(True, text=text, meta={"seconds": round(time.time() - t0, 1),
                                         "input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")})


class AnthropicApi(ApiDriver):
    product = "Claude API"

    def __init__(self, cfg, workdir, timeout):
        cfg = {"api_key_env": "ANTHROPIC_API_KEY", **cfg}
        super().__init__(cfg, workdir, timeout)
        self.base = str(cfg.get("base_url", "https://api.anthropic.com")).rstrip("/")

    def check(self):
        if not self.api_key:
            return False, f"缺少 API key：设置环境变量 {self.key_env}"
        if not self.model:
            return False, "配置里没写 model"
        return True, self.model

    def generate(self, system, prompt, mode="line"):
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        if self.temperature is not None:
            body["temperature"] = min(float(self.temperature), 1.0)
        t0 = time.time()
        try:
            r = httpx.post(f"{self.base}/v1/messages", json=body, timeout=self.timeout,
                           headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        except httpx.TimeoutException:
            return Gen(False, error="接口超时", kind="timeout")
        except httpx.HTTPError as exc:
            return Gen(False, error=f"连不上 {self.base}：{type(exc).__name__}", kind="other")
        if r.status_code >= 400:
            return self._http_error(r)
        try:
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        except ValueError:
            return Gen(False, error=f"返回格式看不懂：{short(r.text)}", kind="other")
        u = data.get("usage") or {}
        return Gen(True, text=text, meta={"seconds": round(time.time() - t0, 1),
                                         "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")})


# ====================================================================== 模拟住户
FEELINGS = ["有点意思，回头再看一遍", "看饿了", "比我想的短", "这个我不太信，先存着", "评论区比正片好看", "想去现场看看",
            "原来是这么回事", "做得挺用心", "标题有点夸张", "看完想睡觉了", "收藏了", "下次叫上大家一起看"]
CHATS = ["刚刚那个我也看到了", "有人吃夜宵吗", "这个我查了一下，没查到出处，先别当真", "厨房的灯谁没关", "明天谁早起",
         "我在书房，有事喊我", "哈哈哈哈", "同意", "这个可以聊聊", "我先去睡了", "刚才那条挺好玩的", "嗯"]


class Mock(Driver):
    access = "mock"
    product = "模拟"

    @property
    def label(self) -> str:
        real = self.cfg.get("as")
        return f"模拟（正式：{real}）" if real else "模拟（不调用模型）"

    def generate(self, system, prompt, mode="line"):
        time.sleep(random.uniform(0.3, 1.5) * float(self.cfg.get("delay", 1)))
        if self.cfg.get("fail"):
            return Gen(False, error="模拟失败", kind=self.cfg.get("fail"))
        if mode == "json":
            say = random.choice(CHATS) if random.random() < 0.35 else ""
            mem = random.choice(["今天看了不少东西", "厨房的酱油快用完了", "书架上那本还没看完"]) if random.random() < 0.2 else ""
            note = random.choice(["今天院子里挺安静的，你忙完来看看", "冰箱快空了，记得补点"]) if "留言" in prompt and random.random() < 0.3 else ""
            return Gen(True, text=json.dumps({"感想": random.choice(FEELINGS), "群聊": say, "记住": mem, "留言": note}, ensure_ascii=False),
                       meta={"seconds": 0.5, "input_tokens": len(prompt) // 2, "output_tokens": 40})
        if random.random() < 0.15:
            return Gen(True, text="[不说话]")
        return Gen(True, text=random.choice(CHATS), meta={"seconds": 0.5, "input_tokens": len(prompt) // 2, "output_tokens": 20})


DRIVERS: dict[str, type[Driver]] = {
    "claude_cli": ClaudeCli, "codex_cli": CodexCli,
    "openai_api": OpenAIApi, "anthropic_api": AnthropicApi,
    "mock": Mock,
}


def make_driver(cfg: dict[str, Any], workdir: Path, timeout: float) -> Driver:
    typ = (cfg or {}).get("type", "mock")
    cls = DRIVERS.get(typ)
    if cls is None:
        raise ValueError(f"不认识的接入方式 {typ!r}，可选：{', '.join(DRIVERS)}")
    return cls(cfg or {}, workdir, timeout)
