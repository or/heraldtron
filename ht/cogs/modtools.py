import discord, asyncio, typing, re
from discord import ui
from discord.ext import commands
from datetime import datetime
from .. import converters, embeds, utils, views

class ModerationTools(utils.MeldedCog, name = "Moderation", limit = False):
	MAX_FEEDS = 3
	SR_VAL = re.compile("(r\/|\/|r\/)+")
	HAS_MARKDOWN = re.compile(r"<@!?|<#|<&|\*{1,2}\w")
	SHORT_MESSAGE = 200
	
	def __init__(self, bot):
		self.bot = bot
		
	async def cog_check(self, ctx):
		if await ctx.bot.is_owner(ctx.author):
			return True
		elif isinstance(ctx.channel, discord.abc.GuildChannel):
			if self.is_mod(ctx.author.guild_permissions):
				return True	
		else:
			for guild in ctx.author.mutual_guilds:
				perms = guild.get_member(ctx.author.id).guild_permissions
				if self.is_mod(perms): return True
		
		raise commands.MissingRole("admin")
	
	@staticmethod	
	def is_mod(perms):
		return perms.ban_members or perms.administrator
	
	@commands.command(
		help = "Adds a Reddit feed for the given query and channel.\nSearches use Reddit syntax;"
			   " for instance, `flair:novov` gets posts flaired `novov`."
			   " Feeds get the newest 8 posts every 2 hours.", 
		aliases = ("af", "feed")
	)	
	async def addfeed(
		self, ctx, 
		subreddit : str, 
		channel : discord.TextChannel, 
		ping : typing.Optional[bool], 
		search_query : str
	):
		ping = ping or False
		rowcount = await self.bot.dbc.execute_fetchone("SELECT COUNT(*) FROM reddit_feeds")
		
		if rowcount[0] > self.MAX_FEEDS:
			raise utils.CustomCommandError("Excessive feed count", f"A server cannot have more than {self.MAX_FEEDS} feeds.")
		
		subreddit = re.sub(self.SR_VAL, "", subreddit)
		validate = await utils.get_json(self.bot.session, f"https://www.reddit.com/r/{subreddit}/new.json?limit=1")
		
		if validate.get("error"): raise utils.CustomCommandError(
			"Invalid subreddit",
			f"**r/{subreddit}** either does not exist or is inaccessible."
		)
		elif validate["data"]["dist"] > 0:
			newest = validate["data"]["children"][0]["data"]["name"] #json can be a nightmare
		else: newest = None
		
		await self.bot.dbc.execute(
			"INSERT INTO reddit_feeds VALUES (?, ?, ?, ?, ?, ?, ?);",
			(None, (await self.choose_guild(ctx)).id, channel.id, subreddit, int(ping), search_query, newest)
		)
		await self.bot.dbc.commit()
		await ctx.send(":white_check_mark: | Subreddit feed created.")
		
	@commands.command(help = "Creates a new roll channel.", aliases = ("c", "create", "new"))	
	async def channel(self, ctx, user : converters.MemberOrUser, info : converters.RollVariant):
		sorting = self.bot.get_cog("Roll Sorting")
		guild = await self.choose_guild(ctx)
		category = await sorting.get_last_category(guild, info)
		overwrites = { 
			guild.default_role: discord.PermissionOverwrite(send_messages = False),
			user: discord.PermissionOverwrite(manage_channels = True) 
		}
		
		await views.Confirm(ctx, "Create").run(f"Make a new channel for {user.name}#{user.discriminator}?")
		
		channel = await guild.create_text_channel(user.name, category = category, overwrites = overwrites)
		await ctx.send(f":scroll: | {channel.mention} created for {user.mention}.")
	
	@commands.command(
		help = "Shows current Reddit feeds and allows deleting them.", 
		aliases = ("managefeed", "mf", "feeds")
	)	
	async def delfeed(self, ctx):
		guild = await self.choose_guild(ctx)
		query = await self.bot.dbc.execute("SELECT * FROM reddit_feeds WHERE guild = ?", (guild.id,))
		feeds = await query.fetchmany(size = self.MAX_FEEDS)
		
		if len(feeds) == 0: raise utils.CustomCommandError(
			"No feeds to delete",
			"There are currently no active feeds, so none can be deleted."
		)
		
		values = []
		for feed in feeds:
			channel = getattr(await utils.get_channel(self.bot, feed[2]), "name", "invalid")
			values.append(discord.SelectOption(label = f"r/{feed[3]}", description = f"{feed[5]} in #{channel}"))
			
		indice = await views.Chooser(ctx, values, "Delete", discord.ButtonStyle.red).run("Choose a feed to delete:")
		await self.bot.dbc.execute("DELETE FROM reddit_feeds WHERE id = ?;", (feeds[indice][0],))
		
		await self.bot.dbc.commit()
		await ctx.send(":x: | Subreddit feed deleted.")
	
	@commands.command(
		help = "Displays a moderator message in a channel.\n By default, this is"
		" the channel the command is invoked in, but it can be specified beforehand.",
		aliases = ("m",)
	)
	async def modmessage(self, ctx, channel : typing.Optional[discord.TextChannel] = None, *, message_content):
		channel = channel or ctx.channel
		prompt = f"Send a message to this DM? To specify a channel, try again and mention it before your message."
		
		if isinstance(ctx.channel, discord.abc.GuildChannel): 
			prompt = f"Send a message in {channel.mention} of **{channel.guild.name}**?"			
		
		await views.Confirm(ctx, "Create", delete = True).run(prompt)
		
		if len(message_content) < self.SHORT_MESSAGE and not re.search(self.HAS_MARKDOWN, message_content):
			embed = embeds.MOD_MESSAGE.create(message_content, "")
		else:
			embed = embeds.MOD_MESSAGE.create("", message_content)
		
		embed.set_footer(
			text = f"Sent by {ctx.author.display_name} on {(datetime.now()).strftime('%d %B %Y')}",
			icon_url = ctx.author.display_avatar.with_size(256).url
		)

		await channel.send(embed = embed)
	
	@commands.guild_only()
	@commands.command(help = "Locks a channel, disabling the ability to send messages from it.", aliases = ("l",))	
	async def lock(self, ctx, channel : typing.Optional[discord.TextChannel] = None):
		channel = channel or ctx.channel
		
		overwrite = discord.PermissionOverwrite(send_messages = False)
		await channel.set_permissions(ctx.guild.default_role, overwrite = overwrite)
		await ctx.send(f":lock: | **{ctx.channel.mention} has been locked.**")
		
	@commands.command(help = "Enables/disables non-essential commands for this server.", aliases = ("li",))	
	async def limit(self, ctx, enabled : bool):
		await self.set_flag(ctx, enabled, "limit_commands", ":stop_sign:", "Command limits have")
		
	@commands.command(help = "Enables/disables welcome and leave messages for a server.", aliases = ("wl", "welcome", "ms", "message"))	
	async def messages(self, ctx, enabled : bool):
		await self.set_flag(ctx, enabled, "welcome_users", ":envelope_with_arrow:", "Welcome and leave messages have")
	
	@commands.command(help = "Sets the leave message for this server.", aliases = ("sl", "setl"))	
	async def setleave(self, ctx):
		await self.set_message(ctx, True)
		
	@commands.command(help = "Sets the welcome message for this server.", aliases = ("sw", "setw"))	
	async def setwelcome(self, ctx):
		await self.set_message(ctx, False)
		
	@commands.command(help = "Enables/disables roll channel sorting for a server.", aliases = ("arrange", "s"))	
	async def sort(self, ctx, enabled : bool):
		await self.set_flag(ctx, enabled, "sort_channels", ":abcd:", "Roll channel sorting has")
	
	@commands.guild_only()	
	@commands.command(help = "Unlocks a channel, restoring the ability to send messages from it.",aliases=("ul",))	
	async def unlock(self, ctx, channel : discord.TextChannel = None):
		channel = channel or ctx.channel
		
		overwrite = discord.PermissionOverwrite(send_messages = True)
		await channel.set_permissions(ctx.guild.default_role, overwrite = overwrite)
		await ctx.send(f":unlock: | **{ctx.channel.mention} has been unlocked.**")
		
	@staticmethod		
	async def choose_guild(ctx):
		if isinstance(ctx.channel, discord.abc.GuildChannel): return ctx.guild
		
		possible = []
		for guild in ctx.author.mutual_guilds:
			if await ctx.bot.is_owner(ctx.author):
				possible.append(guild)
				continue
			
			perms = guild.get_member(ctx.author.id).guild_permissions
			if perms.manage_guild or perms.administrator:
				possible.append(guild)
				
		if len(possible) == 1: 
			await ctx.send(f"Executing command in **{possible[0].name}**...")
			return possible[0]
		
		choices = tuple(discord.SelectOption(label = a.name) for a in possible)
		indice = await views.Chooser(ctx, choices, "Execute").run(
			"**Multiple servers are available.** Select a server to use the command in:", 
		)		
		return possible[indice]
	
	@staticmethod	
	async def set_flag(ctx, enabled, db_col, emoji, desc):
		guild = await ModerationTools.choose_guild(ctx)
		enabled_int = int(enabled)
		enabled_text = "enabled" if enabled else "disabled"
		 
		await ctx.bot.dbc.execute(f"UPDATE guilds SET {db_col} = ? WHERE discord_id = ?", (enabled_int, guild.id))
		await ctx.bot.dbc.commit()
		await ctx.send(f"{emoji} | {desc} been **{enabled_text}** for this server.")
		
		await ctx.bot.refresh_cache_guild(guild.id)
	
	@staticmethod	
	async def set_message(ctx, leave):
		guild = await ModerationTools.choose_guild(ctx)
		enabled = await ctx.bot.dbc.execute("SELECT welcome_users FROM guilds WHERE discord_id == ?;", (guild.id,))
		
		if enabled == 0: raise utils.CustomCommandError(
			"Welcome and leave messages disabled",
			"Your message cannot be set, as the welcome and leave message functionality"
			f" is currently not operational. Turn it on with `{ctx.clean_prefix}messages yes`."
		)
		
		reset = ui.Button(label = "Reset to default", style = discord.ButtonStyle.secondary)	
		result = await views.RespondOrReact(ctx, additional = (reset,)).run(
			"Type your message below. To add details, include `GUILD_NAME`,"
			" `MENTION`, or `MEMBER_NAME` in the message.",
		)
		
		if result == "Reset to default" or isinstance(result, discord.Message):
			message_type = "welcome_text" if not leave else "leave_text"
			new = None if isinstance(result, str) else result.content
			
			await ctx.bot.dbc.execute(f"UPDATE guilds SET {message_type} = ? WHERE discord_id = ?;", (new, guild.id))
			await ctx.bot.dbc.commit()
			await ctx.send(":white_check_mark: | Message changed.")
		
def setup(bot):
	bot.add_cog(ModerationTools(bot))
