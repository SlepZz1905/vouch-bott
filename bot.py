import discord
from discord.ext import commands
import aiosqlite
import os
import time
from openai import OpenAI

# ---------------- CONFIG ----------------
TOKEN = os.getenv("TOKEN")
OPENAI_KEY = os.getenv("OPENAI_KEY")

ai = OpenAI(api_key=OPENAI_KEY)

LOG_CHANNEL_ID = 0  # <- optional

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

DB = "bot.db"

# ---------------- INIT ----------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS warns (user_id INTEGER, count INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS levels (user_id INTEGER PRIMARY KEY, xp INTEGER, level INTEGER)")
        await db.commit()

    await bot.tree.sync()
    print("🔄 Synced")

# ---------------- LOGGING ----------------
async def log(text):
    if LOG_CHANNEL_ID == 0:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(text)

# ---------------- LEVEL SYSTEM ----------------
@bot.event
async def on_message(message):

    if message.author.bot:
        return

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT xp, level FROM levels WHERE user_id=?", (message.author.id,))
        row = await cur.fetchone()

        if row is None:
            await db.execute("INSERT INTO levels VALUES (?, 0, 0)", (message.author.id,))
            xp, level = 0, 0
        else:
            xp, level = row

        xp += 5

        if xp >= 100:
            level += 1
            xp = 0
            await message.channel.send(f"🎉 {message.author.mention} ist jetzt Level {level}!")

        await db.execute("UPDATE levels SET xp=?, level=? WHERE user_id=?", (xp, level, message.author.id))
        await db.commit()

    # ---------------- ANTI SPAM ----------------
    bad_words = ["spam", "hate"]

    if any(w in message.content.lower() for w in bad_words):
        await message.delete()
        await message.channel.send(f"⚠️ {message.author.mention} kein Spam!")
        await log(f"🚫 Filter: {message.author}")

        return

    # ---------------- AI CHAT ----------------
    if bot.user in message.mentions:

        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()

        if prompt:
            res = ai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Du bist ein Discord Moderation Bot."},
                    {"role": "user", "content": prompt}
                ]
            )

            await message.channel.send(res.choices[0].message.content)

    await bot.process_commands(message)

# ---------------- MODERATION ----------------
@bot.tree.command(name="warn")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):

    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT count FROM warns WHERE user_id=?", (user.id,))
        row = await cur.fetchone()

        if row is None:
            count = 1
            await db.execute("INSERT INTO warns VALUES (?, 1)", (user.id,))
        else:
            count = row[0] + 1
            await db.execute("UPDATE warns SET count=? WHERE user_id=?", (count, user.id))

        await db.commit()

    await interaction.response.send_message(f"⚠️ {user} Warn {count}/3")

    await log(f"WARN {user} | {reason}")

    if count >= 3:
        await user.ban(reason="3 Warns erreicht")
        await log(f"🔨 AUTO BAN {user}")

@bot.tree.command(name="kick")
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason"):
    await user.kick(reason=reason)
    await interaction.response.send_message(f"👢 Kicked {user}")
    await log(f"KICK {user}")

@bot.tree.command(name="ban")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason"):
    await user.ban(reason=reason)
    await interaction.response.send_message(f"🔨 Banned {user}")
    await log(f"BAN {user}")

# ---------------- AI COMMAND ----------------
@bot.tree.command(name="ai")
async def ai_cmd(interaction: discord.Interaction, frage: str):

    await interaction.response.defer()

    res = ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Du bist ein hilfreicher Discord Bot."},
            {"role": "user", "content": frage}
        ]
    )

    await interaction.followup.send(res.choices[0].message.content)

# ---------------- TICKET SYSTEM ----------------
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Ticket erstellen", style=discord.ButtonStyle.green)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):

        guild = interaction.guild

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}"
        )

        await channel.set_permissions(interaction.user, read_messages=True, send_messages=True)

        await channel.send(f"🎫 Ticket erstellt für {interaction.user.mention}")

        await interaction.response.send_message("Ticket erstellt!", ephemeral=True)

@bot.tree.command(name="ticket")
async def ticket(interaction: discord.Interaction):
    await interaction.response.send_message("Klicke um Ticket zu erstellen", view=TicketView())

# ---------------- RUN ----------------
bot.run(TOKEN)