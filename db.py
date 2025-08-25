# db.py — MySQL/MariaDB version using aiomysql

import os
from urllib.parse import urlparse, unquote
from typing import Optional, Iterable, List, Dict, Any

import aiomysql

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ------------------------- Pool -------------------------

_pool: Optional[aiomysql.Pool] = None

def _parse_mysql_url(url: str) -> Dict[str, Any]:
    u = urlparse(url)
    if u.scheme not in ("mysql", "mariadb"):
        raise RuntimeError("DATABASE_URL must start with mysql:// or mariadb://")
    return {
        "host": u.hostname or "localhost",
        "port": u.port or 3306,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "db": (u.path or "/").lstrip("/") or None,
    }

async def get_pool() -> aiomysql.Pool:
    global _pool
    if _pool is None:
        cfg = _parse_mysql_url(DATABASE_URL)
        _pool = await aiomysql.create_pool(
            minsize=1,
            maxsize=5,
            autocommit=True,
            charset="utf8mb4",
            cursorclass=aiomysql.DictCursor,
            **cfg,
        )
    return _pool

# If you need to create tables here, put DDL in this function.
async def init_db(pool: aiomysql.Pool) -> None:
    # No-op by default (you already created your core tables).
    # Keep here so app startup doesn’t break.
    return

# ------------------------- Helpers -------------------------

# Categories

async def upsert_category(conn: aiomysql.Connection, name: str) -> int:
    """
    Requires UNIQUE KEY on shop_category(name).
    Returns id whether inserted or exists.
    """
    sql = """
    INSERT INTO shop_category (name)
    VALUES (%s)
    ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
    """
    async with conn.cursor() as cur:
        await cur.execute(sql, (name.strip(),))
        return cur.lastrowid  # works for insert or existing due to LAST_INSERT_ID trick

# Library items

async def upsert_library_item(
    conn: aiomysql.Connection,
    category_id: int,
    name: str,
    blueprint_path: Optional[str],
) -> int:
    """
    Requires UNIQUE KEY on shop_item_library(category_id, name).
    """
    sql = """
    INSERT INTO shop_item_library (category_id, name, blueprint_path)
    VALUES (%s, %s, %s)
    ON DUPLICATE KEY UPDATE
        blueprint_path = VALUES(blueprint_path),
        id = LAST_INSERT_ID(id)
    """
    async with conn.cursor() as cur:
        await cur.execute(sql, (category_id, name.strip(), blueprint_path))
        return cur.lastrowid

async def find_item_library(conn: aiomysql.Connection, library_id: int) -> Optional[Dict[str, Any]]:
    sql = "SELECT * FROM shop_item_library WHERE id = %s"
    async with conn.cursor() as cur:
        await cur.execute(sql, (library_id,))
        return await cur.fetchone()

async def list_items_by_category(
    conn: aiomysql.Connection,
    category_id: int,
    limit: int = 25,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    sql = """
    SELECT id, name
    FROM shop_item_library
    WHERE category_id = %s
    ORDER BY name
    LIMIT %s OFFSET %s
    """
    async with conn.cursor() as cur:
        await cur.execute(sql, (category_id, int(limit), int(offset)))
        return await cur.fetchall()

async def search_categories(
    conn: aiomysql.Connection,
    q: str,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    sql = """
    SELECT id, name
    FROM shop_category
    WHERE name LIKE %s
    ORDER BY name
    LIMIT %s
    """
    pattern = f"%{q}%"
    async with conn.cursor() as cur:
        await cur.execute(sql, (pattern, int(limit)))
        return await cur.fetchall()

async def autocomplete_items(
    conn: aiomysql.Connection,
    q: str,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    sql = """
    SELECT sil.id, sc.name AS category, sil.name
    FROM shop_item_library sil
    JOIN shop_category sc ON sc.id = sil.category_id
    WHERE sil.name LIKE %s
    ORDER BY sil.name
    LIMIT %s
    """
    pattern = f"%{q}%"
    async with conn.cursor() as cur:
        await cur.execute(sql, (pattern, int(limit)))
        return await cur.fetchall()

# Shop items (live)

async def create_shop_item(
    conn: aiomysql.Connection,
    library_id: int,
    category_id: int,
    name: str,
    blueprint_path: Optional[str],
    price: int,
    quantity: int,
    quality: Optional[int],
    is_blueprint: bool,
    buy_limit: Optional[int],
) -> None:
    """
    Inserts a live shop item representing a single library item.
    Assumes shop_item has columns:
      kind ENUM('single','kit') DEFAULT 'single'
    """
    sql = """
    INSERT INTO shop_item
      (kind, library_id, category_id, name, blueprint_path, price, quantity, quality, is_blueprint, buy_limit, active)
    VALUES
      ('single', %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
    """
    async with conn.cursor() as cur:
        await cur.execute(
            sql,
            (
                library_id,
                category_id,
                name,
                blueprint_path,
                int(price),
                int(quantity),
                (int(quality) if quality is not None else None),
                1 if is_blueprint else 0,
                (int(buy_limit) if buy_limit is not None else None),
            ),
        )

# Kits

async def get_kit_by_id(conn: aiomysql.Connection, kit_id: int) -> Optional[Dict[str, Any]]:
    sql = "SELECT id, name FROM shop_kit WHERE id = %s"
    async with conn.cursor() as cur:
        await cur.execute(sql, (kit_id,))
        return await cur.fetchone()

async def create_shop_item_kit(
    conn: aiomysql.Connection,
    kit_id: int,
    name: str,
    price: int,
    quantity: int,
    buy_limit: Optional[int],
) -> None:
    """
    Inserts a live shop item representing a kit.
    """
    sql = """
    INSERT INTO shop_item
      (kind, kit_id, name, price, quantity, buy_limit, active)
    VALUES
      ('kit', %s, %s, %s, %s, %s, TRUE)
    """
    async with conn.cursor() as cur:
        await cur.execute(
            sql,
            (kit_id, name, int(price), int(quantity), (int(buy_limit) if buy_limit is not None else None)),
        )
