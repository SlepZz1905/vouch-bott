import discord
from discord import app_commands
import aiosqlite
import time
import os 


TOKEN = os.getenv("TOKEN")
LOG_CHANNEL_ID = 0  # <- optional eintragen

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

DB = "vouches.db"
cooldowns = {}  # anti spam


# ---------------- DB ----------------
async def setup_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS vouches (
            user_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS last_vouch (
            giver_id INTEGER,
            receiver_id INTEGER,
            timestamp INTEGER
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


async def set_last_vouch(giver, receiver):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO last_vouch VALUES (?, ?, ?)",
            (giver, receiver, int(time.time()))
        )
        await db.commit()


async def get_leaderboard():
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
            SELECT user_id, count FROM vouches
            ORDER BY count DESC
            LIMIT 10
        """)
        return await cur.fetchall()


# ---------------- EVENTS ----------------
@client.event
async def on_ready():
    await setup_db()
    await tree.sync()
    print(f"Logged in as {client.user}")


# ---------------- VOUCH COMMAND ----------------
@tree.command(name="vouch", description="Gib einem User einen Vouch")
@app_commands.describe(user="User", reason="Grund")
async def vouch(interaction: discord.Interaction, user: discord.Member, reason: str):

    if user.id == interaction.user.id:
        return await interaction.response.send_message("❌ Du kannst dich nicht selbst vouchen.", ephemeral=True)

    # cooldown (10 sec)
    now = time.time()
    key = (interaction.user.id, user.id)

    if key in cooldowns and now - cooldowns[key] < 10:
        return await interaction.response.send_message("⏳ Cooldown aktiv (10s)", ephemeral=True)

    cooldowns[key] = now

    await add_vouch(user.id)
    await set_last_vouch(interaction.user.id, user.id)

    embed = discord.Embed(
        title="⭐ New Vouch",
        color=0x00ff99
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="From", value=interaction.user.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)

    await interaction.response.send_message(embed=embed)

    # log channel
    if LOG_CHANNEL_ID:
        channel = client.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)


# ---------------- PROFILE / REP ----------------
@tree.command(name="rep", description="Zeigt Reputation eines Users")
async def rep(interaction: discord.Interaction, user: discord.Member = None):
    user = user or interaction.user
    count = await get_vouches(user.id)

    embed = discord.Embed(
        title=f"📊 Reputation - {user.name}",
        color=0x2b2d31
    )
    embed.add_field(name="⭐ Vouches", value=str(count), inline=True)
    embed.set_thumbnail(url=user.avatar.url if user.avatar else None)

    await interaction.response.send_message(embed=embed)


# ---------------- LEADERBOARD ----------------
@tree.command(name="leaderboard", description="Top Vouched Users")
async def leaderboard(interaction: discord.Interaction):

    data = await get_leaderboard()

    embed = discord.Embed(
        title="🏆 Vouch Leaderboard",
        color=0xf1c40f
    )

    if not data:
        return await interaction.response.send_message("Keine Daten vorhanden.")

    desc = ""
    for i, (user_id, count) in enumerate(data, start=1):
        desc += f"**{i}.** <@{user_id}> — ⭐ {count}\n"

    embed.description = desc

    await interaction.response.send_message(embed=embed)


# ---------------- RUN ----------------
client.run(TOKEN)