"""
A listener that looks for repeat messages and destroys them.
"""
import logging
from datetime import datetime, timedelta

import discord.errors
from discord.ext import commands

from zorak.utilities.cog_helpers._embeds import (
	embed_spammer,  # pylint: disable=E0401
	embed_spammer_warn  # pylint: disable=E0401
)

from zorak.utilities.core.redis import RDB # This singular files connection to redis, as the RDB variable is created on-import

logger = logging.getLogger(__name__)

ANTISPAM_COUNTER_TIMER = 12 # How long it takes the key to expire, AKA; reset all data for a users key in redis.
ANTISPAM_COUNTER_LIMIT = 3 # How many messages with the same content it takes to trigger
ANTISPAM_OCCURANCE_WARN_LIMIT = 2 # How many messages with the same content it takes to trigger a warning
ANTISPAM_OCCURANCE_LIMIT = 3 # How many times they have to trigger the antispam for it to finally take action 
ANTISPAM_COUNTER_HISTORY_LIMIT = 10 # How many messages to go back and check for repeated messages

ANTISPAM_COUNTER_KEY = "zorak:antispam:counter" # The key for the counter
ANTISPAM_CACHE_KEY = "zorak:antispam:cache" # The key for the cache

def find_most_common(lst):
	return max(set(lst), key=lst.count)

def get_cache(user: int) -> int:
	"""Gets the cache for a user ID

	Args:
		user (int): User ID.

	Returns:
		int: IDs of messages in the antispam cache.
	"""    
	return RDB.get(f"{ANTISPAM_CACHE_KEY}:{user}") or None # Default to 0 if the user is not being watched.

def add_to_cache(user: int, message_id: int) -> None:
	"""Adds to the cache for a user ID

	Args:
		user (int): User ID.
		message_id (int): Message ID to add to the cache.

	Returns:
		None
	"""
	key = f"{ANTISPAM_CACHE_KEY}:{user}"
	current = RDB.get(key)
	if not current or current == None:
		current = []
	current.append(message_id)
	RDB.set(key, current, ANTISPAM_COUNTER_TIMER)
	return None


def get_counter(user: int) -> int:
	"""Gets the message count for a user ID

	Args:
		user (int): User ID.

	Returns:
		int: The number of messages that they have sent in the allowed range of seconds.
	"""    
	return RDB.get(f"{ANTISPAM_COUNTER_KEY}:{user}") or 0 # Default to 0 if the user is not being watched.

def add_counter(user: int) -> int:
	"""Adds to antispam counter.

	Args:
		user (int): User ID.

	Returns:
		int: The new count.
	"""    
	key = f"{ANTISPAM_COUNTER_KEY}:{user}"
	current = RDB.get(key)
	if current == None:
		RDB.set(key, 1, ANTISPAM_COUNTER_TIMER)
		return 1
	current = int(current) + 1
	RDB.set(key, current, keepttl=True)
	return current

def remove_from_antispam(user: int) -> None:
	"""Clears a user from the antispam in redis.

	Args:
		user (int): User ID.

	Returns:
		None
	"""    
	RDB.delete(f"{ANTISPAM_COUNTER_KEY}:{user}")
	RDB.delete(f"{ANTISPAM_CACHE_KEY}:{user}")

class ModerationSpamMessages(commands.Cog):
	"""
	Destroying spam with bots
	"""

	def __init__(self, bot):
		self.bot = bot
		self.warn_message = 'Hello there!'

	@commands.Cog.listener()
	async def on_message(self, message):
		"""
		Scans every message and compares them
		"""

		# Dont catch Zorak
		if message.author.bot:
			return
		# Dont care about DM channels
		if isinstance(message.channel, discord.DMChannel):
			return
		member = message.author
		channel = message.channel

		temp = []
		async for message in message.channel.history(limit=ANTISPAM_COUNTER_HISTORY_LIMIT):
			if message.author.id == member.id:
				temp.append(message.content.lower())
		most_common = find_most_common(temp)
		del temp
		occurances = temp.count(most_common)
		if occurances > ANTISPAM_COUNTER_LIMIT: # if repeating messages sent > limit: add to counter
			add_counter(member.id)
			logger.debug("%s has sent a double message in %s", message.author.name, message.channel.name)

		counter = get_counter(member.id)

		if counter == ANTISPAM_OCCURANCE_WARN_LIMIT: # if spam occurances > limit: take action

			await message.author.timeout(until=datetime.utcnow() + timedelta(seconds=15))
			logger.info("%s was timed out (2/3 messages)", message.author.name)
			# Send a DM. If you can't, send in the channel.
			try:
				await message.author.send(embed=embed_spammer_warn(channel.id))
				logger.debug("%s was sent a DM about their double message.", message.author.name)
			except discord.errors.HTTPException as closed_dms:
				logger.debug("could not send %s a message, diverting to channel: %s"
								, message.author.name
								, message.channel.name)

				first_channel = await self.bot.fetch_channel(channel.id)
				self.warn_message = await message.reply(
					f"{message.author.mention}, Please do not post the same message in "
					f"multiple channels.\n You already posted this in {first_channel.mention}")

		elif counter >= ANTISPAM_OCCURANCE_LIMIT: # You lost the game, asshole.
			logger.info("%s was quarantined for sending 3 repeat messages.", message.author.name)
			# timeout right away
			await message.author.timeout(until=datetime.utcnow() + timedelta(seconds=30))

			naughty = message.author.guild.get_role(self.bot.server_settings.user_roles["bad"]["naughty"])
			verified = message.author.guild.get_role(self.bot.server_settings.verified_role['verified'])
			quarantine = await self.bot.fetch_channel(
				self.bot.server_settings.channels["moderation"]["quarantine_channel"])

			# assign Naughty roll
			member = message.author
			await member.remove_roles(verified)
			await member.add_roles(naughty)

			# Post the message in Quarantine channel
			await quarantine.send(embed=embed_spammer(message.content))

			# delete the messages
			channel = await self.bot.fetch_channel(channel.id)
			to_delete = get_cache(member.id)
			for message_id in to_delete:
				message = await channel.fetch_message(message_id)
				await message.delete()
			await self.warn_message.delete()

			remove_from_antispam(member.id)

def setup(bot):
	"""
	Required.
	"""
	bot.add_cog(ModerationSpamMessages(bot))
