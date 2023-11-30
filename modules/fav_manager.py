# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from io import BytesIO
from typing import TYPE_CHECKING, Union, Optional

import disnake
from disnake.ext import commands

from utils.db import DBModel
from utils.music.converters import URL_REG, time_format
from utils.others import CustomContext, music_source_emoji_url, PlayerControls

if TYPE_CHECKING:
    from utils.client import BotCore


class UserFavModalImport(disnake.ui.Modal):

    def __init__(self, view: UserFavView):

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

        cog = self.view.bot.get_cog("FavManager")

        retry_after = cog.fav_import_export_cd.get_bucket(inter).update_rate_limit()
        if retry_after:
            if retry_after < 1:
                retry_after = 1
            await inter.send("**Você deve aguardar {} para importar.**".format(
                time_format(int(retry_after) * 1000, use_names=True)), ephemeral=True)
            return

        try:
            json_data = json.loads(inter.text_values["json_data"])
        except Exception as e:
            await inter.send(
                "**Ocorreu um erro ao analisar os dados ou foi enviado dados inválidos/não-formatado "
                f"em formato json.**\n\n`{repr(e)}`", ephemeral=True)
            return

        for name, url in json_data.items():

            if "> fav:" in name.lower():
                continue

            if len(url) > (max_url_chars := self.view.bot.config["USER_FAV_MAX_URL_LENGTH"]):
                await inter.send(
                    f"**Um item de seu arquivo {url} ultrapassa a quantidade de caracteres permitido:{max_url_chars}**",
                    ephemeral=True)
                return

            if not isinstance(url, str) or not URL_REG.match(url):
                await inter.send(f"O seu arquivo contém link inválido: ```ldif\n{url}```", ephemeral=True)
                return

        await inter.response.defer(ephemeral=True)

        self.view.data = await self.view.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        for name in json_data.keys():
            if len(name) > (max_name_chars := self.view.bot.config["USER_FAV_MAX_NAME_LENGTH"]):
                await inter.edit_original_message(
                    f"**Um item de seu arquivo ({name}) ultrapassa a quantidade de caracteres permitido:{max_name_chars}**")
                return
            try:
                del self.view.data["fav_links"][name.lower()]
            except KeyError:
                continue

        if self.view.bot.config["MAX_USER_FAVS"] > 0 and not (await self.view.bot.is_owner(inter.author)):

            if (json_size := len(json_data)) > self.view.bot.config["MAX_USER_FAVS"]:
                await inter.edit_original_message(f"A quantidade de itens no seu arquivo de favorito excede "
                                                  f"a quantidade máxima permitida ({self.view.bot.config['MAX_USER_FAVS']}).")
                return

            if (json_size + (user_favs := len(self.view.data["fav_links"]))) > self.view.bot.config["MAX_USER_FAVS"]:
                await inter.edit_original_message(
                    "Você não possui espaço suficiente para adicionar todos os favoritos de seu arquivo...\n"
                    f"Limite atual: {self.view.bot.config['MAX_USER_FAVS']}\n"
                    f"Quantidade de favoritos salvos: {user_favs}\n"
                    f"Você precisa de: {(json_size + user_favs) - self.view.bot.config['MAX_USER_FAVS']}")
                return

        self.view.data["fav_links"].update(json_data)

        await self.view.bot.update_global_data(inter.author.id, self.view.data, db_name=DBModel.users)

        await inter.edit_original_message(
            content="**Integrações importadas com sucesso!**"
        )

        if not isinstance(self.view.ctx, CustomContext):
            await self.view.ctx.edit_original_message(embed=self.view.build_embed(), view=self.view)
        elif self.view.message:
            await self.view.message.edit(embed=self.view.build_embed(), view=self.view)

class UserFavModal(disnake.ui.Modal):
    def __init__(self, name: Optional[str], url: Optional[str], view: UserFavView):
        self.name = name
        self.url = url
        self.view = view

        super().__init__(
            title="Adicionar/Editar playlist/favorito",
            custom_id="user_fav_edit",
            timeout=180,
            components=[
                disnake.ui.TextInput(
                    label="Nome da playlist/favorito:",
                    custom_id="user_fav_name",
                    min_length=2,
                    max_length=25,
                    value=name or None
                ),
                disnake.ui.TextInput(
                    label="Link/Url:",
                    custom_id="user_fav_url",
                    min_length=10,
                    max_length=200,
                    value=url or None
                ),
            ]
        )

    async def callback(self, inter: disnake.ModalInteraction):

        url = inter.text_values["user_fav_url"].strip()

        try:
            valid_url = URL_REG.findall(url)[0]
        except IndexError:
            await inter.send(
                embed=disnake.Embed(
                    description=f"**Nenhum link válido encontrado:** {url}",
                    color=disnake.Color.red()
                ), ephemeral=True
            )
            return

        await inter.response.defer(ephemeral=True)

        self.view.data = await self.view.bot.get_global_data(inter.author.id, db_name=DBModel.users)

        name = inter.text_values["user_fav_name"].strip()

        try:
            if name != self.name:
                del self.view.data["fav_links"][self.name]
        except KeyError:
            pass

        self.view.data["fav_links"][name] = valid_url

        await self.view.bot.update_global_data(inter.author.id, self.view.data, db_name=DBModel.users)

        try:
            me = (inter.guild or self.view.bot.get_guild(inter.guild_id)).me
        except AttributeError:
            me = None

        await inter.edit_original_message(
            embed=disnake.Embed(
                description="**Link salvo/atualizado com sucesso nos seus favoritos!\n"
                            "Ele vai aparecer nas seguintes ocasições:** ```\n"
                            "- Ao usar o comando /play (no preenchimento automático da busca)\n"
                            "- Ao clicar no botão de tocar favorito do player.\n"
                            "- Ao usar o comando play (prefixed) sem nome ou link.```",
                color=self.view.bot.get_color(me)
            )
        )

        if not isinstance(self.view.ctx, CustomContext):
            await self.view.ctx.edit_original_message(embed=self.view.build_embed(), view=self.view)
        elif self.view.message:
            await self.view.message.edit(embed=self.view.build_embed(), view=self.view)

class UserFavView(disnake.ui.View):

    def __init__(self, bot: BotCore, ctx: Union[disnake.AppCmdInter, CustomContext], data: dict, log: str = "", prefix: str = ""):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.current = None
        self.data = data
        self.message = None
        self.log = log
        self.prefix = prefix

        self.update_components()
        self.components_updater_task = bot.loop.create_task(self.auto_update())

    def update_components(self):

        if self.data["fav_links"]:

            fav_select = disnake.ui.Select(options=[
                disnake.SelectOption(label=k, emoji=music_source_emoji_url(v)) for k, v in self.data["fav_links"].items()
            ], min_values=1, max_values=1)
            fav_select.options[0].default = True
            self.current = fav_select.options[0].label
            fav_select.callback = self.select_callback
            self.add_item(fav_select)

        favadd_button = disnake.ui.Button(label="Adicionar", emoji="⭐")
        favadd_button.callback = self.favadd_callback
        self.add_item(favadd_button)

        if self.data["fav_links"]:

            edit_button = disnake.ui.Button(label="Editar", emoji="✍️")
            edit_button.callback = self.edit_callback
            self.add_item(edit_button)

            remove_button = disnake.ui.Button(label="Remover", emoji="♻️")
            remove_button.callback = self.remove_callback
            self.add_item(remove_button)

            clear_button = disnake.ui.Button(label="Limpar favoritos", emoji="🚮")
            clear_button.callback = self.clear_callback
            self.add_item(clear_button)

            export_button = disnake.ui.Button(label="Exportar", emoji="📤")
            export_button.callback = self.export_callback
            self.add_item(export_button)

        import_button = disnake.ui.Button(label="Importar", emoji="📥")
        import_button.callback = self.import_callback
        self.add_item(import_button)

        if self.data["fav_links"]:
            play_button = disnake.ui.Button(label="Tocar o favorito selecionado", emoji="▶")
            play_button.callback = self.play_callback
            self.add_item(play_button)

        cancel_button = disnake.ui.Button(label="Fechar", emoji="❌")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def auto_update(self):

        while True:

            user, data, url = await self.bot.wait_for("fav_add", check=lambda user, data, url: user.id == self.ctx.author.id)

            self.log = f"{url} foi adicionado nos seus favoritos."

            if not isinstance(self.ctx, CustomContext):
                await self.ctx.edit_original_message(embed=self.build_embed(), view=self)
            elif self.message:
                await self.message.edit(embed=self.build_embed(), view=self)

    async def on_timeout(self):

        try:
            self.components_updater_task.cancel()
        except:
            pass

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

    def build_embed(self):

        self.update_components()

        embed = disnake.Embed(
            title="Gerenciador de favoritos.",
            colour=self.bot.get_color(),
        )

        if not self.data["fav_links"]:
            embed.description = "Você não possui favoritos (clique no botão de adicionar abaixo)."

        else:
            embed.description = f"**Seus favoritos atuais:**\n\n" + "\n".join(
                f"> ` {n + 1} ` [`{f[0]}`]({f[1]})" for n, f in enumerate(self.data["fav_links"].items())
            )

        cog = self.bot.get_cog("Music")

        if cog:

            try:
                cmd = f"</play:" + str(self.bot.pool.controller_bot.get_global_command_named("play",
                                                                                             cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"
            except AttributeError:
                cmd = "/play"

            embed.add_field(name="**Como usá-los?**", inline=False,
                            value=f"* Usando o comando {cmd} (no preenchimento automático da busca)\n"
                                  "* Clicando no botão/select de tocar favorito/integração do player.\n"
                                  f"* Usando o comando {self.prefix}{cog.play_legacy.name} sem incluir um nome ou link de uma música/vídeo.\n"
                                  "* Usando o botão de tocar favorito abaixo.")

        if self.log:
            embed.add_field(name="Última interação:", value=self.log)

        return embed

    async def favadd_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(UserFavModal(url="", name="", view=self))

    async def edit_callback(self, inter: disnake.MessageInteraction):

        if not self.current:
            await inter.send("Você deve selecionar um item!", ephemeral=True)
            return

        try:
            await inter.response.send_modal(
                UserFavModal(name=self.current, url=self.data["fav_links"][self.current], view=self)
            )
        except KeyError:
            await inter.send(f"**Não há favorito com o nome:** {self.current}", ephemeral=True)

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
            url = f'[`{self.current}`]({self.data["fav_links"][self.current]})'
            del self.data["fav_links"][self.current]
        except:
            await inter.edit_original_message(f"**Não há favorito na lista com o nome:** {self.current}")
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

        if not self.data["fav_links"]:
            await inter.send("**Você não possui links favoritos!**", ephemeral=True)
            return

        self.data["fav_links"].clear()

        await self.bot.update_global_data(inter.author.id, self.data, db_name=DBModel.users)

        self.log = "Sua lista de favoritos foi limpa com sucesso!"

        await inter.edit_original_message(embed=self.build_embed(), view=self)

    async def import_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(UserFavModalImport(view=self))

    async def play_callback(self, inter: disnake.MessageInteraction):
        await self.bot.get_cog("Music").player_controller(inter, PlayerControls.enqueue_fav, query=f"> fav: {self.current}" )

    async def export_callback(self, inter: disnake.MessageInteraction):
        await self.bot.get_cog("FavManager").export_(inter)

    async def cancel_callback(self, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            embed=disnake.Embed(
                description="**Operação com favoritos cancelada...**",
                color=self.bot.get_color(),
            ), view=None
        )
        try:
            self.components_updater_task.cancel()
        except:
            pass
        self.stop()

    async def select_callback(self, inter: disnake.MessageInteraction):
        self.current = inter.values[0]
        await inter.response.defer()

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:

        if inter.author.id == self.ctx.author.id:
            return True

        await inter.send(f"Apenas o membro {self.ctx.author.mention} pode interagir nessa mensagem.", ephemeral=True)


class FavManager(commands.Cog):

    emoji = "⭐"
    name = "Favoritos"
    desc_prefix = f"[{emoji} {name}] | "

    def __init__(self, bot: BotCore):
        self.bot = bot

    fav_cd = commands.CooldownMapping.from_cooldown(3, 15, commands.BucketType.member)
    fav_mc = commands.MaxConcurrency(1, per=commands.BucketType.member, wait=False)

    @commands.command(name="favmanager", aliases=["favs", "favoritos", "fvmgr", "favlist"],
                      description="Gerenciar suas playlists/favoritos.", cooldown=fav_cd, max_concurrency=fav_mc)
    async def favmanager_legacy(self, ctx: CustomContext):
        await self.fav_manager.callback(self=self, inter=ctx)

    @commands.slash_command(description=f"{desc_prefix}Gerenciar suas playlists/favoritos.", cooldown=fav_cd,
                            dm_permission=False, max_concurrency=fav_mc)
    async def fav_manager(self, inter: disnake.AppCmdInter):

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

        view = UserFavView(bot=self.bot, ctx=inter, data=user_data, prefix=prefix)

        embed = view.build_embed()

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

    fav_import_export_cd = commands.CooldownMapping.from_cooldown(1, 15, commands.BucketType.member)

    async def export_(self, inter: disnake.MessageInteraction):

        retry_after = self.fav_import_export_cd.get_bucket(inter).update_rate_limit()
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
            cmd = f"</{self.fav_manager.name}:" + str(
            self.bot.pool.controller_bot.get_global_command_named(self.fav_manager.name,
                                                                  cmd_type=disnake.ApplicationCommandType.chat_input).id) + ">"
        except AttributeError:
            cmd = "/play"

        if not user_data["fav_links"]:
            await inter.send(f"**Você não possui links favoritos..\n"
                               f"Você pode adicionar usando o comando: {cmd}**", ephemeral=True)
            return

        fp = BytesIO(bytes(json.dumps(user_data["fav_links"], indent=4), 'utf-8'))

        embed = disnake.Embed(
            description=f"Seus favoritos estão aqui.\nVocê pode importar usando o comando: {cmd}",
            color=self.bot.get_color())

        await inter.send(embed=embed, file=disnake.File(fp=fp, filename="favoritos.json"), ephemeral=True)


def setup(bot: BotCore):
    bot.add_cog(FavManager(bot))
