import discord, urllib, time, re, random, os
from docx2python import docx2python
from datetime import datetime, timezone
from discord.ext import commands, tasks
from .. import utils, embeds

class BotTasks(commands.Cog, name = "Bot tasks"):
	STRIP_SPACES = re.compile(r"\n[\t\s]+")
	FIND_DATA = re.compile(r"GreiiN:(\d+) - (?:[^\n\r#]+\n)?(.+)#(\d+)[\s\S]+?(Blazon[\s\S]+?)(?=GreiiN|$)")

	STATUSES = (
		discord.Game("a !challenge"),
		discord.Game("with a !resource"),
		discord.Game("with !drawshield"),
		discord.Game("with fire"),
		discord.Game("cards"),
		discord.Game("bingo"),
		discord.Game("canasta"),
		discord.Game("Monopoly"),
		discord.Activity(type = discord.ActivityType.listening, name="for !help"),
		discord.Activity(type = discord.ActivityType.listening, name="a !motto"),
		discord.Activity(type = discord.ActivityType.listening, name="the sounds of nature"),
		discord.Activity(type = discord.ActivityType.watching, name="an !armiger"),
		discord.Activity(type = discord.ActivityType.watching, name="heraldic documentaries"),
		discord.Activity(type = discord.ActivityType.watching, name="Manos: The Hands of Fate"),
		discord.Activity(type = discord.ActivityType.watching, name="Puparia"),
		discord.Activity(type = discord.ActivityType.competing, name="a !trivia game")
	)

	def __init__(self, bot):
		self.bot = bot
		self.update_info.start()
		self.sync_book.start()

		if not os.path.isdir("data/book"):
			os.mkdir("data/book")

	def cog_unload(self):
		self.update_info.stop()
		self.sync_book.stop()

	@tasks.loop(hours = 12)
	async def update_info(self):
		now = datetime.now().date()
		last = await self.bot.dbc.store_get("last_avatar")

		if now.month == 6 and now.day in range(8, 12):
			await self.update_avatar(self.bot, "media/avatars/ihd.jpg", last)
			await self.bot.change_presence(activity = discord.Game("\U0001F6E1\uFE0F International Heraldry Day"))

		elif now.month == 6:
			await self.update_avatar(self.bot, "media/avatars/pride.jpg", last)
			await self.bot.change_presence(activity = discord.Game("\U0001F3F3\uFE0F\u200D\U0001F308 Happy Pride Month!"))

		elif now.month == 12:
			await self.update_avatar(self.bot, "media/avatars/holiday.jpg", last)
			await self.bot.change_presence(activity = discord.Game("\U0001F384 Happy Holidays!"))

		elif now.month == 4:
			await self.update_avatar(self.bot, "media/avatars/easter.jpg", last)
			await self.bot.change_presence(activity = discord.Game("\U0001F414 Happy Easter!"))

		elif (now.month == 2 and now.day in range(8, 12)) or (now.month == 11 and now.day in range(12, 22)):
			await self.update_avatar(self.bot, "media/avatars/trans.jpg", last)
			await self.bot.change_presence(activity = discord.Game("\U0001F3F3\uFE0F\u200D\u26A7\uFE0F Trans Rights!"))

		else:
			await self.update_avatar(self.bot, "media/avatars/generic.jpg", last)
			await self.bot.change_presence(activity = random.choice(BotTasks.STATUSES))

	@staticmethod
	async def update_avatar(bot, path, last):
		if last == path: return

		with open(path, "rb") as image:
			data = bytearray(image.read())

		await bot.user.edit(avatar = data)
		await bot.dbc.store_set("last_avatar", path)

	def write_book(self, doc):
		#don't judge me, I didn't make the choice to store the info in a Word doc
		with open("data/book/book.docx", "wb") as file:
			file.seek(0)
			file.write(doc.getvalue())
			file.truncate()

		text = re.sub(self.STRIP_SPACES, "\n", docx2python("data/book/book.docx").text)
		results = re.findall(self.FIND_DATA, text[text.find("This document contains"):])
		return { entry[0]: entry for entry in results }

	@tasks.loop(hours = 10)
	async def sync_book(self):
		response = await utils.get_json(
			self.bot.session,
			f"https://www.googleapis.com/drive/v3/files/1RyuY_WM4zSRtVhTwjs9lut9vrlMmmd24?"
			f"fields=modifiedTime%2C%20webContentLink&key={self.bot.conf['GCS_TOKEN']}"
		)
		timestamp = time.mktime(datetime.fromisoformat(response["modifiedTime"].rsplit(".")[0]).timetuple())

		if timestamp <= int(await self.bot.dbc.store_get("book_timestamp")):
			return

		doc = await utils.get_bytes(self.bot.session, response["webContentLink"])
		book = await self.bot.loop.run_in_executor(None, self.write_book, doc)

		await self.bot.dbc.execute(
			f"DELETE FROM armigers WHERE greii_n NOT IN ({','.join(['?'] * len(book))})",
			tuple(book.keys())
		)
		await self.bot.dbc.commit()

		for greii_n, entry in book.items():
			await self.bot.dbc.execute(
				"INSERT INTO armigers (greii_n, qualified_name, qualified_id, blazon) VALUES"
				" (?1, ?2, ?3, ?4) ON CONFLICT(greii_n) DO UPDATE SET qualified_name = ?2, qualified_id = ?3, blazon = ?4;",
				(greii_n, entry[1], entry[2], entry[3])
			)

			if await self.bot.dbc.execute(
				"SELECT * FROM armigers WHERE discord_id IS NULL AND greii_n IS ?", (greii_n,)
			):
				user = await utils.unqualify_name(self.bot, entry[1], entry[2])

				if user:
					await self.bot.dbc.execute(
						"UPDATE armigers SET discord_id = ?1 WHERE greii_n = ?2;",
						(user.id, greii_n)
					)

			await self.bot.dbc.commit()

		await self.bot.dbc.store_set("book_timestamp", f"{timestamp:.0f}")
		self.bot.logger.info(f"Successfully refreshed armiger database.")

	@update_info.before_loop
	@sync_book.before_loop
	async def wait_before_loop(self):
		await self.bot.wait_until_ready()

def setup(bot):
	bot.add_cog(BotTasks(bot))
