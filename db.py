import os
from urllib.parse import urlparse, unquote
from typing import Optional, Iterable, List, Dict, Any

import aiomysql

DATABASE_URL = os.getenv("DATABASE_URL", "")

async def get_pool():
    return await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS shop_category (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(191) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_shop_category_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS shop_item_library (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(191) NOT NULL,
  blueprint_path TEXT,
  PRIMARY KEY (id),
  UNIQUE KEY uq_cat_name (category_id, name),
  CONSTRAINT fk_itemlib_category
    FOREIGN KEY (category_id) REFERENCES shop_category(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `shop_user` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `discord_id` BIGINT UNSIGNED UNIQUE,
  `eos_id` VARCHAR(64) UNIQUE,
  `steam_id` BIGINT UNSIGNED UNIQUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `shop_item` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `library_id` BIGINT UNSIGNED,
  `category_id` BIGINT UNSIGNED,
  `name` VARCHAR(191) NOT NULL,
  `blueprint_path` TEXT,
  `price` INT UNSIGNED NOT NULL,
  `quantity` INT UNSIGNED NOT NULL DEFAULT 1,
  `quality` INT UNSIGNED NULL,
  `is_blueprint` BOOLEAN DEFAULT FALSE,
  `kind` ENUM('single','kit') NOT NULL DEFAULT 'single',
  `kit_id` INT UNSIGNED NULL,
  `buy_limit` INT UNSIGNED NULL,
  `active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_shop_item_active` (`active`),
  KEY `idx_shop_item_category` (`category_id`),
  KEY `idx_shop_item_library` (`library_id`),
  KEY `idx_shop_item_kind` (`kind`),
  KEY `idx_shop_item_kit` (`kit_id`),
  CONSTRAINT `fk_shop_item_category`
    FOREIGN KEY (`category_id`) REFERENCES `shop_category`(`id`)
    ON DELETE SET NULL,
  CONSTRAINT `fk_shop_item_library`
    FOREIGN KEY (`library_id`) REFERENCES `shop_item_library`(`id`)
    ON DELETE SET NULL
  CONSTRAINT `fk_shop_item_kit`
    FOREIGN KEY (`kit_id`) REFERENCES `shop_kit`(`id`)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `shop_purchase` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `item_id` BIGINT UNSIGNED NOT NULL,
  `price_paid` INT UNSIGNED NOT NULL,
  `quantity` INT UNSIGNED NOT NULL DEFAULT 1,
  `map` VARCHAR(64) NULL,
  `status` ENUM('queued','delivered','failed','cancelled') NOT NULL DEFAULT 'queued',
  `queued_by_user_id` BIGINT UNSIGNED NULL,
  `queued_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `delivered_at` TIMESTAMP NULL DEFAULT NULL,
  `external_ref` VARCHAR(191) NULL,   -- e.g., ArkShop/Tip4Serv/RCON receipt
  PRIMARY KEY (`id`),
  KEY `idx_purchase_user` (`user_id`),
  KEY `idx_purchase_item` (`item_id`),
  KEY `idx_purchase_status` (`status`),
  CONSTRAINT `fk_purchase_user`
    FOREIGN KEY (`user_id`) REFERENCES `shop_user`(`id`)
    ON DELETE RESTRICT,
  CONSTRAINT `fk_purchase_item`
    FOREIGN KEY (`item_id`) REFERENCES `shop_item`(`id`)
    ON DELETE RESTRICT,
  CONSTRAINT `fk_purchase_queued_by`
    FOREIGN KEY (`queued_by_user_id`) REFERENCES `shop_user`(`id`)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `shop_points_ledger` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `delta` INT NOT NULL,                
  `reason` VARCHAR(191) NULL,
  `ref` VARCHAR(191) NULL,         
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_points_user_time` (`user_id`, `created_at`),
  CONSTRAINT `fk_points_user`
    FOREIGN KEY (`user_id`) REFERENCES `shop_user`(`id`)
    ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

"""

async def init_db(pool):
    async with pool.acquire() as con:
        await con.execute(SCHEMA_SQL)

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
        return cur.lastrowid

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
async def list_kits(conn):
    sql = "SELECT id, name FROM shop_kit WHERE active=1 ORDER BY name LIMIT 25"
    async with conn.cursor() as cur:
        await cur.execute(sql)
        return await cur.fetchall()
