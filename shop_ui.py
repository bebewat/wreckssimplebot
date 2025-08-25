import json, os
from pathlib import Path
from typing import Optional, Set
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select, Button, Modal, TextInput

from db import get_pool, list_items_by_category, search_categories, find_item_library, create_shop_item

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SHOP_LOG_CHANNEL_ID = int(os.getenv("SHOP_LOG_CHANNEL_ID", 0))
SHOP_CHANNEL = int(os.getenv("SHOP_CHANNEL", 0))
REWARD_INTERVAL_MINUTES = int(os.getenv("REWARD_INTERVAL_MINUTES", 30))
REWARD_POINTS = int(os.getenv("REWARD_POINTS", 10))

ADMIN_ROLE_PATH = Path(__file__).parent / 'admin_roles.json'
DISCOUNTS_PATH = Path(__file__).parent / 'discounts.json'

admin_roles = json.loads(ADMIN_ROLE_PATH.read_text()) if ADMIN_ROLE_PATH.exists() else []
discounts = json.loads(DISCOUNTS_PATH.read_text()) if DISCOUNTS_PATH.exists() else []

def _admin_role_ids() -> Set[str]:
    try:
        return {str(r["id"]) for r in admin_roles}
    except Exception:
        return set()
        
def is_shop_admin():
    """Shop Admin Roles"""
    allowed = _admin_role_ids()
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        user_role_ids = {str(r.id) for r in getattr(interaction.user, "roles", [])}
        return bool(allowed & user_role_ids)
    return app_commands.check(predicate)

def apply_discounts(user_roles: Set[str], base_price: int, current_event: Optional[str] = None) -> int:
    price = float(base_price)
    for d in discounts:
        if d.get("type") == "role" and d.get("target") in user_roles:
            price *= (1.0 - float(d.get("amount", 0)) / 100.0)
        if d.get("type") == "event" and d.get("target") == current_event:
            price *= (1.0 - float(d.get("amount", 0)) / 100.0)
    return int(round(price))

class CategorySelect(Select):
    def __init__(self, categories):
        options = [discord.SelectOption(label=cat["name"], value=str(cat["id"])) for cat in categories]
        super().__init__(placeholder="Choose a category…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: "ShopAddView" = self.view  
        view.selected_category_id = int(self.values[0])
        await view.show_items(interaction)

class ItemSelect(Select):
    def __init__(self, items):
        options = [discord.SelectOption(label=it["name"], value=str(it["id"])) for it in items]
        super().__init__(placeholder="Choose an item…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: ShopAddView = self.view  # type: ignore
        view.selected_item_library_id = int(self.values[0])
        await view.open_config_modal(interaction)

class ConfigModal(Modal):
    def __init__(self, view: "ShopAddView"):
        super().__init__(title="Configure Shop Item")
        self._view = view
        
        self.price = TextInput(label="Price (points)", placeholder="e.g., 100", required=True)
        self.quantity = TextInput(label="Quantity", placeholder="e.g., 1", required=True, default="1")
        self.quality = TextInput(label="Quality (optional)", required=False, placeholder="e.g., 100")
        self.is_blueprint = TextInput(label="Is Blueprint? (true/false)", required=False, default="false")
        self.buy_limit = TextInput(label="Buy Limit (optional)", required=False, placeholder="e.g., 3")

        self.add_item(self.price)
        self.add_item(self.quantity)
        self.add_item(self.quality)
        self.add_item(self.is_blueprint)
        self.add_item(self.buy_limit)

    async def on_submit(self, interaction: discord.Interaction):
        v = self._view
        async with v.pool.acquire() as con:
            if v.kind == "single":
                lib = await find_item_library(con, v.selected_item_library_id)
                if not lib:
                    await interaction.response.edit_message(content="Item not found.", view=None)
                    return

                cat_id = lib["category_id"]
                name = lib["name"]
                bp = lib.get("blueprint_path")

                price = int(self.price.value)
                qty = int(self.quantity.value or 1)
                qual = int(self.quality.value) if self.quality.value else None
                is_bp = str(self.is_blueprint.value).strip().lower() in ("true", "yes", "1", "y")
                limit = int(self.buy_limit.value) if self.buy_limit.value else None

                await create_shop_item(
                    con,
                    v.selected_item_library_id,
                    cat_id,
                    name,
                    bp,
                    price,
                    qty,
                    qual,
                    is_bp,
                    limit,
                )
                msg = f"✅ Added **{name}** to the shop (price {price}, qty {qty})."

        else:  
                kit = await get_kit_by_id(con, v.selected_kit_id)
                if not kit:
                    await interaction.response.edit_message(content="Kit not found.", view=None)
                    return

                price = int(self.price.value)
                qty = int(self.quantity.value or 1)
                limit = int(self.buy_limit.value) if self.buy_limit.value else None

                await create_shop_item_kit(
                    con,
                    kit_id=v.selected_kit_id,
                    name=kit["name"],
                    price=price,
                    quantity=qty,
                    buy_limit=limit,
                )
                msg = f"✅ Added **{kit['name']}** (kit) to the shop (price {price}, qty {qty})."

        await interaction.response.edit_message(content=msg, view=None)
     
class ShopAddView(View):
    def __init__(self, pool, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.pool = pool
        self.kind = "single"
        self.selected_kit_id: Optional[int] = None
        self.selected_category_id: Optional[int] = None
        self.selected_item_library_id: Optional[int] = None

    async def start(self, interaction: discord.Interaction):
        self.clear_items()
        self.add_item(KindSelect())
        await interaction.response.send_message("Add to shop:", view=self, ephemeral=True)

    async def start_category_flow(self, interaction: discord.Interaction):
        async with self.pool.acquire() as con:
            cats = await search_categories(con, q="", limit=25)
        self.clear_items()
        self.add_item(CategorySelect(cats))
        await interaction.response.edit_message(content="Select a category:", view=self)

    async def start_kit_flow(self, interaction: discord.Interaction):
        async with self.pool.acquire() as con:
            kits = await con.fetch("select id, name from shop_kit where active=1 order by name limit 25")
        self.clear_items()
        self.add_item(KitSelect(kits))
        await interaction.response.edit_message(content="Choose a kit:", view=self)

    async def show_items(self, interaction: discord.Interaction, page: int = 0):
        limit = 25
        offset = page * limit
        async with self.pool.acquire() as con:
            items = await list_items_by_category(con, self.selected_category_id, limit=limit, offset=offset)
        self.clear_items()
        self.add_item(ItemSelect(items))
        await interaction.response.edit_message(content="Select an item:", view=self)

    async def open_config_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ConfigModal(self))
