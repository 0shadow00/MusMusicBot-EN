# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import re
import traceback
from io import BytesIO
from typing import TYPE_CHECKING, Union, Optional

import disnake
from disnake.ext import commands

from utils.db import DBModel
from utils.music.converters import URL_REG, fix_characters, time_format
from utils.music.spotify import spotify_regex_w_user
from utils.others import CustomContext, music_source_emoji_id, PlayerControls

youtube_regex = r"https?://www\.youtube\.com/(?:channel/|@)[^/]+"
soundcloud_regex = r"^(?:https?:\/\/)?(?:www\.)?soundcloud\.com\/([a-zA-Z0-9_-]+)"

if TYPE_CHECKING:
    from utils.client import BotCore

class InteractionModalImport(disnake.ui.Modal):

    def __init__(self, view: IntegrationsView):

        self.view = view

        super().__init__(
            title="Importar integração",
            custom_id="integration_import",
            components=[
                disnake.ui.TextInput(
                    style=disnake.TextInputStyle.long,
                    label="Inserir dados (em formato json)",
                    custom_id="json_data",
                    min_length=20,
                    required=True
                )
            ]
        )

    async def callback(self, inter: disnake.ModalInteraction, /) -> None:

        try:
            json_data = json.loads(inter.text_values["json_data"])
        except Exception as e:
            await inter.send("**Ocorreu um erro ao analisar os dados ou foi enviado dados inválidos/não-formatado "
                               f"em formato json.**\n\n`{repr(e)}`", ephemeral=True)
            return

        cog = self.view.bot.get_cog("IntegrationManager")

        retry_after = cog.integration_import_export_cd.get_bucket(inter).update_rate_limit()
        if retry_after:
            if retry_after < 1:
                retry_after = 1
            await inter.send("**Você deve aguardar {} para importar.**".format(
                time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)
            return

        for name, url in json_data.items():

            if "> itg:" in name.lower():
                continue

            if len(url) > (max_url_chars := 150):
                await inter.edit_original_message(
                    f"**Um item de seu arquivo {url} ultrapassa a quantidade de caracteres permitido:{max_url_chars}**")
                return

            if not isinstance(url, str) or not URL_REG.match(url):
                await inter.edit_original_message(f"O seu arquivo contém link inválido: ```ldif\n{url}```")
                return

        await inter.response.defer(ephemeral=True)

        self.view.data = await self.view.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        for name in json_data.keys():
            try:
                del self.view.data["integration_links"][name.lower()[:90]]
            except KeyError:
                continue

        if self.view.bot.config["MAX_USER_INTEGRATIONS"] > 0 and not (await self.view.bot.is_owner(inter.author)):

            if (json_size := len(json_data)) > self.view.bot.config["MAX_USER_INTEGRATIONS"]:
                await inter.edit_original_message(f"A quantidade de itens no seu arquivo de integrações excede "
                                   f"a quantidade máxima permitida ({self.view.bot.config['MAX_USER_INTEGRATIONS']}).")
                return

            if (json_size + (user_integrations := len(self.view.data["integration_links"]))) > self.view.bot.config[
                "MAX_USER_INTEGRATIONS"]:
                await inter.edit_original_message(
                    "Você não possui espaço suficiente para adicionar todos as integrações de seu arquivo...\n"
                    f"Limite atual: {self.view.bot.config['MAX_USER_INTEGRATIONS']}\n"
                    f"Quantidade de integrações salvas: {user_integrations}\n"
                    f"Você precisa de: {(json_size + user_integrations) - self.view.bot.config['MAX_USER_INTEGRATIONS']}")
                return

        self.view.data["integration_links"].update(json_data)

        await self.view.bot.update_global_data(inter.author.id, self.view.data, db_name=DBModel.users)

        await inter.edit_original_message(
            content="**Integrações importadas com sucesso!**"
        )

        if s := len(json_data) > 1:
            self.view.log = f"{s} integrações foram importadas com sucesso."
        else:
            name = next(iter(json_data))
            self.view.log = f"A integração [`{name}`]({json_data[name]}) foi importada com sucesso."

        if not isinstance(self.view.ctx, CustomContext):
            await self.view.ctx.edit_original_message(embed=self.view.build_embed(), view=self.view)
        elif self.view.message:
            await self.view.message.edit(embed=self.view.build_embed(), view=self.view)


class IntegrationModal(disnake.ui.Modal):
    def __init__(self, name: Optional[str], url: Optional[str], view: IntegrationsView):

        self.view = view
        self.name = name

        super().__init__(
            title="Adicionar integração",
            custom_id="user_integration_add",
            timeout=180,
            components=[
                disnake.ui.TextInput(
                    label="Link/Url:",
                    custom_id="user_integration_url",
                    min_length=10,
                    max_length=200,
                    value=url or None
                ),
            ]
        )

    async def callback(self, inter: disnake.ModalInteraction):

        url = inter.text_values["user_integration_url"].strip()

        try:
            url = URL_REG.findall(url)[0]
        except IndexError:
            await inter.send(
                embed=disnake.Embed(
                    description=f"**Nenhum link válido encontrado:** {url}",
                    color=disnake.Color.red()
                ), ephemeral=True
            )
            return

        if (matches := spotify_regex_w_user.match(url)):

            if not self.view.bot.spotify:
                await inter.send(
                    embed=disnake.Embed(
                        description="**O suporte ao spotify não está disponível no momento...**",
                        color=disnake.Color.red()
                    ), ephemeral=True
                )
                return

            url_type, user_id = matches.groups()

            if url_type != "user":
                await inter.send(
                    embed=disnake.Embed(
                        description=f"**Você deve usar link de um perfil de usuário do spotify.** {url}",
                        color=disnake.Color.red()
                    ), ephemeral=True
                )
                return

            try:
                await inter.response.defer(ephemeral=True)
            except:
                pass

            try:
                result = await self.view.bot.spotify.get_user(user_id)
            except Exception as e:
                await inter.send(
                    embed=disnake.Embed(
                        description="**Ocorreu um erro ao obter informações do spotify:** ```py\n"
                                    f"{repr(e)}```",
                        color=self.view.bot.get_color()
                    )
                )
                traceback.print_exc()
                return

            if not result:
                await inter.send(
                    embed=disnake.Embed(
                        description="**O usuário do link informado não possui playlists públicas...**",
                        color=self.view.bot.get_color()
                    )
                )
                return

            data = {"title": f"[SP]: {result.name[:90]}", "url": url}

        else:

            if not self.view.bot.config["USE_YTDL"]:
                await inter.send(
                    embed=disnake.Embed(
                        description="**Não há suporte a esse tipo de link no momento...**",
                        color=self.view.bot.get_color()
                    )
                )
                return

            match = re.search(youtube_regex, url)

            if match:
                base_url = f"{match.group(0)}/playlists"
                source = "[YT]:"
            else:
                match = re.search(soundcloud_regex, url)
                if match:
                    group = match.group(1)
                    base_url = f"https://soundcloud.com/{group}/sets"
                else:
                    await inter.send(
                        embed=disnake.Embed(
                            description=f"**Link informado não é suportado:** {url}",
                            color=disnake.Color.red()
                        ), ephemeral=True
                    )
                    return

                source = "[SC]:"

            loop = self.view.bot.loop or asyncio.get_event_loop()

            try:
                await inter.response.defer(ephemeral=True)
            except:
                pass

            try:
                info = await loop.run_in_executor(None, lambda: self.view.bot.pool.ytdl.extract_info(base_url, download=False))
            except Exception as e:
                traceback.print_exc()
                await inter.edit_original_message(f"**Ocorreu um erro ao obter informação da url:** ```py\n{repr(e)}```")
                return

            if not info:

                msg = f"**O usuário/canal do link informado não existe:**\n{url}"

                if source == "[YT]:":
                    msg += f"\n\n`Nota: Confira se no link contém usuário com @, ex: @ytchannel`"

                await inter.edit_original_message(
                    embed=disnake.Embed(
                        description=msg,
                        color=disnake.Color.red()
                    )
                )
                return

            if not info['entries']:
                await inter.edit_original_message(
                    embed=disnake.Embed(
                        description=f"**O usuário/canal do link informado não possui playlists públicas...**",
                        color=disnake.Color.red()
                    )
                )
                return

            data = {"title": f"{source} {info['title']}", "url": info["original_url"]}

        self.view.data = await self.view.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        title = fix_characters(data['title'], 80)

        self.view.data["integration_links"][title] = data['url']

        await self.view.bot.update_global_data(inter.author.id, self.view.data, db_name=DBModel.users)

        try:
            me = (inter.guild or self.view.bot.get_guild(inter.guild_id)).me
        except AttributeError:
            me = None

        await inter.edit_original_message(
            embed=disnake.Embed(
                description=f"**Integração adicionada/editada com sucesso:** [`{title}`]({data['url']})\n"
                            "**Ela vai aparecer nas seguintes ocasições:** ```\n"
                            "- Ao usar o comando /play (selecionando a integração no preenchimento automático da busca)\n"
                            "- Ao clicar no botão de tocar favorito do player.\n"
                            "- Ao usar o comando play (prefixed) sem nome ou link.```",
                color=self.view.bot.get_color(me)
            ), view=None
        )

        self.view.log = f"[`{data['title']}`]({data['url']}) foi adicionado nas suas integrações."

        if not isinstance(self.view.ctx, CustomContext):
            await self.view.ctx.edit_original_message(embed=self.view.build_embed(), view=self.view)
        elif self.view.message:
            await self.view.message.edit(embed=self.view.build_embed(), view=self.view)


class IntegrationsView(disnake.ui.View):

    def __init__(self, bot: BotCore, ctx: Union[disnake.AppCmdInter, CustomContext], data: dict, log: str = "", prefix=""):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.current = None
        self.data = data
        self.message = None
        self.log = log
        self.prefix = prefix
        self.update_components()

    def update_components(self):

        self.clear_items()

        if self.data["integration_links"]:

            integration_select = disnake.ui.Select(options=[
                disnake.SelectOption(label=k, emoji=music_source_emoji_id(k)) for k, v in self.data["integration_links"].items()
            ], min_values=1, max_values=1)
            integration_select.options[0].default = True
            self.current = integration_select.options[0].label
            integration_select.callback = self.select_callback
            self.add_item(integration_select)

        integrationadd_button = disnake.ui.Button(label="Adicionar", emoji="💠")
        integrationadd_button.callback = self.integrationadd_callback
        self.add_item(integrationadd_button)

        if self.data["integration_links"]:

            remove_button = disnake.ui.Button(label="Remover", emoji="♻️")
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(label="Limpar Integrações", emoji="🚮")
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

            export_button = disnake.ui.Button(label="Exportar", emoji="📤")
            export_button.callback = self.export_callback
            self.add_item(export_button)

        import_button = disnake.ui.Button(label="Importar", emoji="📥")
        import_button.callback = self.import_callback
        self.add_item(import_button)

        if self.data["integration_links"]:
            play_button = disnake.ui.Button(label="Tocar uma playlist da integração selecionada", emoji="▶")
            play_button.callback = self.play_callback
            self.add_item(play_button)

        cancel_button = disnake.ui.Button(label="Fechar", emoji="❌")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def on_timeout(self):

        try:
            for i in self.children[0].options:
                i.default = self.current == i.value
        except:
            pass

        for c in self.children:
            c.disabled = True

        if isinstance(self.ctx, CustomContext):
            try:
                await self.message.edit(view=self)
            except:
                pass

        else:
            try:
                await self.ctx.edit_original_message(view=self)
            except:
                pass

        self.stop()

    def build_embed(self):

        supported_platforms = []

        if self.bot.config["USE_YTDL"]:
            supported_platforms.extend(["[31;1mYoutube[0m", "[33;1mSoundcloud[0m"])

        if self.bot.spotify:
            supported_platforms.append("[32;1mSpotify[0m")

        if not supported_platforms:
            return

        self.update_components()

        embed = disnake.Embed(
            title="Gerenciador de integrações de canais/perfis com playlists públicas.",
            colour=self.bot.get_color(),
        )

        if not self.data["integration_links"]:
            embed.description = "**Você não possui integrações no momento...**"

        if self.data["integration_links"]:

            embed.description = f"**Suas integrações atuais:**\n\n" + "\n".join(
                f"> ` {n + 1} ` [`{f[0]}`]({f[1]})" for n, f in enumerate(self.data["integration_links"].items()))

            cog = self.bot.get_cog("Music")

            if cog:

                try:
                    cmd = f"</play:" + str(self.bot.pool.controller_bot.get_global_command_named("play",
                                                                                                 cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"
                except AttributeError:
                    cmd = "/play"

                embed.add_field(name="**Como tocar a playlist de uma integração?**", inline=False,
                                value=f"* Usando o comando {cmd} (no preenchimento automático da busca)\n"
                                      "* Clicando no botão/select de tocar favorito/integração do player.\n"
                                      f"* Usando o comando {self.prefix}{cog.play_legacy.name} sem incluir um nome ou link de uma música/vídeo.\n"
                                      "* Usando o botão de tocar integração abaixo.")

        if self.log:
            embed.add_field(name="Última interação:", value=self.log)

        embed.add_field(
            name="Links de perfis/canais suportados:", inline=False,
            value=f"```ansi\n{', '.join(supported_platforms)}```"
        )
        return embed

    async def integrationadd_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(IntegrationModal(name=None, url=None, view=self))

    async def remove_callback(self, inter: disnake.MessageInteraction):

        if not self.current:
            await inter.send("Você deve selecionar um item!", ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        try:
            self.data = inter.global_user_data
        except AttributeError:
            self.data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = self.data

        try:
            url = f'[`{self.current}`]({self.data["integration_links"][self.current]})'
            del self.data["integration_links"][self.current]
        except:
            await inter.send(f"**Não há integração na lista com o nome:** {self.current}", ephemeral=True)
            return

        await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

        self.log = f"Integração {url} foi removida com sucesso!"
        await inter.edit_original_message(embed=self.build_embed(), view=self)

    async def clear_callback(self, inter: disnake.MessageInteraction):

        await inter.response.defer(ephemeral=True)

        try:
            self.data = inter.global_user_data
        except AttributeError:
            self.data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = self.data

        if not self.data["integration_links"]:
            await inter.response.edit_message(content="**Você não possui integrações salvas!**", view=None)
            return

        fp = BytesIO(bytes(json.dumps(self.data["integration_links"], indent=4), 'utf-8'))

        self.data["integration_links"].clear()

        await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

        self.log = "Sua lista de integrações foi limpa com sucesso!"

        await inter.send("### Suas integrações foram excluídas com sucesso!\n"
                         "`um arquivo de backup foi gerado e caso queira reverter essa exclusão, copie o "
                         "conteúdo do arquivo e clique no botão \"importar\" e cole o conteudo no campo indicado.`",
                         ephemeral=True, file=disnake.File(fp, filename="integrations.json"))

        if not isinstance(self.ctx, CustomContext):
            await self.ctx.edit_original_message(embed=self.build_embed(), view=self)
        elif self.message:
            await self.message.edit(embed=self.build_embed(), view=self)

    async def import_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(InteractionModalImport(view=self))

    async def play_callback(self, inter: disnake.MessageInteraction):
        await self.bot.get_cog("Music").player_controller(inter, PlayerControls.enqueue_fav, query=f"> itg: {self.current}")

    async def export_callback(self, inter: disnake.MessageInteraction):
        await self.bot.get_cog("IntegrationManager").export_(inter)

    async def cancel_callback(self, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            embed=disnake.Embed(
                description="**Operação com integrações cancelada...**",
                color=self.bot.get_color(),
            ), view=None
        )
        self.stop()

    async def select_callback(self, inter: disnake.MessageInteraction):
        self.current = inter.values[0]
        await inter.response.defer()

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:

        if inter.author.id == self.ctx.author.id:
            return True

        await inter.send(f"Apenas o membro {self.ctx.author.mention} pode interagir nessa mensagem.", ephemeral=True)


class IntegrationManager(commands.Cog):

    emoji = "💠"
    name = "Integrações"
    desc_prefix = f"[{emoji} {name}] | "

    def __init__(self, bot: BotCore):
        self.bot = bot

    itg_cd = commands.CooldownMapping.from_cooldown(3, 15, commands.BucketType.member)

    async def integration(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @commands.command(name="integrations", aliases=["integrationmanager", "itg", "itgmgr", "itglist", "integrationlist"],
                      description="Gerenciar suas integrações.", cooldown=itg_cd)
    async def integratios_legacy(self, ctx: CustomContext):
        await self.integrations.callback(self=self, inter=ctx)

    @commands.max_concurrency(1, commands.BucketType.member, wait=False)
    @commands.slash_command(
        description=f"{desc_prefix}Gerenciar suas integrações de canais/perfis com playlists públicas.",
        cooldown=itg_cd, dm_permission=False)
    async def integrations(self, inter: disnake.AppCmdInter):

        await inter.response.defer(ephemeral=True)

        try:
            user_data = inter.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = user_data

        if isinstance(inter, CustomContext):
            prefix = inter.clean_prefix
        else:
            try:
                global_data = inter.global_guild_data
            except AttributeError:
                global_data = await self.bot.get_global_data(inter.guild_id, db_name=DBModel.guilds)
                try:
                    inter.global_guild_data = global_data
                except:
                    pass
            prefix = global_data['prefix'] or self.bot.default_prefix

        view = IntegrationsView(bot=self.bot, ctx=inter, data=user_data, prefix=prefix)

        embed = view.build_embed()

        if not embed:
            await inter.send("**Não há suporte a esse recurso no momento...**\n\n"
                               "`Suporte ao spotify e YTDL não estão ativados.`", ephemeral=True)
            return

        if isinstance(inter, CustomContext):
            try:
                view.message = inter.store_message
                await inter.store_message.edit(embed=embed, view=view)
            except:
                view.message = await inter.send(embed=embed, view=view)
        else:
            try:
                await inter.edit_original_message(embed=embed, view=view)
            except:
                await inter.response.edit_message(embed=embed, view=view)

        await view.wait()

    integration_import_export_cd = commands.CooldownMapping.from_cooldown(1, 15, commands.BucketType.member)

    async def export_(self, inter: disnake.MessageInteraction):

        retry_after = self.integration_import_export_cd.get_bucket(inter).update_rate_limit()
        if retry_after:
            if retry_after < 1:
                retry_after = 1
            await inter.send("**Você deve aguardar {} para exportar.**".format(
                time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)
            return

        await inter.response.defer(ephemeral=True)

        try:
            user_data = inter.global_user_data
        except AttributeError:
            user_data = await self.bot.get_global_data(inter.author.id, db_name=DBModel.users)
            inter.global_user_data = user_data

        try:
            cmd = f"</{self.integrations.name}:" + str(
                self.bot.pool.controller_bot.get_global_command_named(self.integrations.name,
                                                                  cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"
        except AttributeError:
            cmd = "/play"

        if not user_data["integration_links"]:
            await inter.edit_original_message(f"**Você não possui integrações adicionadas...\n"
                               f"Você pode adicionar usando o comando: {cmd}**")
            return

        fp = BytesIO(bytes(json.dumps(user_data["integration_links"], indent=4), 'utf-8'))

        embed = disnake.Embed(
            description=f"Suas integrações estão aqui.\nVocê pode importar usando o comando: {cmd}",
            color=self.bot.get_color())

        await inter.send(embed=embed, file=disnake.File(fp=fp, filename="integrations.json"), ephemeral=True)


def setup(bot: BotCore):

    if bot.config["USE_YTDL"] and not hasattr(bot.pool, 'ytdl'):

        from yt_dlp import YoutubeDL

        bot.pool.ytdl = YoutubeDL(
            {
                'extract_flat': True,
                'quiet': True,
                'no_warnings': True,
                'lazy_playlist': True,
                'simulate': True,
                'cachedir': False,
                'allowed_extractors': [
                    r'.*youtube.*',
                    r'.*soundcloud.*',
                ],
                'extractor_args': {
                    'youtube': {
                        'skip': [
                            'hls',
                            'dash',
                            'translated_subs'
                        ],
                        'player_skip': [
                            'js',
                            'configs',
                            'webpage'
                        ],
                        'player_client': ['android_creator'],
                        'max_comments': [0],
                    },
                    'youtubetab': {
                        "skip": ["webpage"]
                    }
                }
            }
        )

    bot.add_cog(IntegrationManager(bot))
