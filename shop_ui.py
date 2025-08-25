import json
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

def is_shop_admin():
    return any(r['id'] == str(user_id) for r in admin_roles)

def apply_discounts(user_roles, base_price, current_event=None):
    price = base_price
    for d in discounts:
        if d['type'] == 'role' and d['target'] in user_roles:
            price = price * (1 - d['amount']/100)
        if d['type'] == 'event' and d['target'] == current_event:
            price = price * (1 - d['amount']/100)
    return int(price)

class CategorySelect(Select):
    def __init__(self, categories):
        options = [discord.SelectOption(label=cat["name"], value=str(cat["id"])) for cat in categories]
        super().__init__(placeholder="Choose a category…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: ShopAddView = self.view  # type: ignore
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

class ConfigModal(Modal, title="Configure Shop Item"):
    price = TextInput(label="Price (points)", placeholder="e.g., 100", required=True)
    quantity = TextInput(label="Quantity", placeholder="e.g., 1", required=True, default="1")
    quality = TextInput(label="Quality (optional)", required=False, placeholder="e.g., 100")
    is_blueprint = TextInput(label="Is Blueprint? (true/false)", required=False, default="false")
    buy_limit = TextInput(label="Buy Limit (optional)", required=False, placeholder="e.g., 3")

    def __init__(self, view: "ShopAddView"):
        super().__init__()
        self._view = view

    async def on_submit(self, interaction: discord.Interaction):
        v = self._view
        async with v.pool.acquire() as con:
            lib = await con.fetchrow("select * from shop_item_library where id=$1", v.selected_item_library_id)
            cat_id = lib["category_id"]
            name = lib["name"]
            bp = lib["blueprint_path"]

            # parse modal inputs
            price = int(str(self.price))
            qty = int(str(self.quantity)) if str(self.quantity) else 1
            qual = int(str(self.quality)) if str(self.quality) else None
            is_bp = str(self.is_blueprint).strip().lower() in ("true", "yes", "1", "y")
            limit = int(str(self.buy_limit)) if str(self.buy_limit) else None

            await create_shop_item(con, v.selected_item_library_id, cat_id, name, bp, price, qty, qual, is_bp, limit)

        await interaction.response.edit_message(
            content=f"✅ Added **{name}** to the shop (price {price}, qty {qty}).",
            view=None
        )

class ShopAddView(View):
    def __init__(self, pool, timeout=300):
        super().__init__(timeout=timeout)
        self.pool = pool
        self.selected_category_id = None
        self.selected_item_library_id = None

    async def start(self, interaction: discord.Interaction):
        async with self.pool.acquire() as con:
            cats = await search_categories(con, q="", limit=25)
        self.clear_items()
        self.add_item(CategorySelect(cats))
        await interaction.response.send_message("Select a category:", view=self, ephemeral=True)

    async def show_items(self, interaction: discord.Interaction, page=0):
        limit = 25
        offset = page * limit
        async with self.pool.acquire() as con:
            items = await list_items_by_category(con, self.selected_category_id, limit=limit, offset=offset)
        self.clear_items()
        self.add_item(ItemSelect(items))

        await interaction.response.edit_message(content="Select an item:", view=self)

    async def open_config_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ConfigModal(self))
