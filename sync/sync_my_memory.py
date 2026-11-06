# -*- coding: utf-8 -*-
# 脱敏示例：真实地址、令牌、称呼已替换为占位符，请按 config.py.example 配置
"""
把她那边的记忆同步进我的记忆文件

跑一次，就把：
  - auto_memory.md（她的日常流水）
  - 今天的对话（**从服务器拉，网页/QQ 上的都在里面**）
写进日志目录下的 YYYY-MM-DD.md 里一个固定区块。

服务器拉不到才退回读本地 chat_history.jsonl。
每次覆盖那个区块，不会重复堆叠。
"""
import json
import os
# 配置：同目录的 config.py，或者环境变量
try:
    import config as _cfg
except Exception:
    _cfg = None


def _conf(name, env, default=""):
    v = getattr(_cfg, name, "") if _cfg else ""
    return v or os.environ.get(env, "") or default
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
MEM_DIR = _conf("MEM_DIR", "MEM_DIR",
                os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "memory", "daily"))
HOST = _conf("HOST", "SYNC_HOST", "http://YOUR_SERVER")
TOKEN = _conf("TOKEN", "SYNC_TOKEN")

AUTO = os.path.join(BASE, "auto_memory.md")
HIST = os.path.join(BASE, "chat_history.jsonl")

START = "<!-- AI那边同步过来的 START -->"
END = "<!-- AI那边同步过来的 END -->"

WHO = {"user": "用户", "sister": "AI（另一处）", "assistant": "AI"}


def read(p, default=""):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return default


def remote_today(limit=50):
    """服务器上的今天，三条通道合在一起的那条时间线"""
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        raw = op.open(f"{HOST}/api/history?k={TOKEN}&limit=3000", timeout=30).read()
        d = json.loads(raw.decode())
    except Exception:
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    rows = [r for r in d.get("items", []) if (r.get("ts") or "").startswith(today)]
    rows.sort(key=lambda r: (r.get("ts", ""),
                             0 if r.get("role") in ("user", "sister") else 1))
    return rows[-limit:]


def today_history(limit=50):
    """先问服务器要（网页上聊的也在里面），拿不到再退回读本地文件"""
    rows = remote_today(limit)
    if rows:
        return rows

    rows = []
    if not os.path.exists(HIST):
        return rows
    today = datetime.now().strftime("%Y-%m-%d")
    with open(HIST, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if (r.get("ts") or "").startswith(today):
                rows.append(r)
    rows.sort(key=lambda r: (r.get("ts", ""), 0 if r.get("role") == "user" else 1))
    return rows[-limit:]


def build_block():
    now = datetime.now().strftime("%H:%M")
    lines = [START, "", f"## 她那边同步过来的（{now} 更新）", ""]

    auto = read(AUTO).strip()
    if auto:
        lines.append("**她的自动流水记忆：**")
        lines.append("")
        for ln in auto.split("\n"):
            s = ln.strip()
            if s.startswith("- ") or s.startswith("## "):
                lines.append(s)
        lines.append("")

    rows = today_history()
    if rows:
        lines.append(f"**今天聊的（最近 {len(rows)} 条）：**")
        lines.append("")
        for r in rows:
            who = WHO.get(r.get("role"), "AI")
            txt = (r.get("content") or "").replace("\n", " / ")[:110]
            lines.append(f"- `{r.get('ts','')[11:16]}` {who}：{txt}")
        lines.append("")

    lines.append(END)
    return "\n".join(lines)


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    fp = os.path.join(MEM_DIR, today + ".md")
    os.makedirs(MEM_DIR, exist_ok=True)

    old = read(fp)
    block = build_block()

    if START in old and END in old:
        head = old[:old.index(START)]
        tail = old[old.index(END) + len(END):]
        new = head + block + tail
    else:
        new = old.rstrip() + "\n\n" + block + "\n"

    with open(fp, "w", encoding="utf-8") as f:
        f.write(new)
    try:
        print(f"已同步到 {fp}（{len(block)} 字）", flush=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
