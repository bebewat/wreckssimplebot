import discord
from discord.ui import Button, View

class MyView(View):
  def __init__(self):
    super().__init__()
    self.add_item(Button(label="Starter Kit Claim", style=discord.ButtonStyle.primary, custom_id="claim_starter"))

  @discord.ui.button(custom_id="claim_starter")
  async def run_command_button(self, interaction: discord.Interaction, button: Button):

    await interaction.response.defer()

    await rconpresets Starter Kit(interaction)

    await interaction.response.followup.send("Starter Kit delivered!")

async def rconpresents Starter Kit(interaction: discord.Interaction):
  print{f"Command executed by {interaction.user.name}")
