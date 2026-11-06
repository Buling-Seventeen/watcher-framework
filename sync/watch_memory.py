# -*- coding: utf-8 -*-
"""
记忆守望者 —— 盯着本地记忆文件，一改就推给服务器

电脑上的布铃改完 shared_memory.md / our_story.md，
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
import threading
import time
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
# 子进程输出统一用 UTF-8，不然中文按 GBK 出来会成乱码
_SUBPENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

# 配置：优先读同目录的 config.py，没有就读环境变量。
# 仓库里只放 config.py.example，真的 config.py 不进仓库。
try:
    import config as _cfg
except Exception:
    _cfg = None


def _conf(name, env, default=""):
    v = getattr(_cfg, name, "") if _cfg else ""
    return v or os.environ.get(env, "") or default


HOST = _conf("HOST", "SYNC_HOST")
TOKEN = _conf("TOKEN", "SYNC_TOKEN")

SHARED = os.path.join(BASE, "shared_memory.md")
STORY = os.path.join(BASE, "our_story.md")
MEM_DIR = _conf("MEM_DIR", "MEM_DIR", os.path.join(BASE, "memory", "daily"))

LOG_FILE = os.path.join(BASE, "watch.log")

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LOCK_FILE = os.path.join(BASE, "watch.pid")
OFF_FILE = os.path.join(BASE, "watch_off.json")
_log_day = [""]


def off(name):
    """临时关掉某一项：watch_off.json 里写 ["video","bili"] 就不跑它"""
    try:
        with io.open(OFF_FILE, encoding="utf-8") as f:
            return name in json.load(f)
    except Exception:
        return False


def already_running():
    """已经有守望者在跑吗（防止点两次 bat 双开）"""
    try:
        with io.open(LOCK_FILE, encoding="utf-8") as f:
            pid = int((f.read() or "0").strip())
    except Exception:
        return None
    if pid <= 0 or pid == os.getpid():
        return None
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                             capture_output=True, text=True,
                             encoding="gbk", errors="replace", timeout=8,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        if str(pid) in (out or ""):
            return pid
    except Exception:
        pass
    return None


def take_lock():
    pid = already_running()
    if pid:
        return pid
    try:
        with io.open(LOCK_FILE, "w", encoding="utf-8", newline="\n") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass
    return None


def rotate_log():
    """每天一份日志：watch.log 是今天的，昨天的改名成 watch-日期.log"""
    today = datetime.now().strftime("%Y-%m-%d")
    if _log_day[0] == today:
        return
    old = _log_day[0]
    if old and os.path.exists(LOG_FILE):
        try:
            os.replace(LOG_FILE, os.path.join(BASE, "watch-%s.log" % old))
        except Exception:
            pass
    _log_day[0] = today


STATE_FILE = os.path.join(BASE, "watch_state.json")
_workers = {}


def state_load():
    try:
        with io.open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def state_set(key, **kw):
    """记下每件事上次跑的时间。重启之后从文件读，不会重复跑"""
    d = state_load()
    rec = dict(d.get(key) or {})

    # 连续失败计数：连着三次失败就吼一声，别闷着
    if kw.get("ok") is False:
        rec["fails"] = int(rec.get("fails") or 0) + 1
    elif kw.get("ok") is True:
        rec["fails"] = 0
    rec.update(kw)

    if rec.get("fails") == 3:
        log(f"!! {key} 连着失败 3 次：{str(kw.get('note',''))[:80]}")
    rec["at"] = time.time()
    rec["at_h"] = datetime.now().strftime("%m-%d %H:%M:%S")
    d[key] = rec
    try:
        with io.open(STATE_FILE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def state_age(key):
    """上次跑完到现在多少秒；没跑过返回一个很大的数"""
    rec = state_load().get(key) or {}
    at = rec.get("at")
    if not at:
        return 1e9
    age = time.time() - at
    # 系统时间被调过：负数或离谱的大数，当刚跑过，别重复跑
    if age < 0 or age > 7 * 86400:
        return 0
    return age


def busy(name):
    t = _workers.get(name)
    return bool(t and t.is_alive())


def spawn(name, fn, *a, **kw):
    """耗时活儿丢线程里跑，不许同一件起两个"""
    if busy(name):
        return False
    t = threading.Thread(target=fn, args=a, kwargs=kw, daemon=True, name=name)
    _workers[name] = t
    t.start()
    return True


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
    if off("pc"):
        return
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

# _video_inbox.py 要 paramiko，系统 python 里可能没有。
# 装了依赖的环境写在 config.py 的 PY_EXE 里，没有就用当前这个。
_VENV_PY = _conf("PY_EXE", "PY_EXE")


def video_py():
    """用装了依赖的那个 python。黑框靠 creationflags 关掉，不靠 pythonw——
    pythonw 会丢 stdout，capture_output 就成空的了"""
    return _VENV_PY if (_VENV_PY and os.path.exists(_VENV_PY)) else PY_EXE


def video_job():
    vb = os.path.join(BASE, "_video_inbox.py")
    try:
        r = subprocess.run([video_py(), vb], capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=900,
                           cwd=BASE, env=_SUBPENV,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip()
        if out and "待分析 0" not in out:
            log("✓ 视频处理 " + out[-200:].replace("\n", " ／ "))
            state_set("video", ok=True, note=out[-120:].replace("\n", " "))
        else:
            state_set("video", ok=True, note="无待处理")
    except Exception as e:
        log(f"✗ 视频处理异常 {type(e).__name__}: {e}")
        state_set("video", ok=False, note=("%s: %s" % (type(e).__name__, e))[:120])


def video_tick():
    """五分钟看一次；跑在后台线程，不堵主循环"""
    if off("video"):
        return
    if state_age("video") < 300 or busy("video"):
        return
    if not os.path.exists(os.path.join(BASE, "_video_inbox.py")):
        return
    state_set("video", ok=None, note="排队")
    spawn("video", video_job)


def archive_job():
    sc = os.path.join(BASE, "_archive_chat.py")
    try:
        r = subprocess.run([video_py(), sc], capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=300, cwd=BASE, env=_SUBPENV,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip()
        if out:
            log("✓ 对话归档 " + out.replace("\n", " "))
            state_set("archive", ok=True, note=out[:120])
    except Exception as e:
        log(f"✗ 归档失败 {type(e).__name__}: {e}")
        state_set("archive", ok=False, note=("%s: %s" % (type(e).__name__, e))[:120])


def archive_tick():
    """六小时一次；同样丢线程"""
    if off("archive"):
        return
    if state_age("archive") < 6 * 3600 or busy("archive"):
        return
    if not os.path.exists(os.path.join(BASE, "_archive_chat.py")):
        return
    state_set("archive", ok=None, note="排队")
    spawn("archive", archive_job)


_note_stamp = {}


def _sync_note(name, which):
    """一本笔记本跟服务器对一次。两边都会写，所以按行合并。"""
    p = os.path.join(BASE, name)
    if not os.path.exists(p):
        return
    try:
        st = str(os.path.getmtime(p))
    except Exception:
        return
    if _note_stamp.get(name) == st:
        return
    _note_stamp[name] = st

    try:
        local = open(p, encoding="utf-8").read()
    except Exception:
        return

    try:
        r = get_json(f"/api/self_note?k={TOKEN}&which={which}")
    except Exception:
        return
    remote = (r.get("content") or "") if r.get("ok") else ""
    if remote == local:
        return

    if not remote:
        post("/api/self_note", {"token": TOKEN, "content": local, "which": which})
        log(f"✓ {which} 那本首次上传")
        return

    rl = set(remote.splitlines())
    extra = [ln for ln in local.splitlines() if ln.strip() and ln not in rl]
    if extra:
        merged = remote.rstrip() + "\n\n" + "\n".join(extra) + "\n"
        post("/api/self_note", {"token": TOKEN, "content": merged, "which": which})
        log(f"✓ {which} 那本追加 %d 行" % len(extra))
    else:
        with open(p, "w", encoding="utf-8") as f:
            f.write(remote)
        log(f"✓ {which} 那本拉下来")


def self_note_tick():
    """两本各对一次：我写的这本、她写的那本"""
    _sync_note("self_note.md", "pc")
    _sync_note("self_note_web.md", "web")


def bili_job():
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

        # 光有标题和评论不算"看过"——再跑一遍看视频的工具，把画面和台词也捞出来
        detail = ""
        wv2 = os.path.join(BASE, "watch_video2.py")
        if os.path.exists(wv2):
            try:
                outdir = os.path.join(BASE, "bili_watch", v)
                t0 = time.time()
                r2 = subprocess.run(
                    [video_py(), wv2, "https://www.bilibili.com/video/%s" % v,
                     "--read", "--out", outdir],
                    capture_output=True, text=True, timeout=1500,
                    encoding="utf-8", errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                detail = (r2.stdout or "").strip()
                if detail:
                    log(f"✓ 看完了 {v}（{len(detail)} 字，{time.time()-t0:.0f}s）")
                else:
                    log(f"✗ 看 {v} 没输出：{(r2.stderr or '')[-120:]}")
            except Exception as e:
                log(f"✗ 看 {v} 失败 {type(e).__name__}: {e}")

        body = ("姐姐替你看过了（她那边服务器被 B 站封了 IP，我这边是家用网，能开）：\n"
                + txt[:1100])
        if detail:
            body += "\n\n—— 画面和台词 ——\n" + detail[:4200]
        try:
            rr = post("/api/bili_queue/reply", {"token": TOKEN, "id": it["id"], "text": body})
            log(f"✓ B 站 {v} 已回填 ok={rr.get('ok')}")
        except Exception as e:
            log(f"✗ 回填 {v} 失败 {type(e).__name__}")


def bili_tick():
    """每 30 秒看一次队列，有活就丢线程——他发链接时不用干等"""
    if off("bili"):
        return
    if state_age("bili") < 30 or busy("bili"):
        return
    try:
        r = get_json(f"/api/bili_queue?k={TOKEN}&pending=1")
    except Exception:
        return
    if not (r.get("items") or []):
        return
    state_set("bili", ok=None, note="排队")
    spawn("bili", bili_job)


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
        rotate_log()
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


BACKUP_DIR = os.path.join(BASE, "backup")


def backup(name, content):
    """每天给记忆文件留一份快照，保留七天。改坏了能翻回去"""
    try:
        d = os.path.join(BACKUP_DIR, name.replace(".md", ""))
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, datetime.now().strftime("%Y-%m-%d.md"))
        if not os.path.exists(p):
            with io.open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            _prune(d, 7)
    except Exception:
        pass


def _prune(d, keep):
    try:
        fs = sorted(f for f in os.listdir(d) if f.endswith(".md"))
        for f in fs[:-keep]:
            os.remove(os.path.join(d, f))
    except Exception:
        pass


def gitee_job():
    sc = os.path.join(BASE, "_backup_gitee.py")
    try:
        r = subprocess.run([video_py(), sc], capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=600, cwd=BASE, env=_SUBPENV,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip()
        ok = "已同步" in out
        state_set("gitee", ok=ok, note=(out[-90:] if out else "没输出").replace("\n", " "))
        if ok:
            log("✓ 记忆已备份到 Gitee")
        else:
            log("✗ Gitee 备份没成： " + out[-120:])
    except Exception as e:
        state_set("gitee", ok=False, note=type(e).__name__)


def gitee_tick():
    """十二小时往私有仓库推一次，跟本机 archive 两份互为备份"""
    if off("gitee") or state_age("gitee") < 12 * 3600 or busy("gitee"):
        return
    if not os.path.exists(os.path.join(BASE, "_backup_gitee.py")):
        return
    state_set("gitee", ok=None, note="排队")
    spawn("gitee", gitee_job)


def hb_job():
    prev = (state_load().get("hb") or {}).get("turns")
    try:
        r = post("/api/heartbeat", {"token": TOKEN,
                                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        turns = r.get("turns")
        state_set("hb", ok=bool(r.get("ok")),
                  note=("%s 条对话" % turns) if turns else "已报", turns=turns)
        # 她那边一有新的，立刻拉下来，别等我下次 pull
        if prev and turns and turns > prev:
            log("她那边多了 %d 条对话，先拉一下" % (turns - prev))
            if not busy("mymem"):
                spawn("mymem", my_mem_job)
    except Exception as e:
        state_set("hb", ok=False, note=type(e).__name__[:60])


def heartbeat_tick():
    """五分钟跟服务器报一次「我还在」，她那头就知道电脑关没关"""
    if off("hb") or state_age("hb") < 300 or busy("hb"):
        return
    state_set("hb", ok=None, note="报心跳")
    spawn("hb", hb_job)


def my_mem_job():
    try:
        sync_my_memory.main()
        _last_my_sync[0] = _minute()
        log("我的记忆已同步（她那边 → 我这边）")
    except Exception as e:
        log(f"我的记忆同步失败 {type(e).__name__}")


def logs_job():
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sync_logs.cmd_push()
        out = buf.getvalue().strip().replace("\n", " ／ ")
        log(f"✓ 日志同步 {out[:200]}")
    except Exception as e:
        LAST.pop("~mem~", None)     # 失败了下次还得试
        log(f"✗ 日志同步失败 {type(e).__name__}: {e}")


def main():
    pid = take_lock()
    if pid:
        log(f"已经有一个在跑了（PID {pid}），这个退出。要换新的先关掉旧的。")
        return

    if not HOST:
        log("没读到服务器地址。把 sync/config.py.example 复制成 sync/config.py，"
            "填上 HOST 和 TOKEN 再跑；或者设 SYNC_HOST / SYNC_TOKEN 环境变量。")
        return
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
                        backup("shared_memory.md", c)
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
                        backup("our_story.md", c2)
                        LAST[STORY] = d2
                    else:
                        log("✗ our_story 推送失败，下轮再试")

            # 把她那边的流水和对话，同步进我的记忆文件（丢线程，别堵主循环）
            if sync_my_memory and not busy("mymem") and _last_my_sync[0] != _minute():
                spawn("mymem", my_mem_job)

            # memory/ 里的日志改了 → 推给网页那只（同样丢线程）
            if sync_logs and not busy("logs"):
                st = mem_stamp()
                if st and st != LAST.get("~mem~"):
                    LAST["~mem~"] = st
                    spawn("logs", logs_job)

            # 服务器打不开的 B 站链接，我这边替它读
            bili_tick()

            # 电脑这边的对话，推给她读
            pc_tick()

            # 她那边有视频待分析就拉下来跑
            video_tick()

            # 服务器对话按天归档到本地
            archive_tick()

            # 自己那本笔记本，两边对一下
            self_note_tick()

            # 跟服务器报一声「我还在」
            heartbeat_tick()

            # 往私有仓库备份一份记忆（十二小时一次）
            gitee_tick()

        except Exception as e:
            log(f"出错 {type(e).__name__}: {e}")

        time.sleep(20)


if __name__ == "__main__":
    main()
