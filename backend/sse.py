"""Server-Sent Events 实时进度推送"""
import asyncio
import json
from collections import defaultdict

# task_id -> list of asyncio.Queue
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


def subscribe(task_id: str) -> asyncio.Queue:
    """为 task_id 创建消息队列，返回给 /stream 端点消费"""
    q: asyncio.Queue = asyncio.Queue()
    _subscribers[task_id].append(q)
    return q


def push_event(task_id: str, data: dict):
    """向所有订阅者推送事件"""
    for q in _subscribers.get(task_id, []):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


def unsubscribe(task_id: str, q: asyncio.Queue):
    """客户端断开时取消订阅，清理空列表"""
    subs = _subscribers.get(task_id)
    if subs and q in subs:
        subs.remove(q)
    if not subs:
        _subscribers.pop(task_id, None)


async def sse_stream(task_id: str, timeout: float = 300):
    """异步生成器：生成 SSE 数据帧，超时或 completed/failed 后结束"""
    q = subscribe(task_id)
    try:
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=timeout)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'status': 'timeout', 'error': 'No progress for 5 minutes'}, ensure_ascii=False)}\n\n"
                return
            # send event
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            if data.get("status") in ("completed", "failed"):
                return
    finally:
        unsubscribe(task_id, q)
