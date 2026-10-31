# 同步层

让同一只 AI 出现在多个地方，读的是同一套记忆。

## 文件

| 文件 | 干什么 |
|---|---|
| `sync_memory.py` | 共享记忆 推/拉 |
| `sync_logs.py` | 日志 推/拉 |
| `sync_my_memory.py` | 把服务器上的对话写成当天的日志区块 |
| `sync_pc_history.py` | 把电脑端会话补推给服务器（带密钥过滤） |
| `sync_both.py` | 入口：`pull` / `push` / `all` |
| `watch_memory.py` | 盯着文件，改了就自动推 |
| `config.py.example` | 配置模板，复制成 `config.py` |

## 怎么用

```bash
# 1. 配置
cp config.py.example config.py
# 改里面的 HOST 和 TOKEN

# 2. 拉（开口之前）
python sync_both.py pull

# 3. 推（说完之后）
python sync_both.py push

# 4. 或者两个一起
python sync_both.py all
```

## 三条原则

1. **先拉再改** —— 改之前先拉一次，避免覆盖另一处的修改
2. **改完就推** —— 不要攒着，攒着就会忘
3. **冲突以更晚的时间戳为准**，但记一条冲突日志

## 一条安全经验（踩过的）

**对话记录同步之前，先把密钥过滤掉。**

`sync_pc_history.py` 里有一个 `mask_secrets()`：

```python
SECRET_PAT = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")

def mask_secrets(s):
    return SECRET_PAT.sub("[密钥已屏蔽]", s)
```

起因是：有一次把 GitHub token 直接发在对话里，同步之后它就进了服务器的 `chat_history.jsonl`。

**密钥一旦进了对话记录，就等于进了公共日志。** 所以过滤要放在同步之前，不是之后。
