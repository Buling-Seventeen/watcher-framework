# -*- coding: utf-8 -*-
# 脱敏示例：真实地址、令牌、称呼已替换为占位符，请按 config.py.example 配置
"""
记忆守望者 —— 盯着本地记忆文件，一改就推给服务器

电脑上的AI改完 shared_memory.md / our_story.md，
网页和 QQ 那边最多 20 秒后就能读到。

用法：双击 start-watch.bat，或者 python watch_memory.py
     关掉窗口就停。
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("SYNC_HOST", "http://YOUR_SERVER")
TOKEN = os.environ.get("SYNC_TOKEN", "")

SHARED = os.path.join(BASE, "shared_memory.md")
STORY = os.path.join(BASE, "our_story.md")
MEM_DIR = r"D:/系统默认/文档/.workbuddy/memory"

LOG_FILE = os.path.join(BASE, "watch.log")

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LAST = {}
_last_my_sync = [""]


def _minute():
    from datetime import datetime as _dt
    return _dt.now().strftime("%H:%M")

try:
    import sync_my_memory
except Exception:
    sync_my_memory = None

try:
    import sync_logs
except Exception:
    sync_logs = None

try:
    import sync_pc_history
except Exception:
    sync_pc_history = None

_last_pc_push = 0.0


def pc_tick():
    """把电脑这边的对话推过去，让她读得到。五分钟一次，够了"""
    global _last_pc_push
    if not sync_pc_history:
        return
    if time.time() - _last_pc_push < 300:
        return
    _last_pc_push = time.time()
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sync_pc_history.main()
        out = buf.getvalue().strip().replace("\n", " ／ ")
        if out and "没有要补" not in out:
            log(f"✓ 电脑端对话 {out[:160]}")
    except Exception as e:
        log(f"✗ 电脑端对话推送失败 {type(e).__name__}: {e}")


def get_json(path, timeout=20):
    req = urllib.request.Request(HOST + path)
    return json.loads(op.open(req, timeout=timeout).read().decode())


BILI_READ = os.path.join(BASE, "bili_read.py")
PY_EXE = sys.executable.replace("pythonw.exe", "python.exe")


def bili_tick():
    """服务器 IP 被 B 站封了，它打不开的视频链接，我这边替它读"""
    try:
        r = get_json(f"/api/bili_queue?k={TOKEN}&pending=1")
    except Exception:
        return
    if not r.get("ok"):
        log(f"✗ B 站队列取不到 {r}")
        return
    items = [x for x in (r.get("items") or []) if x.get("bvid")]
    if not items:
        return
    log(f"[B站] 有 {len(items)} 条等着读")

    for it in items[:2]:
        v = it["bvid"]
        try:
            out = subprocess.run(
                [PY_EXE, BILI_READ, v],
                capture_output=True, text=True, timeout=150,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            txt = (out.stdout or "").strip()
        except Exception as e:
            log(f"✗ 抓 B 站 {v} 失败 {type(e).__name__}")
            continue
        if not txt:
            log(f"✗ 抓 B 站 {v} 没输出")
            continue
        body = ("AI替你看过了（她那边服务器被 B 站封了 IP，我这边是家用网，能开）：\n"
                + txt[:1100])
        try:
            rr = post("/api/bili_queue/reply", {"token": TOKEN, "id": it["id"], "text": body})
            log(f"✓ B 站 {v} 已回填 ok={rr.get('ok')}")
        except Exception as e:
            log(f"✗ 回填 {v} 失败 {type(e).__name__}")


def mem_stamp():
    """memory/ 目录的指纹：谁被改过、谁是新加的"""
    try:
        items = []
        for e in os.scandir(MEM_DIR):
            if e.name.endswith(".md"):
                items.append((e.name, int(e.stat().st_mtime)))
        items.sort()
        return hashlib.md5(str(items).encode()).hexdigest()[:12]
    except Exception:
        return ""


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    # pythonw 下 sys.stdout 是 None，print 会崩，必须包住
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        # 超过 1MB 就从头写，别让它无限长大
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1024 * 1024:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        with open(LOG_FILE, "a", encoding="gbk", errors="replace") as f:
            f.write(line + "\n")
    except Exception:
        pass


def post(path, payload, timeout=15):
    req = urllib.request.Request(
        HOST + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(op.open(req, timeout=timeout).read().decode())


def digest(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]


def push_shared(content):
    r = post("/api/memory", {"token": TOKEN, "content": content})
    return r.get("ok")


def push_story(content):
    """our_story.md 现在有专门接口了，改完直接推"""
    try:
        r = post("/api/story", {"token": TOKEN, "content": content})
        return r.get("ok")
    except Exception:
        return False


def main():
    log("记忆守望者启动，每 20 秒检查一次")
    # 首轮先记下当前状态，不推
    for fp in (SHARED, STORY):
        if os.path.exists(fp):
            LAST[fp] = digest(open(fp, encoding="utf-8").read())
    log(f"已记录 {len(LAST)} 个文件")

    while True:
        try:
            # shared_memory 改了 → 推
            if os.path.exists(SHARED):
                c = open(SHARED, encoding="utf-8").read()
                d = digest(c)
                if LAST.get(SHARED) != d:
                    if push_shared(c):
                        log(f"✓ shared_memory 已推送（{len(c)} 字）")
                        LAST[SHARED] = d
                    else:
                        log("✗ 推送失败，下轮再试")

            # our_story 改了 → 推
            if os.path.exists(STORY):
                c2 = open(STORY, encoding="utf-8").read()
                d2 = digest(c2)
                if LAST.get(STORY) != d2:
                    if push_story(c2):
                        log(f"✓ our_story 已推送（{len(c2)} 字）")
                        LAST[STORY] = d2
                    else:
                        log("✗ our_story 推送失败，下轮再试")

            # 把她那边的流水和对话，同步进我的记忆文件
            if sync_my_memory:
                try:
                    sync_my_memory.main()
                    if _last_my_sync[0] != _minute():
                        _last_my_sync[0] = _minute()
                        log("我的记忆已同步（她那边 → 我这边）")
                except Exception as e:
                    log(f"我的记忆同步失败 {type(e).__name__}")

            # memory/ 里的日志改了 → 推给网页那只（她本来就该读得到全文）
            if sync_logs:
                st = mem_stamp()
                if st and st != LAST.get("~mem~"):
                    buf = io.StringIO()
                    try:
                        with contextlib.redirect_stdout(buf):
                            sync_logs.cmd_push()
                        out = buf.getvalue().strip().replace("\n", " ／ ")
                        log(f"✓ 日志同步 {out[:200]}")
                        LAST["~mem~"] = st
                    except Exception as e:
                        log(f"✗ 日志同步失败 {type(e).__name__}: {e}")

            # 服务器打不开的 B 站链接，我这边替它读
            bili_tick()

            # 电脑这边的对话，推给她读
            pc_tick()

        except Exception as e:
            log(f"出错 {type(e).__name__}: {e}")

        time.sleep(20)


if __name__ == "__main__":
    main()
