from prompts_v2 import match_category, select_model, generate_all_tasks

# Test matching
print("=== Category Matching Tests ===")
for ptype in ["连衣裙", "T恤", "运动鞋", "戒指", "口红", "沙发", "手机", "手表", "项链", "卫衣", "蓝牙耳机"]:
    c = match_category(ptype)
    m = select_model("", c)
    print(f"  {ptype:8s} -> {c['name']:10s} | shot: {c['shot_type']:7s} | model: {m}")

print()

# Test task generation
print("=== Task Generation ===")
t = generate_all_tasks("连衣裙", "http://test.com/1.png", "korea", "", "1:1", "1k")
print(f"  Tasks: {len(t['tasks'])}")
print(f"  Model: {t['model_code']} ({t['model_profile']['name']})")
print(f"  Category: {t['category']['name']} / {t['category']['parent']}")
print(f"  First prompt length: {len(t['tasks'][0]['prompt'])} chars")
print()
print("=== First Prompt Preview ===")
print(t['tasks'][0]['prompt'][:500])
