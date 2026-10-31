# -*- coding: utf-8 -*-
# 脱敏示例：真实地址、令牌、称呼已替换为占位符，请按 config.py.example 配置
"""
AI记忆同步 —— 本地 QQ 版 ←→ 服务器网页版

用法：
    python sync_memory.py status    看两边差多少
    python sync_memory.py push      本地记忆 → 服务器
    python sync_memory.py pull      服务器记忆 → 本地
    python sync_memory.py merge     把本地对话记录补推给服务器
    python sync_memory.py all       先 merge 再 push（日常用这个）
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("SYNC_HOST", "http://YOUR_SERVER")
TOKEN = os.environ.get("SYNC_TOKEN", "")
SHARED = os.path.join(BASE, "shared_memory.md")
HISTORY = os.path.join(BASE, "chat_history.jsonl")

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    try:
        return json.loads(op.open(req, timeout=timeout).read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "code": e.code, "body": e.read().decode()[:200]}
    except Exception as e:
        return {"ok": False, "err": f"{type(e).__name__}: {e}"}


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:10]


def local_memory():
    try:
        return open(SHARED, encoding="utf-8").read()
    except Exception:
        return ""


def local_history():
    rows = []
    if not os.path.exists(HISTORY):
        return rows
    with open(HISTORY, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


# ---------------------------------------------------------------- 命令

def cmd_status():
    lm = local_memory()
    r = api(f"/api/memory?k={TOKEN}")
    if not r.get("ok"):
        print("❌ 取不到服务器记忆:", r)
        return
    sm = r.get("content", "")
    print("本地记忆 : %d 字 · %s" % (len(lm), md5(lm)))
    print("服务器   : %d 字 · %s" % (len(sm), md5(sm)))
    print("状态     :", "一致 ✅" if md5(lm) == md5(sm) else "不一致 ⚠️")

    h = local_history()
    rh = api(f"/api/history?k={TOKEN}&limit=10000")
    sh = rh.get("items", []) if rh.get("ok") else []
    print("\n本地对话 : %d 条" % len(h))
    print("服务器   : %d 条" % len(sh))


def cmd_push():
    lm = local_memory()
    if not lm.strip():
        print("❌ 本地记忆是空的，不推")
        return
    r = api("/api/memory", {"token": TOKEN, "content": lm})
    print("推送到服务器:", r)


def cmd_pull():
    r = api(f"/api/memory?k={TOKEN}")
    if not r.get("ok"):
        print("❌ 取不到:", r)
        return
    content = r.get("content", "")
    if not content.strip():
        print("❌ 服务器记忆是空的，不覆盖本地")
        return
    if os.path.exists(SHARED):
        os.replace(SHARED, SHARED + ".bak")
    with open(SHARED, "w", encoding="utf-8") as f:
        f.write(content)
    print("已拉到本地，%d 字（旧的存成了 .bak）" % len(content))


def cmd_merge():
    rows = local_history()
    if not rows:
        print("本地没有对话记录")
        return
    items = []
    for r in rows:
        items.append({"role": r.get("role"), "content": r.get("content"),
                      "ts": r.get("ts"), "src": "qq"})
    out = api("/api/history/append", {"token": TOKEN, "items": items}, timeout=60)
    print("推送对话:", out)


def cmd_all():
    cmd_merge()
    cmd_push()
    print()
    cmd_status()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"status": cmd_status, "push": cmd_push, "pull": cmd_pull,
     "merge": cmd_merge, "all": cmd_all}.get(cmd, cmd_status)()
