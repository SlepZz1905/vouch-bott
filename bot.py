import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
import os
import time
from openai import OpenAI

# ---------------- FLASK ----------------
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running"

def run():
    app.run(host="0.0.0.0", port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ---------------- CONFIG ----------------
TOKEN = os.getenv("TOKEN")
OPENAI_KEY = os.getenv("OPENAI_KEY")

LOG_CHANNEL_ID = 0  # optional

ai_client = OpenAI(api_key=OPENAI_KEY)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DB = "vouches.db"
cooldowns = {}

# ---------------- DATABASE ----------------
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


async def get_leaderboard():
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT user_id, count FROM vouches
        ORDER BY count DESC
        LIMIT 10
        """)
        return await cur.fetchall()

# ---------------- START ----------------
@bot.event
async def on_ready():
    await setup_db()
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

# ---------------- VOUCH ----------------
@bot.tree.command(name="vouch", description="Gib einem User einen Vouch")
@app_commands.describe(user="User", reason="Grund")
async def vouch(interaction: discord.Interaction, user: discord.Member, reason: str):

    if user.id == interaction.user.id:
        return await interaction.response.send_message("❌ Du kannst dich nicht selbst vouchen.", ephemeral=True)

    now = time.time()
    key = (interaction.user.id, user.id)

    if key in cooldowns and now - cooldowns[key] < 10:
        return await interaction.response.send_message("⏳ Cooldown aktiv (10s)", ephemeral=True)

    cooldowns[key] = now

    await add_vouch(user.id)

    embed = discord.Embed(title="⭐ New Vouch", color=0x00ff99)
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="From", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)

    await interaction.response.send_message(embed=embed)

# ---------------- REP ----------------
@bot.tree.command(name="rep", description="Zeigt Reputation eines Users")
async def rep(interaction: discord.Interaction, user: discord.Member = None):

    user = user or interaction.user
    count = await get_vouches(user.id)

    embed = discord.Embed(title=f"📊 Reputation - {user.name}", color=0x2b2d31)
    embed.add_field(name="⭐ Vouches", value=str(count), inline=True)

    if user.avatar:
        embed.set_thumbnail(url=user.avatar.url)

    await interaction.response.send_message(embed=embed)

# ---------------- LEADERBOARD ----------------
@bot.tree.command(name="leaderboard", description="Top Users")
async def leaderboard(interaction: discord.Interaction):

    data = await get_leaderboard()

    if not data:
        return await interaction.response.send_message("Keine Daten vorhanden.")

    desc = ""
    for i, (user_id, count) in enumerate(data, start=1):
        desc += f"**{i}.** <@{user_id}> — ⭐ {count}\n"

    embed = discord.Embed(title="🏆 Leaderboard", description=desc, color=0xf1c40f)
    await interaction.response.send_message(embed=embed)

# ---------------- MODERATION ----------------
@bot.tree.command(name="kick", description="Kicke einen User")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund"):
    await user.kick(reason=reason)
    await interaction.response.send_message(f"👢 {user} gekickt | {reason}")

@bot.tree.command(name="ban", description="Banne einen User")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund"):
    await user.ban(reason=reason)
    await interaction.response.send_message(f"🔨 {user} gebannt | {reason}")

@bot.tree.command(name="clear", description="Lösche Nachrichten")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 {amount} Nachrichten gelöscht", ephemeral=True)

# ---------------- AI ----------------
@bot.tree.command(name="ai", description="Frag die AI")
async def ai(interaction: discord.Interaction, frage: str):

    await interaction.response.defer()

    response = ai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Du bist ein hilfreicher Discord Bot."},
            {"role": "user", "content": frage}
        ]
    )

    await interaction.followup.send(response.choices[0].message.content)

# ---------------- AUTO MOD + AI CHAT ----------------
@bot.event
async def on_message(message):

    if message.author.bot:
        return

    # --- Auto Mod ---
    bad_words = ["spam", "hate"]

    if any(word in message.content.lower() for word in bad_words):
        await message.delete()
        await message.channel.send(f"⚠️ {message.author.mention} kein Spam!")
        return

    # --- AI Mention Chat ---
    if bot.user in message.mentions:

        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()

        if not prompt:
            await message.channel.send("❓ Frag mich etwas.")
            return

        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Du bist ein hilfreicher Discord Bot."},
                {"role": "user", "content": prompt}
            ]
        )

        await message.channel.send(response.choices[0].message.content)

    await bot.process_commands(message)

# ---------------- RUN ----------------
bot.run(TOKEN)