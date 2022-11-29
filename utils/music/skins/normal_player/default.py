import datetime
from utils.music.models import LavalinkPlayer
import disnake
from utils.music.converters import fix_characters, time_format
import itertools


def load(player: LavalinkPlayer) -> dict:

    data = {
        "content": None,
        "embeds": []
    }

    embed = disnake.Embed(color=player.bot.get_color(player.guild.me))
    embed_queue = None
    vc_txt = ""

    if not player.paused:
        embed.set_author(
            name="Tocando Agora:",
            icon_url="https://cdn.discordapp.com/attachments/480195401543188483/895862881105616947/music_equalizer.gif"
        )

    else:
        embed.set_author(
            name="Em Pausa:",
            icon_url="https://cdn.discordapp.com/attachments/480195401543188483/896013933197013002/pause.png"
        )

    if player.current_hint:
        embed.set_footer(text=f"💡 Dica: {player.current_hint}")
    else:
        embed.set_footer(
            text=str(player),
            icon_url="https://cdn.discordapp.com/attachments/480195401543188483/907119505971486810/speaker-loud-speaker.gif"
        )

    player.mini_queue_feature = True

    duration = "> 🔴 **⠂Duração:** `Livestream`" if player.current.is_stream else \
        f"> ⏰ **⠂Duração:** `{time_format(player.current.duration)} [`" + \
        f"<t:{int((disnake.utils.utcnow() + datetime.timedelta(milliseconds=player.current.duration - player.position)).timestamp())}:R>`]`"

    txt = f"[`{player.current.single_title}`]({player.current.uri})\n\n" \
          f"{duration}\n" \
          f"> 💠 **⠂Por:** {player.current.authors_md}\n" \
          f"> ✋ **⠂Pedido por:** <@{player.current.requester}>\n" \
          f"> 🔊 **⠂Volume:** `{player.volume}%`"

    if player.current.track_loops:
        txt += f"\n> 🔂 **⠂Repetições restante:** `{player.current.track_loops}`"

    if player.loop:
        if player.loop == 'current':
            e = '🔂'; m = 'Música atual'
        else:
            e = '🔁'; m = 'Fila'
        txt += f"\n> {e} **⠂Modo de repetição:** `{m}`"

    if player.nightcore:
        txt += f"\n> 🇳 **⠂Efeito nightcore:** `ativado`"

    if player.current.album_name:
        txt += f"\n> 💽 **⠂Álbum:** [`{fix_characters(player.current.album_name, limit=13)}`]({player.current.album_url})"

    if player.current.playlist_name:
        txt += f"\n> 📑 **⠂Playlist:** [`{fix_characters(player.current.playlist_name, limit=13)}`]({player.current.playlist_url})"

    if (qlenght:=len(player.queue)) and not player.mini_queue_enabled:
        txt += f"\n> 🎶 **⠂Músicas na fila:** `{qlenght}`"

    if player.keep_connected:
        txt += "\n> ♾️ **⠂Modo 24/7:** `Ativado`"

    elif player.restrict_mode:
        txt += f"\n> 🔒 **⠂Modo restrito:** `Ativado`"

    txt += f"{vc_txt}\n"

    if player.command_log:
        txt += f"```ansi\n [34;1mÚltima Interação[0m```**┕ {player.command_log_emoji} ⠂**{player.command_log}\n"

    if len(player.queue) and player.mini_queue_enabled:

        queue_txt = "\n".join(
            f"`{(n + 1):02}) [{time_format(t.duration) if not t.is_stream else '🔴 Livestream'}]` [`{fix_characters(t.title, 31)}`]({t.uri})"
            for n, t in (enumerate(itertools.islice(player.queue, 3)))
        )

        embed_queue = disnake.Embed(title=f"Músicas na fila: {qlenght}", color=player.bot.get_color(player.guild.me),
                                    description=f"\n{queue_txt}")

        if not player.loop and not player.keep_connected:

            queue_duration = 0

            for t in player.queue:
                if not t.is_stream:
                    queue_duration += t.duration

            embed_queue.description += f"\n`[⌛ As músicas acabam` <t:{int((disnake.utils.utcnow() + datetime.timedelta(milliseconds=(queue_duration + (player.current.duration if not player.current.is_stream else 0)) - player.position)).timestamp())}:R> `⌛]`"

        embed_queue.set_image(url="https://cdn.discordapp.com/attachments/554468640942981147/937918500784197632/rainbow_bar.gif")

    embed.description = txt
    embed.set_image(url="https://cdn.discordapp.com/attachments/554468640942981147/937918500784197632/rainbow_bar.gif")
    embed.set_thumbnail(url=player.current.thumb)

    player.auto_update = 0

    data["embeds"] = [embed_queue, embed] if embed_queue else [embed]

    return data
