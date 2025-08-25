# db.py
import os, asyncpg, json, csv
from typing import Iterable

DATABASE_URL = os.getenv("DATABASE_URL")

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

async def upsert_category(con, name: str) -> int:
    row = await con.fetchrow(
        """insert into shop_category(name)
           values($1)
           on conflict(name) do update set name=excluded.name
           returning id""",
        name.strip()
    )
    return row["id"]

async def upsert_library_item(con, category_id: int, name: str, blueprint_path: str | None) -> int:
    row = await con.fetchrow(
        """insert into shop_item_library(category_id, name, blueprint_path)
           values($1,$2,$3)
           on conflict(category_id, name) do update set blueprint_path=excluded.blueprint_path
           returning id""",
        category_id, name.strip(), blueprint_path
    )
    return row["id"]

async def create_shop_item(con, lib_id: int, category_id: int, name: str, blueprint_path: str | None,
                           price: int, quantity: int, quality: int | None, is_blueprint: bool, buy_limit: int | None):
    await con.execute(
        """insert into shop_item(library_id, category_id, name, blueprint_path, price, quantity, quality, is_blueprint, buy_limit)
           values($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        lib_id, category_id, name, blueprint_path, price, quantity, quality, is_blueprint, buy_limit
    )

async def search_categories(con, q: str, limit=25):
    return await con.fetch(
        "select id, name from shop_category where name ilike $1 order by name limit $2",
        f"%{q}%", limit
    )

async def list_items_by_category(con, category_id: int, limit=25, offset=0):
    return await con.fetch(
        """select id, name from shop_item_library
           where category_id=$1
           order by name limit $2 offset $3""",
        category_id, limit, offset
    )

async def find_item_library(con, category_id: int, name: str):
    return await con.fetchrow(
        "select * from shop_item_library where category_id=$1 and name=$2",
        category_id, name
    )

async def autocomplete_items(con, q: str, limit=25):
    return await con.fetch(
        """select sil.id, sc.name as category, sil.name
           from shop_item_library sil
           join shop_category sc on sc.id = sil.category_id
           where sil.name ilike $1
           order by sil.name limit $2""",
        f"%{q}%", limit
    )
