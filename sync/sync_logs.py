# -*- coding: utf-8 -*-
# 脱敏示例：真实地址、令牌、称呼已替换为占位符，请按 config.py.example 配置
"""
记忆日志同步 —— 电脑端 memory/*.md → 服务器网页版

用法：
    python sync_logs.py status    看本地多少篇、服务器多少篇
    python sync_logs.py push      增量推（内容没变的不推）
    python sync_logs.py all       全量重推
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("SYNC_HOST", "http://YOUR_SERVER")
TOKEN = os.environ.get("SYNC_TOKEN", "")
MEM_DIR = r"D:/系统默认/文档/.workbuddy/memory"
BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, ".logs_synced.json")

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path, payload=None, timeout=60):
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
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def local_files():
    out = {}
    if not os.path.isdir(MEM_DIR):
        return out
    for name in sorted(os.listdir(MEM_DIR)):
        if not name.endswith(".md"):
            continue
        p = os.path.join(MEM_DIR, name)
        try:
            out[name] = open(p, encoding="utf-8").read()
        except Exception:
            pass
    return out


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print("⚠️ 状态没存上:", e)


def cmd_status():
    loc = local_files()
    r = api(f"/api/logs?k={TOKEN}")
    if not r.get("ok"):
        print("❌ 取不到服务器日志目录:", r)
        return
    remote = {i["name"]: i for i in r.get("items", [])}
    st = load_state()
    changed = [n for n, c in loc.items() if st.get(n) != md5(c)]
    print("本地  : %d 篇 · %d 字" % (len(loc), sum(len(c) for c in loc.values())))
    print("服务器: %d 篇" % len(remote))
    print("待推  : %d 篇" % len(changed))
    miss = [n for n in loc if n not in remote]
    if miss:
        print("服务器还没有:", ", ".join(miss[:12]))


def cmd_push(force=False):
    loc = local_files()
    if not loc:
        print("❌ 本地没有日志")
        return
    st = load_state()
    todo = {n: c for n, c in loc.items() if force or st.get(n) != md5(c)}
    if not todo:
        print("✅ 都是最新的，不用推（%d 篇）" % len(loc))
        return
    r = api("/api/logs", {"token": TOKEN, "files": todo}, timeout=120)
    if not r.get("ok"):
        print("❌ 推送失败:", r)
        return
    for n in r.get("saved", []):
        st[n] = md5(loc[n])
    save_state(st)
    print("推上去 %d 篇 · 内容没变跳过 %d 篇 · 服务器共 %d 篇"
          % (len(r.get("saved", [])), len(r.get("skipped", [])), r.get("total", 0)))
    if r.get("saved"):
        print("  本次:", ", ".join(r["saved"][-8:]))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "push"
    if cmd == "status":
        cmd_status()
    elif cmd == "all":
        cmd_push(force=True)
    else:
        cmd_push()
