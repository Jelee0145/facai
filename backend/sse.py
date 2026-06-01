"""Server-Sent Events 实时进度推送"""
import asyncio
import json
import logging
import os

logger = logging.getLogger("ecommerce-gen.sse")

SSE_IDLE_TIMEOUT = int(os.getenv("SSE_IDLE_TIMEOUT_SECONDS", "300"))
_TERMINAL_STATUSES = frozenset({"completed", "failed", "error"})

# task_id -> list of asyncio.Queue
_subscribers: dict[str, list[asyncio.Queue[dict]]] = {}
_lock = asyncio.Lock()


async def subscribe(task_id: str) -> asyncio.Queue[dict]:
    """为 task_id 创建消息队列，返回给 /stream 端点消费"""
    q: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)
    async with _lock:
        _subscribers.setdefault(task_id, []).append(q)
    logger.debug(f"[SSE] Subscribed to {task_id}")
    return q


def push_event(task_id: str, data: dict):
    """向所有订阅者推送事件（同步函数，用于同一 event loop 内调用）"""
    subs = _subscribers.get(task_id)
    if not subs:
        return
    # 复制列表，避免迭代期间列表被修改
    queues = list(subs)
    is_terminal = data.get("status") in _TERMINAL_STATUSES
    for q in queues:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            if is_terminal:
                # 终态事件：丢弃最旧的非终态事件，腾出空间
                try:
                    _ = q.get_nowait()
                    q.put_nowait(data)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    logger.warning(f"[SSE] Cannot deliver terminal event for {task_id}: queue stuck")
            else:
                logger.debug(f"[SSE] Queue full for {task_id}, dropping non-terminal event")


async def unsubscribe(task_id: str, q: asyncio.Queue[dict]):
    """客户端断开时取消订阅，清理空列表"""
    async with _lock:
        subs = _subscribers.get(task_id)
        if subs and q in subs:
            subs.remove(q)
        if subs is not None and len(subs) == 0:
            _subscribers.pop(task_id, None)
    logger.debug(f"[SSE] Unsubscribed from {task_id}")


async def sse_stream(task_id: str, timeout: float = SSE_IDLE_TIMEOUT, initial_event: dict | None = None):
    """异步生成器：生成 SSE 数据帧。

    空闲时发送 SSE comment 保活，不把连接空闲误判为任务失败；任务终态由生成流程
    显式推送 completed/failed/error。
    """
    q = await subscribe(task_id)
    try:
        if initial_event:
            yield f"data: {json.dumps(initial_event, ensure_ascii=False)}\n\n"
            if initial_event.get("status") in ("completed", "failed", "error", "timeout"):
                return

        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=timeout)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            if data.get("status") in ("completed", "failed", "error", "timeout"):
                return
    finally:
        await unsubscribe(task_id, q)


def cleanup_task_subscribers(task_id: str):
    """Force-remove all subscribers for a task (used on task completion cleanup)."""
    _subscribers.pop(task_id, None)
