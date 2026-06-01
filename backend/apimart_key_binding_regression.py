"""Regression tests for Apimart task/key ownership.

Run with:
    python backend/apimart_key_binding_regression.py
"""

import asyncio
import json

import main as m


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = json.dumps(self._body) if body is not None else ""

    def json(self):
        return self._body


class FakeKeyManager:
    def __init__(self):
        self.keys = [{"key_value": "key-a"}, {"key_value": "key-b"}]
        self.index = -1
        self.successes = []
        self.failures = []

    def get_active_key(self):
        self.index = (self.index + 1) % len(self.keys)
        return self.keys[self.index]

    def mark_success(self, key_value):
        self.successes.append(key_value)

    def mark_failure(self, key_value):
        self.failures.append(key_value)


async def fast_sleep(_seconds):
    return None


def install_fakes(task_owner):
    fake_keys = FakeKeyManager()
    calls = []

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            key = headers["Authorization"].replace("Bearer ", "")
            prompt = json["prompt"]
            task_id = f"task-{prompt}"
            task_owner[task_id] = key
            calls.append(("POST", task_id, key))
            return FakeResponse(200, {"data": [{"task_id": task_id}]})

        async def get(self, url, headers):
            key = headers["Authorization"].replace("Bearer ", "")
            task_id = url.rsplit("/", 1)[-1]
            calls.append(("GET", task_id, key))
            if task_owner[task_id] != key:
                return FakeResponse(403, {"error": {"message": "task belongs to another key"}})
            return FakeResponse(
                200,
                {
                    "data": {
                        "status": "completed",
                        "result": {"images": [{"url": [f"https://img.example/{task_id}.png"]}]},
                    }
                },
            )

    originals = {
        "key_manager": m.key_manager,
        "get_active_keys": m.get_active_keys,
        "AsyncClient": m.httpx.AsyncClient,
        "sleep": m.asyncio.sleep,
    }
    m.key_manager = fake_keys
    m.get_active_keys = lambda: fake_keys.keys
    m.httpx.AsyncClient = FakeAsyncClient
    m.asyncio.sleep = fast_sleep
    return originals, fake_keys, calls


def restore_fakes(originals):
    m.key_manager = originals["key_manager"]
    m.get_active_keys = originals["get_active_keys"]
    m.httpx.AsyncClient = originals["AsyncClient"]
    m.asyncio.sleep = originals["sleep"]


def test_single_generation_reuses_submit_key_for_polling():
    task_owner = {}
    originals, fake_keys, calls = install_fakes(task_owner)
    try:
        url = asyncio.run(m.apimart_generate("single"))
    finally:
        restore_fakes(originals)

    assert url == "https://img.example/task-single.png"
    assert calls == [
        ("POST", "task-single", "key-a"),
        ("GET", "task-single", "key-a"),
    ]
    assert fake_keys.failures == []


def test_batch_generation_reuses_each_task_submit_key_for_polling():
    task_owner = {}
    originals, fake_keys, calls = install_fakes(task_owner)
    try:
        urls = asyncio.run(
            m.apimart_batch_generate(
                [
                    {"prompt": "one", "size": "1:1", "resolution": "1k"},
                    {"prompt": "two", "size": "1:1", "resolution": "1k"},
                ]
            )
        )
    finally:
        restore_fakes(originals)

    assert urls == [
        "https://img.example/task-one.png",
        "https://img.example/task-two.png",
    ]
    assert ("GET", "task-one", task_owner["task-one"]) in calls
    assert ("GET", "task-two", task_owner["task-two"]) in calls
    assert fake_keys.failures == []


if __name__ == "__main__":
    tests = [
        test_single_generation_reuses_submit_key_for_polling,
        test_batch_generation_reuses_each_task_submit_key_for_polling,
    ]
    passed = 0
    for test in tests:
        test()
        print(f"[PASS] {test.__name__}")
        passed += 1
    print(f"\nTOTAL: {passed}/{len(tests)} passed")
