import asyncio
import datetime
import json
import logging
import re

import aiohttp
import discord

from discord.ext import commands
from discord.gateway import DiscordClientWebSocketResponse

log = logging.getLogger(__name__)


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if self.bot.config.testing is False and self.bot.cluster == 1:
            self.stats_updates = bot.loop.create_task(self.stats_updater())
        self.bot_stats_updates = bot.loop.create_task(self.bot_stats_updater())
        self.bot_categories_updates = bot.loop.create_task(self.bot_categories_updater())

    async def stats_updater(self):
        while True:
            guilds = await self.bot.cogs["Communication"].handler("guild_count", self.bot.cluster_count)
            if len(guilds) < self.bot.cluster_count:
                await asyncio.sleep(300)
                continue
            guilds = sum(guilds)
            await self.bot.session.post(
                f"https://top.gg/api/bots/{self.bot.user.id}/stats",
                data=json.dumps({"server_count": guilds, "shard_count": self.bot.shard_count}),
                headers={"Authorization": self.bot.config.topgg_token, "Content-Type": "application/json"},
            )
            await self.bot.session.post(
                f"https://discord.bots.gg/api/v1/bots/{self.bot.user.id}/stats",
                data=json.dumps({"guildCount": guilds, "shardCount": self.bot.shard_count}),
                headers={"Authorization": self.bot.config.dbots_token, "Content-Type": "application/json"},
            )
            await self.bot.session.post(
                f"https://discordbotlist.com/api/v1/bots/{self.bot.user.id}/stats",
                data=json.dumps({"guilds": guilds}),
                headers={"Authorization": self.bot.config.dbl_token, "Content-Type": "application/json"},
            )
            await self.bot.session.post(
                f"https://bots.ondiscord.xyz/bot-api/bots/{self.bot.user.id}/guilds",
                data=json.dumps({"guildCount": guilds}),
                headers={"Authorization": self.bot.config.bod_token, "Content-Type": "application/json"},
            )
            await self.bot.session.post(
                f"https://botsfordiscord.com/api/bot/{self.bot.user.id}",
                data=json.dumps({"server_count": guilds}),
                headers={"Authorization": self.bot.config.bfd_token, "Content-Type": "application/json"},
            )
            await self.bot.session.post(
                f"https://discord.boats/api/v2/bot/{self.bot.user.id}",
                data=json.dumps({"server_count": guilds}),
                headers={"Authorization": self.bot.config.dboats_token, "Content-Type": "application/json"},
            )
            await asyncio.sleep(900)

    async def bot_stats_updater(self):
        while True:
            async with self.bot.pool.acquire() as conn:
                res = await conn.fetch("SELECT identifier, category FROM ban")
                res2 = await conn.fetch("SELECT identifier, expiry FROM premium WHERE expiry IS NOT NULL")
            self.banned_users = []
            self.banned_guilds = []
            for row in res:
                if row[1] == 0:
                    self.banned_users.append(row[0])
                elif row[1] == 1:
                    self.banned_guilds.append(row[0])
            if self.bot.cluster == 1:
                timestamp = int(datetime.datetime.utcnow().timestamp() * 1000)
                for row in res2:
                    if row[1] < timestamp:
                        await self.bot.tools.wipe_premium(self.bot, row[0])
            await asyncio.sleep(60)

    async def bot_categories_updater(self):
        while True:
            async with self.bot.pool.acquire() as conn:
                data = await conn.fetch("SELECT category FROM data")
            categories = []
            for row in data:
                categories.append(row[0])
            self.bot.all_category = categories
            await asyncio.sleep(5)

    async def on_http_request_start(self, session, trace_config_ctx, params):
        trace_config_ctx.start = asyncio.get_event_loop().time()

    async def on_http_request_end(self, session, trace_config_ctx, params):
        elapsed = asyncio.get_event_loop().time() - trace_config_ctx.start
        if elapsed > 0.5:
            log.info(f"{params.method} {params.url} took {elapsed} seconds")
        route = str(params.url)
        route = re.sub(r"https:\/\/[a-z\.]+\/api\/v[0-9]+", "", route)
        route = re.sub(r"\/[%A-Z0-9]+", "/_id", route)
        route = re.sub(r"\?.+", "", route)
        status = str(params.response.status)
        if not route.startswith("/"):
            return
        await self.bot.prom.inc("http", method=params.method, route=route, status=status)

    @commands.Cog.listener()
    async def on_ready(self):
        log.info(f"{self.bot.user.name}#{self.bot.user.discriminator} is online!")
        log.info("--------")
        trace_config = aiohttp.TraceConfig()
        trace_config.on_request_start.append(self.on_http_request_start)
        trace_config.on_request_end.append(self.on_http_request_end)
        self.bot.http._HTTPClient__session = aiohttp.ClientSession(
            connector=self.bot.http.connector,
            ws_response_class=DiscordClientWebSocketResponse,
            trace_configs=[trace_config],
        )
        embed = discord.Embed(
            title=f"[Cluster {self.bot.cluster}] Bot Ready",
            colour=0x00FF00,
            timestamp=datetime.datetime.utcnow(),
        )
        await self.bot.http.send_message(self.bot.config.event_channel, None, embed=embed.to_dict())
        await self.bot.change_presence(activity=discord.Game(name=self.bot.config.activity))

    @commands.Cog.listener()
    async def on_shard_ready(self, shard):
        try:
            embed = discord.Embed(
                title=f"[Cluster {self.bot.cluster}] Shard {shard} Ready",
                colour=0x00FF00,
                timestamp=datetime.datetime.utcnow(),
            )
            await self.bot.http.send_message(self.bot.config.event_channel, None, embed=embed.to_dict())
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_shard_connect(self, shard):
        await self.bot.prom.inc("events", type="CONNECT")
        try:
            embed = discord.Embed(
                title=f"[Cluster {self.bot.cluster}] Shard {shard} Connected",
                colour=0x00FF00,
                timestamp=datetime.datetime.utcnow(),
            )
            await self.bot.http.send_message(self.bot.config.event_channel, None, embed=embed.to_dict())
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_shard_disconnect(self, shard):
        await self.bot.prom.inc("events", type="DISCONNECT")
        try:
            embed = discord.Embed(
                title=f"[Cluster {self.bot.cluster}] Shard {shard} Disconnected",
                colour=0xFF0000,
                timestamp=datetime.datetime.utcnow(),
            )
            await self.bot.http.send_message(self.bot.config.event_channel, None, embed=embed.to_dict())
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_shard_resumed(self, shard):
        await self.bot.prom.inc("events", type="RESUME")
        try:
            embed = discord.Embed(
                title=f"[Cluster {self.bot.cluster}] Shard {shard} Resumed",
                colour=self.bot.config.primary_colour,
                timestamp=datetime.datetime.utcnow(),
            )
            await self.bot.http.send_message(self.bot.config.event_channel, None, embed=embed.to_dict())
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.bot.prom.inc("guilds_join")
        embed = discord.Embed(
            title="Server Join",
            description=f"{guild.name} ({guild.id})",
            colour=0x00FF00,
            timestamp=datetime.datetime.utcnow(),
        )
        guilds = sum(await self.bot.cogs["Communication"].handler("guild_count", self.bot.cluster_count))
        embed.set_footer(text=f"{guilds} servers")
        await self.bot.http.send_message(self.bot.config.join_channel, None, embed=embed.to_dict())
        if guild.id in self.bot.banned_guilds:
            await guild.leave()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self.bot.prom.inc("guilds_leave")
        async with self.bot.pool.acquire() as conn:
            await conn.execute("DELETE FROM data WHERE guild=$1", guild.id)
        embed = discord.Embed(
            title="Server Leave",
            description=f"{guild.name} ({guild.id})",
            colour=0xFF0000,
            timestamp=datetime.datetime.utcnow(),
        )
        guilds = sum(await self.bot.cogs["Communication"].handler("guild_count", self.bot.cluster_count))
        embed.set_footer(text=f"{guilds} servers")
        await self.bot.http.send_message(self.bot.config.join_channel, None, embed=embed.to_dict())

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        ctx = await self.bot.get_context(message)
        if not ctx.command:
            return
        await self.bot.prom.inc("commands", name=ctx.command.name)
        if message.guild:
            if message.guild.id in self.bot.banned_guilds:
                await message.guild.leave()
                return
            permissions = message.channel.permissions_for(message.guild.me)
            if permissions.send_messages is False:
                return
            elif permissions.embed_links is False:
                await message.channel.send("The Embed Links permission is needed for basic commands to work.")
                return
        if message.author.id in self.bot.banned_users:
            await ctx.send(
                embed=discord.Embed(description="You are banned from this bot.", colour=self.bot.error_colour)
            )
            return
        if ctx.command.cog_name in ["Owner", "Admin"] and (
            ctx.author.id in self.bot.config.admins or ctx.author.id in self.bot.config.owners
        ):
            embed = discord.Embed(
                title=ctx.command.name.title(),
                description=ctx.message.content,
                colour=self.bot.primary_colour,
                timestamp=datetime.datetime.utcnow(),
            )
            embed.set_author(
                name=f"{ctx.author.name}#{ctx.author.discriminator} ({ctx.author.id})", icon_url=ctx.author.avatar_url
            )
            await self.bot.http.send_message(self.bot.config.admin_channel, None, embed=embed.to_dict())
        if ctx.prefix == f"<@{self.bot.user.id}> " or ctx.prefix == f"<@!{self.bot.user.id}> ":
            ctx.prefix = self.bot.tools.get_guild_prefix(self.bot, message.guild)
        await self.bot.invoke(ctx)

    @commands.Cog.listener()
    async def on_socket_response(self, message):
        if message.get("op") == 0:
            t = message.get("t")
            if not t == "PRESENCE_UPDATE":
                await self.bot.prom.inc("dispatch", type=message.get("t"))


def setup(bot):
    bot.add_cog(Events(bot))
