from database import get_db
db = get_db()
cols = [r[1] for r in db.execute("PRAGMA table_info('generation_history')").fetchall()]
print("Has llm_request:", "llm_request" in cols)
print("Has llm_response:", "llm_response" in cols)
print("Has tasks_detail:", "tasks_detail" in cols)

rows = db.execute(
    "SELECT id, product_type, created_at, llm_request, llm_response, tasks_detail FROM generation_history ORDER BY id DESC LIMIT 3"
).fetchall()
for r in rows:
    print(f"\nID={r[0]} product={r[1]} time={r[2]}")
    print(f"  llm_request: {bool(r[3])} ({len(r[3] or '')} chars)")
    print(f"  llm_response: {bool(r[4])} ({len(r[4] or '')} chars)")
    print(f"  tasks_detail: {bool(r[5])} ({len(r[5] or '')} chars)")
