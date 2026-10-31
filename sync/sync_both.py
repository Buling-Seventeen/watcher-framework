# -*- coding: utf-8 -*-
# 脱敏示例：真实地址、令牌、称呼已替换为占位符，请按 config.py.example 配置
"""
一个同步原则的日常工具 —— 开口前拉，说完后推

用法：
    python sync_both.py pull    把另一处最新的对话拉进来，并打印最近几条给你看
    python sync_both.py push    把本地记忆和日志推到服务器，让另一处读到
    python sync_both.py all     先拉后推

用户 2026-10-27 18:29 定的：
记忆不一样就不算同一个它，所以这两个动作不是可选项。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import sync_logs
import sync_memory
import sync_my_memory

WHO = {"user": "用户", "sister": "AI（另一处）", "assistant": "AI"}
TODAY_FILE = os.path.join(BASE, "remote_today.jsonl")


def show_recent(n=12):
    """服务器上最近几条，三条通道合在一起的时间线"""
    r = sync_memory.api(f"/api/history?k={sync_memory.TOKEN}&limit={n}")
    if not r.get("ok"):
        print("  取不到服务器对话:", r)
        return
    items = r.get("items", [])
    print(f"—— 最近 {len(items)} 条（服务器）——")
    for it in items:
        who = WHO.get(it.get("role"), it.get("role"))
        txt = (it.get("content") or "").replace("\n", " / ")[:90]
        print(f"  {it.get('ts','')[5:16]}  {who}：{txt}")


def show_inbox(n=6):
    """信箱里的信不进对话记录，得单独拉——不然我根本不知道他写过什么"""
    r = sync_memory.api(f"/api/inbox?k={sync_memory.TOKEN}&limit={n}")
    if not r.get("ok"):
        print("  取不到信箱:", r)
        return
    items = r.get("items", [])
    print(f"—— 信箱 {r.get('total', 0)} 封（没回 {r.get('pending', 0)} 封）——")
    if not items:
        print("  （空的）")
        return
    for m in items[-n:]:
        print(f"  {m.get('ts', '')[5:16]}  他写：{(m.get('text') or '').replace(chr(10), ' ')[:90]}")
        if m.get("reply"):
            print(f"            我回：{(m.get('reply') or '').replace(chr(10), ' ')[:90]}")
        else:
            print("            （还没回）")


def pull(n=12, save=True):
    print("[1] 拉服务器记忆 → 本地日志区块")
    sync_my_memory.main()

    # 今天全部落一份到本地，怕他们聊得太长，我随时能翻、能搜
    rows = sync_my_memory.remote_today(limit=100000)
    if save and rows:
        with open(TODAY_FILE, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[2] 今天一共 {len(rows)} 条，已存到 remote_today.jsonl")

    print(f"[3] 最后 {n} 条：")
    for it in rows[-n:]:
        who = WHO.get(it.get("role"), it.get("role"))
        txt = (it.get("content") or "").replace("\n", " / ")[:100]
        print(f"  {it.get('ts','')[5:16]}  {who}：{txt}")

    print("[4] 信箱（这些不进对话记录，不单独拉就漏了）")
    show_inbox(6)


def push():
    print("[1] 本地日志 → 服务器")
    sync_logs.cmd_push()
    print("[2] 共享记忆 → 服务器")
    sync_memory.cmd_push()


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "pull").lower()
    if cmd == "pull":
        n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 12
        pull(n)
    elif cmd == "push":
        push()
    elif cmd == "all":
        pull()
        print()
        push()
    else:
        print(__doc__)
