import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
import os
import time
from openai import OpenAI

# ---------------- CONFIG ----------------
TOKEN = os.getenv("TOKEN")
OPENAI_KEY = os.getenv("OPENAI_KEY")

ai = OpenAI(api_key=OPENAI_KEY)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DB = "bot.db"
cooldowns = {}

# ---------------- DB ----------------
async def setup_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS vouches (
            user_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
        """)
        await db.commit()

async def add_vouch(user_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT INTO vouches (user_id, count)
        VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET count = count + 1
        """, (user_id,))
        await db.commit()

async def get_vouches(user_id: int):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT count FROM vouches WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0

# ---------------- READY ----------------
@bot.event
async def on_ready():
    await setup_db()
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")

# ---------------- VOUCH ----------------
@bot.tree.command(name="vouch", description="Gib einen Vouch")
async def vouch(interaction: discord.Interaction, user: discord.Member, reason: str):

    if user.id == interaction.user.id:
        return await interaction.response.send_message("❌ Selbstvouch nicht erlaubt", ephemeral=True)

    key = (interaction.user.id, user.id)
    now = time.time()

    if key in cooldowns and now - cooldowns[key] < 10:
        return await interaction.response.send_message("⏳ Cooldown aktiv", ephemeral=True)

    cooldowns[key] = now

    await add_vouch(user.id)

    embed = discord.Embed(title="⭐ Vouch", color=0x00ff99)
    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="From", value=interaction.user.mention)
    embed.add_field(name="Reason", value=reason)

    await interaction.response.send_message(embed=embed)

# ---------------- REP ----------------
@bot.tree.command(name="rep", description="Reputation anzeigen")
async def rep(interaction: discord.Interaction, user: discord.Member = None):

    user = user or interaction.user
    count = await get_vouches(user.id)

    embed = discord.Embed(title=f"📊 Rep - {user.name}", color=0x2b2d31)
    embed.add_field(name="⭐ Vouches", value=str(count))

    await interaction.response.send_message(embed=embed)

# ---------------- AI ----------------
@bot.tree.command(name="ai", description="Frag die AI")
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

# ---------------- MODERATION ----------------
@bot.tree.command(name="kick")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason"):
    await user.kick(reason=reason)
    await interaction.response.send_message(f"👢 Kicked {user}")

@bot.tree.command(name="ban")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason"):
    await user.ban(reason=reason)
    await interaction.response.send_message(f"🔨 Banned {user}")

# ---------------- AUTO MOD + AI CHAT ----------------
@bot.event
async def on_message(message):

    if message.author.bot:
        return

    # simple filter
    bad_words = ["spam", "hate"]

    if any(w in message.content.lower() for w in bad_words):
        await message.delete()
        return await message.channel.send(f"⚠️ {message.author.mention} kein Spam!")

    # AI mention
    if bot.user in message.mentions:

        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()

        if prompt:
            res = ai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Du bist ein hilfreicher Discord Bot."},
                    {"role": "user", "content": prompt}
                ]
            )

            await message.channel.send(res.choices[0].message.content)

    await bot.process_commands(message)

# ---------------- RUN ----------------
bot.run(TOKEN)