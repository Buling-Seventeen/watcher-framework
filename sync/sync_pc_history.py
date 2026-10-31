# -*- coding: utf-8 -*-
# 脱敏示例：真实地址、令牌、称呼已替换为占位符，请按 config.py.example 配置
"""
把「电脑上这只AI」的会话，补推给服务器

网页/QQ 那边的AI读的是服务器上的 chat_history，
以前只有 QQ 那一路，电脑这边说的话她看不到。
这个脚本从 WorkBuddy 的会话 jsonl 里捞 user / assistant 的正文，
推到 /api/history/append，标 src=pc。

用法：
    python sync_pc_history.py            只推今天
    python sync_pc_history.py 2026-10-26 推指定某天（可多次）
    python sync_pc_history.py 2026-10-26 2026-10-27
"""
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("SYNC_HOST", "http://YOUR_SERVER")
TOKEN = os.environ.get("SYNC_TOKEN", "")
PROJ = r"D:/系统默认/文档/.workbuddy/projects"
STATE = os.path.join(BASE, ".pc_synced.json")

pat_sr = re.compile(r"<system-reminder.*?</system-reminder>", re.S)
pat_uq = re.compile(r"<user_query>(.*?)</user_query>", re.S)
pat_tag = re.compile(r"<[^>]{1,80}>")

SECRET_PAT = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")


def mask_secrets(s):
    """密钥不进对话记录：token 一旦同步上去就等于写进了公共日志"""
    return SECRET_PAT.sub("[密钥已屏蔽]", s)


op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, payload, timeout=60):
    req = urllib.request.Request(
        HOST + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(op.open(req, timeout=timeout).read().decode())


def load_state():
    try:
        return set(json.load(open(STATE, encoding="utf-8")))
    except Exception:
        return set()


def save_state(s):
    # 只留最近 4000 个，别让它无限长
    json.dump(sorted(s)[-4000:], open(STATE, "w", encoding="utf-8"))


def texts(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts, has_tool = [], False
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type") or ""
            if "tool_result" in t or "tool_use" in t or t == "tool_call":
                has_tool = True
            if t in ("text", "input_text", "output_text"):
                parts.append(c.get("text", ""))
        if has_tool and not parts:
            return ""
        return "\n".join(p for p in parts if p)
    return ""


def fmt_ts(ts):
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return ""
    return str(ts)[:19].replace("T", " ")


def sess_files(dayset):
    """找当天动过的所有会话文件——以前写死一个，换个会话就推不动了"""
    out = []
    for root, _, files in os.walk(PROJ):
        for f in files:
            if not f.endswith(".jsonl"):
                continue
            p = os.path.join(root, f)
            try:
                mt = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")
            except Exception:
                continue
            if mt in dayset:
                out.append(p)
    return sorted(out)


def main():
    days = sys.argv[1:] or [datetime.now().strftime("%Y-%m-%d")]
    dayset = set(days)
    done = load_state()
    items, seen = [], set()

    files = sess_files(dayset)
    if not files:
        print("这两天没有动过的会话文件")
        return

    for fp in files:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") != "message":
                    continue
                role = o.get("role")
                if role not in ("user", "assistant"):
                    continue
                raw = texts(o.get("content"))
                if not raw:
                    continue
                if role == "user":
                    m = pat_uq.findall(raw)
                    txt = "\n".join(m) if m else pat_sr.sub("", raw)
                    txt = txt.replace("<user_query>", "").replace("</user_query>", "")
                    txt = pat_tag.sub("", txt).strip()
                else:
                    txt = re.sub(r"<[^>]{1,80}>", "", raw).strip()
                if not txt:
                    continue
                ts = fmt_ts(o.get("timestamp"))
                if not ts or ts[:10] not in dayset:
                    continue
                key = hashlib.md5((role + ts + txt[:200]).encode("utf-8")).hexdigest()[:16]
                if key in done or key in seen:
                    continue
                seen.add(key)
                txt = mask_secrets(txt)
                items.append({"role": role, "content": txt[:1500], "ts": ts, "src": "pc", "_k": key})

    if not items:
        print("这几天没有要补的内容")
        return
    payload = [{k: v for k, v in it.items() if k != "_k"} for it in items]
    r = post("/api/history/append", {"token": TOKEN, "items": payload})
    print("推送 %d 条 →" % len(payload), r)
    if r.get("ok"):
        done |= seen
        save_state(done)


if __name__ == "__main__":
    main()
