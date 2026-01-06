# DingTalk 集成工程笔记

本文档记录 vibe-remote 添加 DingTalk (钉钉) 支持过程中的工程问题、失败案例和解决方案。

## 目录

- [背景](#背景)
- [架构挑战](#架构挑战)
- [失败案例](#失败案例)
- [解决方案](#解决方案)
- [经验总结](#经验总结)

## 背景

**目标**：为 vibe-remote 添加 DingTalk IM 平台支持，使其能与 Slack 和 Telegram 并列作为远程 AI 编程助手的接入点。

**已有实现**：
- Slack：使用 Socket Mode，每个消息独立处理
- Telegram：使用 Long Polling，每个消息独立处理

**挑战**：DingTalk 使用 Stream 模式，但 SDK 的回调机制与我们的异步架构存在不匹配。

## 架构挑战

### 1. SDK 回调机制差异

**DingTalk SDK 的限制**：

```python
class ChatbotHandler(ChatbotHandler):
    def process(self, callback_message: CallbackMessage):
        # 必须返回 (200, "OK") 作为 ACK
        return 200, "OK"
```

- SDK 期望 `process()` 方法**同步返回** ACK
- 但我们的消息处理是**异步**的（需要与 Claude SDK 通信）

### 2. Claude SDK 的异步特性

Claude Agent 的工作流程：

```python
async def handle_message(self, request):
    client = await get_or_create_claude_session()
    await client.query(...)  # 发送消息后立即返回

    # 创建后台任务接收响应
    asyncio.create_task(self._receive_messages(client, ...))
    # 函数返回，但 _receive_messages 需要持续运行
```

**问题**：
- `_receive_messages` 是一个**无限循环** (`async for message in client.receive_messages()`)
- 需要在事件循环中**持续运行**才能接收 Claude 的响应
- 如果事件循环被关闭，任务就被中断，无法接收消息

### 3. 事件循环生命周期冲突

**最初的实现**（失败）：

```python
def _run_async_handler(self, handler, *args):
    def run_in_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(handler(*args))  # 运行后立即关闭
        loop.close()

    thread = threading.Thread(target=run_in_loop)
    thread.start()
```

**问题**：
1. `handler(*args)` 执行完后立即返回
2. `_receive_messages` 任务还在等待消息
3. 事件循环被关闭，任务被取消
4. Claude 的响应无法到达

### 4. Qoder 与 Claude 的差异

| 特性 | Claude | Qoder |
|------|--------|-------|
| 通信方式 | SDK 异步流 | 子进程 stdout/stderr |
| 消息接收 | 需要持续监听的后台任务 | 随进程输出同步读取 |
| handle_message | 发送后立即返回 | `await process.wait()` 阻塞 |
| 对事件循环依赖 | 强（需要持续运行） | 弱（只需运行期间） |

**结果**：Qoder 在原始架构下能正常工作，Claude 不能。

## 失败案例

### 尝试 1：简单线程 + 新事件循环

**做法**：为每个消息创建新线程和新事件循环

**结果**：❌ 失败
- `handle_message` 返回后事件循环关闭
- `_receive_messages` 任务被中断
- Claude 响应无法到达

### 尝试 2：添加等待时间

**做法**：在 `handler` 完成后等待 pending tasks

```python
async def run_and_wait():
    await handler(*args)
    await asyncio.sleep(0.5)
    pending = asyncio.all_tasks(loop)
    await asyncio.gather(*pending)
```

**结果**：❌ 失败
- `_receive_messages` 是无限循环，永远不会完成
- 30 秒超时后被强制取消
- 连接中断

### 尝试 3：超时控制

**做法**：使用 `asyncio.wait_for(timeout=30)` 等待任务

**结果**：❌ 失败
- 超时后任务被取消
- 读取任务被中断：`Read task cancelled`
- Claude 连接断开

## 解决方案

### 最终方案：共享持久事件循环

**核心思想**：创建一个长期运行的专用事件循环，所有异步任务都在其中执行。

```python
class ChatbotMessageHandler(ChatbotHandler):
    def __init__(self, bot_instance):
        super().__init__()
        self.bot = bot_instance
        self._loop = None
        self._loop_thread = None

    def _get_or_create_loop(self):
        """获取或创建共享事件循环"""
        if self._loop is not None and self._loop.is_running():
            return self._loop

        # 在专用线程中创建长期运行的事件循环
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()  # 永不停止

        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()
        return self._loop

    async def process(self, callback_message: CallbackMessage):
        """处理消息 - 在共享循环中异步执行"""
        loop = self._get_or_create_loop()

        # 将异步任务提交到共享循环
        future = asyncio.run_coroutine_threadsafe(
            self._process_message(callback_message), loop
        )

        # 立即返回 ACK，不等待完成
        return 200, "OK"
```

**关键点**：
1. `loop.run_forever()` - 事件循环永不停止
2. `asyncio.run_coroutine_threadsafe()` - 从不同线程提交任务
3. 立即返回 ACK - 不阻塞 DingTalk SDK

## 其他问题与解决

### 问题 1：重复消息显示

**现象**：Assistant 消息和 Result 消息内容相同，显示两次

**原因**：Claude SDK 在流程结束时会发送 Result 事件，但某些情况下 Result 事件为空或包含相同文本

**解决**：在 Claude Agent 中过滤空的 Result 事件

```python
elif message_type == "result":
    result_text = getattr(message, "result", None)
    if not result_text:
        # 跳过空 result，避免重复显示
        self._last_assistant_text.pop(composite_key, None)
        continue
```

### 问题 2：Qoder 会话恢复失败

**现象**：使用 `-r` 参数恢复会话时，qodercli 报错 "unexpected end of JSON input"

**原因**：Qoder CLI 在处理包含非 ASCII 字符的路径时，路径 sanitization 不一致

**解决**：跳过非 ASCII 路径的会话恢复

```python
should_resume = resume_id and request.working_path.isascii()
if not should_resume and resume_id:
    logger.warning("Skipping session resume due to non-ASCII characters in path")
```

### 问题 3：Qoder 工具调用重复显示

**现象**：同一个工具调用被显示多次

**原因**：Qoder 的 stream-json 输出会重复发送相同的事件

**解决**：使用消息哈希去重

```python
text_hash = hashlib.md5(text.encode()).hexdigest()
if text_hash not in self._sent_message_hashes[session_id]:
    self._sent_message_hashes[session_id].add(text_hash)
    # 发送消息
```

## 经验总结

### 1. 理解 Agent 的异步特性

在设计 IM 集成时，必须充分理解 Agent 的异步特性：

| Agent 类型 | 特点 | 集成注意事项 |
|-----------|------|-------------|
| 进程型 (Qoder/Codex) | 同步等待进程结束 | 事件循环只需运行期间 |
| SDK 型 (Claude) | 后台任务持续运行 | 需要持久事件循环 |

### 2. 事件循环生命周期管理

- **短期任务**：创建临时事件循环即可
- **长期任务**：必须使用持久事件循环（`run_forever()`）
- **跨线程调用**：使用 `asyncio.run_coroutine_threadsafe()`

### 3. 子进程 vs SDK 的权衡

| 考量 | 子进程模式 | SDK 模式 |
|------|-----------|---------|
| 集成复杂度 | 需要进程通信解析 | 直接 API 调用 |
| 语言限制 | 无限制 | 限于 SDK 支持的语言 |
| 隔离性 | 进程隔离 | 同进程，崩溃可能影响主程序 |
| 流式输出 | 需要解析 stdout | 原生支持 |

### 4. 调试技巧

- 添加详细的日志记录事件循环生命周期
- 检查 pending tasks 的数量和状态
- 使用 `asyncio.all_tasks()` 监控任务状态
- 区分"无响应"和"响应慢"的问题

### 5. 平台差异

虽然都支持异步消息处理，但各平台的 SDK 设计理念不同：

| 平台 | SDK 设计 | 事件循环要求 |
|------|---------|-------------|
| Slack | Socket Mode，自带事件循环 | 需要配合 |
| Telegram | Long Polling，显式控制 | 灵活 |
| DingTalk | Stream 模式，回调式 | 需要适配 |

### 6. 测试策略

1. 先测试简单消息（如 "hello"）
2. 测试长时间运行的任务
3. 测试并发消息
4. 测试会话恢复
5. 测试错误处理

## 总结

DingTalk 集成的核心挑战在于**异步长期运行任务**与**回调式 SDK**的适配。通过使用共享持久事件循环，我们成功解决了这个问题，同时保持了与 Qoder 等 Agent 的兼容性。

**关键学习**：
- 理解 Agent 的异步模型是设计 IM 集成的前提
- 事件循环生命周期管理至关重要
- 进程型 Agent 和 SDK 型 Agent 有不同的集成需求
- 持久事件循环是支持 SDK 型 Agent 的通用解决方案
