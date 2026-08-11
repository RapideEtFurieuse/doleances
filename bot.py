import csv
import io
import os
import sqlite3
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()


TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DATABASE_PATH = os.getenv("DB_PATH", "data/insultes.db")

if not TOKEN:
    raise RuntimeError(
        "Token Discord introuvable. Vérifie DISCORD_BOT_TOKEN dans .env."
    )

if not GUILD_ID:
    raise RuntimeError(
        "ID du serveur introuvable. Vérifie DISCORD_GUILD_ID dans .env."
    )


database_folder = os.path.dirname(DATABASE_PATH)

if database_folder:
    os.makedirs(database_folder, exist_ok=True)


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

GUILD = discord.Object(id=int(GUILD_ID))

ENTRIES_PER_PAGE = 5


def get_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    connection = get_database()

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS doleances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            victime_id TEXT NOT NULL,
            victime_nom TEXT NOT NULL,
            agent_chaos_id TEXT NOT NULL,
            agent_chaos_nom TEXT NOT NULL,
            mefait TEXT NOT NULL,
            preuve TEXT,
            piece_jointe_url TEXT,
            date_doleance TEXT NOT NULL,
            signale_le TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    connection.commit()
    connection.close()


def save_setting(name: str, value: str):
    connection = get_database()

    connection.execute(
        """
        INSERT INTO settings (name, value)
        VALUES (?, ?)
        ON CONFLICT(name)
        DO UPDATE SET value = excluded.value
        """,
        (name, value),
    )

    connection.commit()
    connection.close()


def get_setting(name: str):
    connection = get_database()

    row = connection.execute(
        "SELECT value FROM settings WHERE name = ?",
        (name,),
    ).fetchone()

    connection.close()

    if row:
        return row["value"]

    return None


def parse_date(date_text: Optional[str]) -> str:
    if not date_text or not date_text.strip():
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    date_text = date_text.strip()

    accepted_formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ]

    for date_format in accepted_formats:
        try:
            parsed_date = datetime.strptime(date_text, date_format)

            if date_format in ("%Y-%m-%d", "%d/%m/%Y"):
                parsed_date = parsed_date.replace(hour=12, minute=0)

            return parsed_date.strftime("%Y-%m-%d %H:%M")

        except ValueError:
            pass

    raise ValueError(
        "Date invalide. Utilise par exemple "
        "2026-08-11 18:30 ou 11/08/2026 18:30."
    )


def add_doleance(
    victime: discord.Member,
    agent_chaos: discord.Member,
    mefait: str,
    preuve: Optional[str],
    piece_jointe_url: Optional[str],
    date_doleance: str,
):
    connection = get_database()

    cursor = connection.execute(
        """
        INSERT INTO doleances (
            victime_id,
            victime_nom,
            agent_chaos_id,
            agent_chaos_nom,
            mefait,
            preuve,
            piece_jointe_url,
            date_doleance,
            signale_le
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(victime.id),
            str(victime),
            str(agent_chaos.id),
            str(agent_chaos),
            mefait,
            preuve,
            piece_jointe_url,
            date_doleance,
            str(victime),
        ),
    )

    doleance_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return doleance_id


def get_total_doleances():
    connection = get_database()

    row = connection.execute(
        "SELECT COUNT(*) AS total FROM doleances"
    ).fetchone()

    connection.close()

    return row["total"]


def get_doleances(page: int):
    offset = page * ENTRIES_PER_PAGE

    connection = get_database()

    rows = connection.execute(
        """
        SELECT *
        FROM doleances
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (ENTRIES_PER_PAGE, offset),
    ).fetchall()

    connection.close()

    return rows


def get_agent_counts():
    connection = get_database()

    rows = connection.execute(
        """
        SELECT agent_chaos_nom, COUNT(*) AS total
        FROM doleances
        GROUP BY agent_chaos_id, agent_chaos_nom
        ORDER BY total DESC
        """
    ).fetchall()

    connection.close()

    return rows


def get_victim_counts():
    connection = get_database()

    rows = connection.execute(
        """
        SELECT victime_nom, COUNT(*) AS total
        FROM doleances
        GROUP BY victime_id, victime_nom
        ORDER BY total DESC
        """
    ).fetchall()

    connection.close()

    return rows


def create_embed(page: int = 0):
    total = get_total_doleances()
    total_pages = max(1, (total + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE)

    if page >= total_pages:
        page = total_pages - 1

    if page < 0:
        page = 0

    embed = discord.Embed(
        title="📋 Registre des doléances",
        description=(
            "Actes diaboliques archivés et comptabilisés"
        ),
        color=discord.Color.orange(),
    )

    agent_counts = get_agent_counts()

    if agent_counts:
        agent_text = "\n".join(
            f"• {row['agent_chaos_nom']} : **{row['total']}**"
            for row in agent_counts
        )
    else:
        agent_text = "Aucun agent du chaos enregistré."

    embed.add_field(
        name="☄️ Agents du chaos",
        value=agent_text[:1024],
        inline=True,
    )

    victim_counts = get_victim_counts()

    if victim_counts:
        victim_text = "\n".join(
            f"• {row['victime_nom']} : **{row['total']}**"
            for row in victim_counts
        )
    else:
        victim_text = "Aucune doléance enregistrée."

    embed.add_field(
        name="🛡️ Victimes",
        value=victim_text[:1024],
        inline=True,
    )

    rows = get_doleances(page)

    if not rows:
        entries_text = "Aucune doléance pour le moment."
    else:
        entry_blocks = []

        for row in rows:
            proof_text = row["preuve"] or "Aucune preuve écrite"

            if len(proof_text) > 150:
                proof_text = proof_text[:147] + "..."

            attachment_text = ""

            if row["piece_jointe_url"]:
                attachment_text = (
                    f"\n📎 [Ouvrir la pièce jointe]"
                    f"({row['piece_jointe_url']})"
                )

            block = (
                f"**#{row['id']} · {row['date_doleance']}**\n"
                f"Victime : {row['victime_nom']}\n"
                f"Agent du chaos : {row['agent_chaos_nom']}\n"
                f"Méfait : {row['mefait']}\n"
                f"Preuve : {proof_text}"
                f"{attachment_text}"
            )

            entry_blocks.append(block)

        entries_text = "\n\n".join(entry_blocks)

    if len(entries_text) > 1024:
        entries_text = entries_text[:1000] + "\n..."

    embed.add_field(
        name=f"📜 Doléances · page {page + 1}/{total_pages}",
        value=entries_text,
        inline=False,
    )

    embed.set_footer(
        text=(
            "La victime est automatiquement la personne "
            "qui utilise /doleance."
        )
    )

    return embed, page, total_pages


class TableauView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=None)

        self.page = page

        total = get_total_doleances()
        self.total_pages = max(
            1,
            (total + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE,
        )

        if self.page <= 0:
            self.previous_button.disabled = True

        if self.page >= self.total_pages - 1:
            self.next_button.disabled = True

    @discord.ui.button(
        label="Précédent",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        new_page = max(0, self.page - 1)
        embed, page, total_pages = create_embed(new_page)

        await interaction.response.edit_message(
            embed=embed,
            view=TableauView(page),
        )

    @discord.ui.button(
        label="Actualiser",
        emoji="🔄",
        style=discord.ButtonStyle.primary,
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        embed, page, total_pages = create_embed(self.page)

        await interaction.response.edit_message(
            embed=embed,
            view=TableauView(page),
        )

    @discord.ui.button(
        label="Suivant",
        emoji="➡️",
        style=discord.ButtonStyle.secondary,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        new_page = min(self.total_pages - 1, self.page + 1)
        embed, page, total_pages = create_embed(new_page)

        await interaction.response.edit_message(
            embed=embed,
            view=TableauView(page),
        )


async def refresh_permanent_table():
    channel_id = get_setting("tableau_channel_id")
    message_id = get_setting("tableau_message_id")

    if not channel_id or not message_id:
        return

    try:
        channel = bot.get_channel(int(channel_id))

        if channel is None:
            channel = await bot.fetch_channel(int(channel_id))

        message = await channel.fetch_message(int(message_id))

        embed, page, total_pages = create_embed(0)

        await message.edit(
            embed=embed,
            view=TableauView(page),
        )

    except Exception as error:
        print(f"Impossible de mettre à jour le tableau permanent : {error}")


@bot.tree.command(
    name="doleance",
    description="Ajoute une doléance reçue par la personne qui lance la commande.",
)
@app_commands.guild_only()
@app_commands.describe(
    agent_du_chaos="La personne qui a provoqué le méfait.",
    mefait="Décris le méfait ou l'insulte.",
    preuve="Citation, témoignage ou explication facultative.",
    piece_jointe="Capture, photo ou fichier facultatif.",
    date="Facultatif : 2026-08-11 18:30 ou 11/08/2026 18:30.",
)
async def doleance(
    interaction: discord.Interaction,
    agent_du_chaos: discord.Member,
    mefait: str,
    preuve: Optional[str] = None,
    piece_jointe: Optional[discord.Attachment] = None,
    date: Optional[str] = None,
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "Cette commande doit être utilisée dans un serveur.",
            ephemeral=True,
        )
        return

    if agent_du_chaos.id == interaction.user.id:
        await interaction.response.send_message(
            "Tu ne peux pas être ta propre victime et ton propre agent du chaos.",
            ephemeral=True,
        )
        return

    try:
        parsed_date = parse_date(date)

    except ValueError as error:
        await interaction.response.send_message(
            str(error),
            ephemeral=True,
        )
        return

    doleance_id = add_doleance(
        victime=interaction.user,
        agent_chaos=agent_du_chaos,
        mefait=mefait,
        preuve=preuve,
        piece_jointe_url=piece_jointe.url if piece_jointe else None,
        date_doleance=parsed_date,
    )

    await refresh_permanent_table()

    await interaction.response.send_message(
        f"✅ Doléance #{doleance_id} enregistrée.",
        ephemeral=True,
    )


@bot.tree.command(
    name="tableau",
    description="Affiche le registre actualisé des doléances.",
)
@app_commands.guild_only()
async def tableau(interaction: discord.Interaction):
    embed, page, total_pages = create_embed(0)

    await interaction.response.send_message(
        embed=embed,
        view=TableauView(page),
    )


@bot.tree.command(
    name="installer_tableau",
    description="Crée le tableau permanent dans ce salon.",
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_messages=True)
async def installer_tableau(interaction: discord.Interaction):
    embed, page, total_pages = create_embed(0)

    await interaction.response.send_message(
        "✅ Tableau permanent créé dans ce salon.",
        ephemeral=True,
    )

    message = await interaction.channel.send(
        embed=embed,
        view=TableauView(page),
    )

    save_setting("tableau_channel_id", str(interaction.channel_id))
    save_setting("tableau_message_id", str(message.id))


@bot.tree.command(
    name="doleance_details",
    description="Affiche les détails complets d'une doléance.",
)
@app_commands.guild_only()
@app_commands.describe(
    id="Numéro de la doléance à consulter.",
)
async def doleance_details(
    interaction: discord.Interaction,
    id: int,
):
    connection = get_database()

    row = connection.execute(
        "SELECT * FROM doleances WHERE id = ?",
        (id,),
    ).fetchone()

    connection.close()

    if row is None:
        await interaction.response.send_message(
            f"La doléance #{id} n'existe pas.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"📜 Doléance #{row['id']}",
        color=discord.Color.orange(),
    )

    embed.add_field(
        name="Victime",
        value=row["victime_nom"],
        inline=True,
    )

    embed.add_field(
        name="Agent du chaos",
        value=row["agent_chaos_nom"],
        inline=True,
    )

    embed.add_field(
        name="Date",
        value=row["date_doleance"],
        inline=False,
    )

    embed.add_field(
        name="Méfait",
        value=row["mefait"],
        inline=False,
    )

    embed.add_field(
        name="Preuve",
        value=row["preuve"] or "Aucune preuve écrite",
        inline=False,
    )

    if row["piece_jointe_url"]:
        embed.add_field(
            name="Pièce jointe",
            value=f"[Ouvrir la preuve]({row['piece_jointe_url']})",
            inline=False,
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=False,
    )


@bot.tree.command(
    name="export",
    description="Exporte le registre complet en fichier CSV.",
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_messages=True)
async def export(interaction: discord.Interaction):
    connection = get_database()

    rows = connection.execute(
        "SELECT * FROM doleances ORDER BY id ASC"
    ).fetchall()

    connection.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "id",
            "victime",
            "agent_du_chaos",
            "mefait",
            "preuve",
            "piece_jointe",
            "date",
            "signale_le",
        ]
    )

    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["victime_nom"],
                row["agent_chaos_nom"],
                row["mefait"],
                row["preuve"] or "",
                row["piece_jointe_url"] or "",
                row["date_doleance"],
                row["signale_le"],
            ]
        )

    file_data = io.BytesIO(
        output.getvalue().encode("utf-8-sig")
    )

    file = discord.File(
        file_data,
        filename="registre-des-doleances.csv",
    )

    await interaction.response.send_message(
        "Voici l'export du registre.",
        file=file,
        ephemeral=True,
    )


@bot.event
async def on_ready():
    initialize_database()

    try:
        synced_commands = await bot.tree.sync()

        print(
            f"Connecté en tant que {bot.user} | "
            f"{len(synced_commands)} commandes globales synchronisées"
        )

    except Exception as error:
        print(f"Erreur de synchronisation : {error}")


bot.run(TOKEN)