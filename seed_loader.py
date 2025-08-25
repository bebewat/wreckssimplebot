import csv, json, os
from db import upsert_category, upsert_library_item

async def seed_from_json(con, path: str):
  data = json.load(open(path, "r", encoding="utf-8"))
  for cat, items in data.items():
    cid = await upsert_category(con, cat)
    for it in items:
      await upsert_library_item(con, cid, it["name"], it.get("blueprint_path"))

async def seed_from_csv(conn, path: str):
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat = row.get("category") or row.get("Category")
            name = row.get("name") or row.get("Name")
            bp = row.get("blueprint_path") or row.get("BlueprintPath")
            if not (cat and name):
                continue
            cid = await upsert_category(conn, cat.strip())
            await upsert_library_item(conn, cid, name.strip(), bp)
