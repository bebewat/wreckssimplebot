import os
import asyncio
import logging
from fastapi import FastAPI
import uvicorn
import discord
from discord import app_commands
from discord.ext import commands
from db import get_pool, init_db
from seed_loader import seed_from_json, seed_from_csv
from shop_ui import ShopAddView, is_shop_admin

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)
log = logging.getLogger("wrecksshop")

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
if not DISCORD_TOKEN:
  raise RuntimeError("Missing DISCORD_TOKEN env var")

app = FastAPI()

@app.get("/")
def root():
  return {"status": "ok", "service": "wrecksshop-bot"}

@app.get("/healthz")
def healthz():
  return {"ok": True}

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)

@bot.tree.command(name="ping", description="Check if the bot is alive")
async def ping_cmd(interaction: discord_Interaction):
  await interaction.response.send_message("Pong!", ephemeral=True)

@bot.tree.command(name="thankyou", description="Send a thanks to someone")
@app_commands.describe(
  member="Who do you want to thank?",
  message="Custom thanks here",
  anonymous="Send anonymously (still logged internally)"
)
async def thankyou_cmd(
  interaction: discord.Interaction,
  member: discord.Member,
  message: str,
  anonymous: bool = False
):
  author = Interaction.user
  if anonymous:
    display = f"Someone says: {message}"
  else:
    display = f"{author.mention} says: {message}"
  try: 
    await member.send(f"You received a thank you on {interaction.guild.name}:\n{display}")
  except: Exception:
    await interaction.response.send_message(
      f"Could you DM {member.mention}. Posting here:\n{display}"
    )
    return
  await interaction.response.send_message("Delivered!", ephemeral=True)

class ShopCog(commands.Cog):
  def __init__(self, bot: commands.Bot, pool):
    self.bot = bot
    self.pool = pool
  @app_commands.command(name="shop-add", description="Add a shop item")
  @is_shop_admin()
  async def shop_add(self, interaction: discord.Interaction):
    view = ShopAddView(self.pool)
    await view.start(interaction)

@app_commands.command(name="shop-remove", description="Remove a shop item by name")
@app_commands.describe(name="Item name to remove")
@is_shop_admin()
async def shop_remove(self, interaction: discord.Interaction, name: str):
  async with self.pool.acquire() as con:
    row = await con.fetchrow("Delete from shop_item where name=$1 returning name", name)
    if row: await interaction.response.send_message(f" Removed **{row['name']}**.", ephemeral=True)

@app_commands.command(name="shop-sync-seed", description="Import categories from CSV/JSON")

@bot.event
async def on_ready():
  try: 
    await bot.tree.sync()
    log.info("App commands synced. Logged in as %s (%s)", bot.user, bot.user.id)
except Exception as e:
  log.exception("Failed to sync app commands: %s", e)

async def start_bot():
  await bot.start(DISCORD_TOKEN)

async def main():
  config = uvicorn.Config(app, host"0.0.0.0", port=int(os.getenv("PORT", "10000")), log_level=LOG_LEVEL.lower())
  server = uvicorn.Server(config)

  bot_task = asyncio.create_task(start_bot())
  api_task = asyncio.create_task(server.serve())

  done, pending = await asyncio.wait(
    {bot_task, api_task},
    return_when=asyncio.FIRST_EXCEPTION
  )

for task in pending:
  task.cancel()
for task in done:
  if exc := task.exception():
    raise exc

if __name__ = "__main__":
  try: 
    asyncio.run(main())
  except KeyboardInterrupt:
    pass
      
