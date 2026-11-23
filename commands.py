import asyncio
import psutil
import time
import os
import random
import aiohttp
import re
import unicodedata
from datetime import datetime, timezone	
from dateutil.relativedelta import relativedelta
from database_manager import *
from chat import *
from vod import *
from config import BOT_USER_ID, OBS_HOST, OBS_PORT, OBS_PASSWORD, OBS_VIDEO_SOURCE, OBS_DELAY_FILTER, TRUSTED_USERS
from config import COMMAND_PREFIX, CONTROL_FILE, CLIENT_ID, BROADCASTER_ID_247
from twitch_api import *
from logger import logger

# Wide Spread Bot Crash Prevention
def safe_command(func):
	async def wrapper(*args, **kwargs):
		try:
			return await func(*args, **kwargs)
		except Exception as e:
			logger.error(f"[{func.__name__}] {e}")
	return wrapper

# Helpers
BLOCKED_PREFIXES = {"/", "."}

async def reply(broadcaster_id, message, app_access_token, message_id=None):
	await send_message(broadcaster_id, BOT_USER_ID, message, app_access_token, reply_message_id=message_id)

def format_uptime(td):
	total_seconds = int(td.total_seconds())
	days, remainder = divmod(total_seconds, 86400)
	hours, remainder = divmod(remainder, 3600)
	minutes, seconds = divmod(remainder, 60)
	parts = []

	if days:
		parts.append(f"{days}d")
	if hours:
		parts.append(f"{hours}h")
	if minutes:
		parts.append(f"{minutes}m")
	parts.append(f"{seconds}s")
	return " ".join(parts)

def format_watchtime(live_seconds):
	hours, remainder = divmod(live_seconds, 3600)
	minutes, seconds = divmod(remainder, 60)
	return f"{hours}h {minutes}m {seconds}s"

def time_ago(timestamp):
	msg_time = datetime.fromisoformat(
		timestamp.replace("Z", "+00:00")
	)
	now = datetime.now(timezone.utc)

	if msg_time > now:
		return "in the future"

	delta = relativedelta(now, msg_time)

	parts = []

	for value, unit in [
		(delta.years, "year"),
		(delta.months, "month"),
		(delta.days, "day"),
		(delta.hours, "hr"),
		(delta.minutes, "min"),
		(delta.seconds, "sec"),
	]:
		if value:
			parts.append(f"{value} {unit}{'s' if value != 1 else ''}")

		# Show at most the two largest nonzero units
		if len(parts) == 2:
			break

	return f"{' '.join(parts)} ago" if parts else "just now"

def format_date(date):
	dt = datetime.fromisoformat(date.replace("Z", "+00:00"))

	return dt.strftime("%B %d, %Y")

def clean_login(s):
	return re.sub(r"[^a-z0-9_]", "", s.lstrip("@").lower())


# Templates
async def var_watchtime(broadcaster_id, user_id, username, parts, app_access_token):
	row = await get_live_time(user_id, broadcaster_id)
	if not row:
		return "0h 0m 0s"
	return format_watchtime(row["live_seconds"])

async def var_offlineWatchTime(broadcaster_id, user_id, username, parts, app_access_token):
	row = await get_offline_time(user_id, broadcaster_id)
	if not row:
		return "0h 0m 0s"
	return format_watchtime(row["offline_seconds"])

async def var_username(broadcaster_id, user_id, username, parts, app_access_token):
	return username

async def var_touser(broadcaster_id, user_id, username, parts, app_access_token):
	if len(parts) > 1:
		return parts[1].lstrip("@")
	return "someone"

async def var_random_number(broadcaster_id, user_id, username, parts, app_access_token):
	return str(random.randint(1, 100))

async def var_viewer_count(broadcaster_id, user_id, username, parts, app_access_token):
	info = await asyncio.to_thread(get_stream_info, broadcaster_id, app_access_token)
	if info == -1:
		return "Channel is offline"

	return str(info[0]["viewer_count"])

async def var_game(broadcaster_id, user_id, username, parts, app_access_token):
	info = get_offline_info(broadcaster_id, app_access_token)
	if info == -1:
		return "Channel is offline"
	
	return info[0]["game_name"]

async def var_title(broadcaster_id, user_id, username, parts, app_access_token):
	info = get_offline_info(broadcaster_id, app_access_token)
	if info == -1:
		return "Channel is offline"
	return info[0]["title"]

async def var_first_line(broadcaster_id, user_id, username, parts, app_access_token):
	row = await get_first_line(broadcaster_id, user_id)
	if not row:
		return "No messages found"
	sent_at = row["sent_at"].strftime("%B %d, %Y")
	return f"{row['message']} (send on {sent_at})"

async def var_random_quote(broadcaster_id, user_id, username, parts, app_access_token):
	if await check_opt_out(user_id, "randomquote"):
		return "User is opt out"
	
	try:
		data = await get_random_quote(broadcaster_id, user_id)

		if not data:
			return "No messages found"

		for msg in data["messages"]:
			return msg["text"]

	except (aiohttp.ClientError, TimeoutError, ValueError) as e:
		logger.error(f"Error retrieving random message: {e}")
		return "Unable to retrieve a message"

async def var_cpu(broadcaster_id, user_id, username, parts, app_access_token):
	return f"{await asyncio.to_thread(psutil.cpu_percent, 0.5)}%"

async def var_ram(broadcaster_id, user_id, username, parts, app_access_token):
	ram = psutil.virtual_memory()
	ram_used = ram.used / (1024 ** 3)
	ram_total = ram.total / (1024 ** 3)
	return f"{ram_used:.1f}/{ram_total:.1f}GB ({ram.percent}%)"

async def var_latency(broadcaster_id, user_id, username, parts, app_access_token, latency_ms=0):
	return f"{latency_ms:.1f}"

# map variable names to functions
DYNAMIC_VARIABLES = {
	"{watchtime}":      var_watchtime,
	"{username}":       var_username,
	"{touser}":         var_touser,
	"{random_number}":  var_random_number,
	"{viewers}":        var_viewer_count,
	"{game}":           var_game,
	"{title}":          var_title,
	"{first_line}":  	var_first_line,
	"{random_quote}": 	var_random_quote,
	"{cpu}":            var_cpu,
	"{ram}":            var_ram,
	"{latency}":		var_latency,
	"{offlinewatchtime}": var_offlineWatchTime
}

async def resolve_template(response, broadcaster_id, user_id, username, parts, app_access_token, latency_ms):
	for variable, func in DYNAMIC_VARIABLES.items():
		if variable in response:
			if variable == "{latency}":
				value = await func(broadcaster_id, user_id, username, parts, app_access_token, latency_ms)
			else:
				value = await func(broadcaster_id, user_id, username, parts, app_access_token)
			response = response.replace(variable, str(value))
	return response

# Static
@safe_command
async def handle_static(response, broadcaster_id, user_id, username, parts, app_access_token, message_id=None, latency_ms=0):
	try:
		resolved = await resolve_template(response, broadcaster_id, user_id, username, parts, app_access_token, latency_ms)
		await reply(broadcaster_id, resolved, app_access_token, message_id)
	except Exception as e:
		logger.error(f"[Static] Error: {e}")
		import traceback
		traceback.print_exc()


# Stream Controls
@safe_command
async def handle_skip(broadcaster_id, app_access_token, message_id=None):
	try:
		with open(CONTROL_FILE, "w") as f:
			f.write("SKIP")
		await reply(broadcaster_id, "Skipping current video.", app_access_token, message_id)
	except Exception as e:
		await reply(broadcaster_id, "Error skipping video", app_access_token, message_id)

@safe_command
async def handle_restart_stream(broadcaster_id, app_access_token, message_id=None):
	try:
		with open(CONTROL_FILE, "w") as f:
			f.write("RESTART")
		await reply(broadcaster_id, "Manually restarting stream.", app_access_token, message_id)
	except Exception as e:
		await reply(broadcaster_id, "Error restarting stream.", app_access_token, message_id)

# Mod actions
@safe_command
async def handle_timeout(broadcaster_id, parts, is_mod, app_access_token, message_id=None, prefix='$'):
	if not is_mod:
		return

	target = clean_login(parts[1]) if len(parts) > 1 else ""
	if not target:
		await reply(broadcaster_id, f"Usage: {prefix}timeout <username> [seconds]", app_access_token, message_id)
		return

	duration = 1
	if len(parts) > 2:
		try:
			duration = int(parts[2])
		except ValueError:
			await reply(broadcaster_id, f"Usage: {prefix}timeout <username> [seconds]", app_access_token, message_id)
			return
	if not 1 <= duration <= 1209600:  # Twitch max is 2 weeks
		await reply(broadcaster_id, "Duration must be between 1 and 1209600 seconds.", app_access_token, message_id)
		return

	target_id = await asyncio.to_thread(get_user_id, target, app_access_token)
	if not target_id:
		await reply(broadcaster_id, f"Could not find user {target}.", app_access_token, message_id)
		return
	if target_id == broadcaster_id or target_id == BOT_USER_ID:
		return

	b = await get_broadcaster(broadcaster_id)
	headers = {
		"Client-ID": CLIENT_ID,
		"Authorization": f"Bearer {b['user_access_token']}",
		"Content-Type": "application/json"
	}
	payload = {"data": {"user_id": target_id, "duration": duration}}
	params = {"broadcaster_id": broadcaster_id, "moderator_id": broadcaster_id}

	async with aiohttp.ClientSession() as session:
		async with session.post("https://api.twitch.tv/helix/moderation/bans",
								headers=headers, json=payload, params=params) as resp:
			if resp.status == 200:
				await reply(broadcaster_id, f"{target} timed out for {duration} seconds.", app_access_token, message_id)
			else:
				logger.error(f"[timeout] {resp.status} {await resp.text()}")
				await reply(broadcaster_id, f"Failed to timeout {target}.", app_access_token, message_id)
				
@safe_command
async def handle_ban(broadcaster_id, parts, is_mod, app_access_token, message_id=None, prefix='$'):
	if not is_mod:
		return

	target = clean_login(parts[1]) if len(parts) > 1 else ""
	if not target:
		await reply(broadcaster_id, f"Usage: {prefix}ban <username> [reason]", app_access_token, message_id)
		return

	target_id = await asyncio.to_thread(get_user_id, target, app_access_token)
	if not target_id:
		await reply(broadcaster_id, f"Could not find user {target}.", app_access_token, message_id)
		return
	if target_id == broadcaster_id or target_id == BOT_USER_ID:
		return

	reason = " ".join(parts[2:]) if len(parts) > 2 else "No reason provided"

	b = await get_broadcaster(broadcaster_id)
	headers = {
		"Client-ID": CLIENT_ID,
		"Authorization": f"Bearer {b['user_access_token']}",
		"Content-Type": "application/json"
	}
	payload = {"data": {"user_id": target_id, "reason": reason}}
	params = {"broadcaster_id": broadcaster_id, "moderator_id": broadcaster_id}

	async with aiohttp.ClientSession() as session:
		async with session.post("https://api.twitch.tv/helix/moderation/bans",
								headers=headers, json=payload, params=params) as resp:
			if resp.status == 200:
				await reply(broadcaster_id, f"{target} has been banned.", app_access_token, message_id)
			else:
				logger.error(f"[ban] {resp.status} {await resp.text()}")
				await reply(broadcaster_id, f"Failed to ban {target}.", app_access_token, message_id)

@safe_command
async def handle_create_poll(broadcaster_id, parts, is_mod, app_access_token, message_id=None, prefix='$'):
	if not is_mod:
		return
	if len(parts) < 2:
		await reply(broadcaster_id, f"Usage: {prefix}createpoll <duration> <title> | <choice1> | <choice2>", app_access_token, message_id)
		return
	try:
		duration = int(parts[1])
		rest= " ".join(parts[2:])
		segments = [s.strip() for s in rest.split("|")]
		title = segments[0]
		choices = [{"title": c} for c in segments[1:]]
		if len(choices) < 2:
			await reply(broadcaster_id, "Need at least 2 choices.", app_access_token, message_id)
			return
		url = "https://api.twitch.tv/helix/polls"
		headers = {
			"Client-ID": CLIENT_ID,
			"Authorization": f"Bearer {app_access_token}",
			"Content-Type": "application/json"
		}
		payload = {
			"broadcaster_id": broadcaster_id,
			"title": title,
			"choices": choices,
			"duration": duration
		}

		async with aiohttp.ClientSession() as session:
			async with session.post(url, headers=headers, json=payload) as resp:
				if resp.status == 200:
					await reply(broadcaster_id, f"Poll created: {title}", app_access_token, message_id)
				else:
					text = await resp.text()
					await reply(broadcaster_id, f"Failed to create poll: {title}", app_access_token, message_id)
	except Exception as e:
		await reply(broadcaster_id, "Error creating poll.", app_access_token, message_id)

# Command Management
@safe_command
async def handle_addcom(broadcaster_id, parts, app_access_token, message_id=None, prefix='$'):
	if len(parts) < 4:
		await reply(broadcaster_id, f"Usage: {prefix}addcom <command> <permission> <response>", app_access_token, message_id)
		return

	command_name = parts[1].lower()
	permission = parts[2].lower()
	if permission not in ["everyone", "vip", "moderator", "broadcaster", "trusted"]:
		await reply(broadcaster_id, "Permission not in listed permission options.", app_access_token, message_id)
		return
	response = " ".join(parts[3:])
	await add_command(broadcaster_id, command_name, response, permission)
	await reply(broadcaster_id, f"Command: {command_name} added successfully.", app_access_token, message_id)

@safe_command
async def handle_editcom(broadcaster_id, parts, app_access_token, message_id=None, prefix='$', modified_by=None):
	if len(parts) < 3:
		await reply(broadcaster_id, f"Usage: {prefix}editcom <command> <new response>", app_access_token, message_id)
		return

	command_name = parts[1].lower()
	new_response = " ".join(parts[2:])
	
	success = await edit_command(broadcaster_id, command_name, new_response)
	if success:
		await reply(broadcaster_id, f"Command: {command_name} has been updated.", app_access_token, message_id)
	else:
		await reply(broadcaster_id, f"Command: {command_name} not found.", app_access_token, message_id)

@safe_command
async def handle_delcom(broadcaster_id, parts, app_access_token, message_id=None, prefix='$'):
	if len(parts) < 3:
		await reply(broadcaster_id, f"Usage: {prefix}delcom <command>", app_access_token, message_id)
		return
	
	command_name = parts[1].lower()
	success = await delete_command(broadcaster_id, command_name)
	if success:
		await reply(broadcaster_id, f"Command: {command_name} successfully deleted.", app_access_token, message_id)
	else:
		await reply(broadcaster_id, f"Command: {command_name} not found.", app_access_token, message_id)

@safe_command
async def handle_editperms(broadcaster_id, parts, app_access_token, message_id=None, prefix='$'):
	if len(parts) < 3:
		await reply(broadcaster_id, f"Usage: {prefix}editperm <command> <permission>", app_access_token, message_id)
		return
	command_name = parts[1].lower()
	new_permission = parts[2].lower()
	if new_permission not in ["everyone", "vip", "moderator", "broadcaster", "trusted"]:
		await reply(broadcaster_id, "Permission not in listed permission options.", app_access_token, message_id)
		return
	success = await edit_command_permission(broadcaster_id, command_name, new_permission)
	if success:
		await reply(broadcaster_id, f"Permission for {command_name} updated to {new_permission}", app_access_token, message_id)
	else:
		await reply(broadcaster_id, f"Command: {command_name} not found.", app_access_token, message_id)

@safe_command
async def handle_commands_list(broadcaster_id, app_access_token, message_id=None, prefix='$'):
	commands = await get_all_commands(broadcaster_id)
	if not commands:
		await reply(broadcaster_id, "No commands found.", app_access_token, message_id)
		return
	
	command_list = " | ".join([f"{c['command_name']}" for c in commands])
	await reply(broadcaster_id, f"Commands: {command_list}", app_access_token, message_id)

@safe_command
async def handle_set_prefix(broadcaster_id, parts, is_mod, app_access_token, message_id=None, prefix='$'):
	if not is_mod:
		return

	if len(parts) < 2:
		await reply(broadcaster_id, f"Usage: {prefix}setprefix <prefix> (single character symbol)", app_access_token, message_id)
		return

	new_prefix = parts[1]

	if len(new_prefix) != 1:
		await reply(broadcaster_id, "Prefix must be 1 character.", app_access_token, message_id)
		return

	# reject whitespace, control/format chars, and combining marks (e.g. U+034F)
	if new_prefix.isspace() or unicodedata.category(new_prefix)[0] in ("C", "Z", "M"):
		await reply(broadcaster_id, "Prefix must be a visible character.", app_access_token, message_id)
		return

	if new_prefix in BLOCKED_PREFIXES:
		await reply(broadcaster_id, f"'{new_prefix}' is reserved by Twitch and can't be used.", app_access_token, message_id)
		return

	await set_broadcaster_prefix(broadcaster_id, new_prefix)
	await reply(broadcaster_id, f"Command prefix updated to '{new_prefix}'", app_access_token, message_id)

@safe_command
async def get_vod(broadcaster_id, username, app_access_token, message_id=None, prefix='$'):
	if broadcaster_id not in BROADCASTER_ID_247:
		return
	if username.lower() not in TRUSTED_USERS:
		untrusted_vod = get_vod()
		await reply(broadcaster_id, untrusted_vod, app_access_token, message_id)
	else:
		trusted_vod = get_trusted_vod()
		await reply(broadcaster_id, trusted_vod, app_access_token, message_id)

@safe_command
async def get_vod_info(broadcaster_id, username, app_access_token, message_id=None, prefix='$'):
	vod_info = await get_info()
	await reply(broadcaster_id, vod_info, app_access_token, message_id)

@safe_command
async def handle_uptime(broadcaster_id, username, parts, app_access_token, message_id=None, prefix='$'):
	info = await asyncio.to_thread(get_stream_info, broadcaster_id, app_access_token)
	if info == -1:
		offline = (f"Stream is currently offline.")
		await reply(broadcaster_id, offline, app_access_token, message_id)
		return
	started_at = datetime.fromisoformat(info[0]["started_at"].replace("Z", "+00:00"))
	uptime = format_uptime(datetime.now(timezone.utc) - started_at)
	live = (f"Stream has been live for {uptime}.")
	await reply(broadcaster_id, live, app_access_token, message_id)

@safe_command
async def handle_random_quote(broadcaster_id, user_id, username, parts, app_access_token, message_id=None, prefix='$'):
	if len(parts) > 1:
		target = clean_login(parts[1])
		user_id = await asyncio.to_thread(get_user_id, target, app_access_token) if target else None
		if not user_id:
			await reply(broadcaster_id, f"Could not find user {target or parts[1]}.", app_access_token, message_id)
			return

	if await check_opt_out(user_id, "randomquote"):
		response = "User has opted out of random quote"
	else:
		try:
			data = await get_random_message(broadcaster_id, user_id)
			if not data or not data.get("messages"):
				response = "No messages found"
			else:
				m = data["messages"][0]
				response = f"({time_ago(m['timestamp'])}) {m['displayName']} : {m['text']}"
		except (aiohttp.ClientError, TimeoutError, ValueError):
			response = "Error retrieving message logs"

	await reply(broadcaster_id, response, app_access_token, message_id)

@safe_command
async def handle_random_line(broadcaster_id, user_id, parts, app_access_token, message_id=None, prefix='$'):
	optout = True
	response = "No messages found"
	attempts = 5
	for attempt in attempts:
		try:
			data = await get_random_line(broadcaster_id)
		

			if not data or not data.get("messages"):
				response = "No messages found"
				break
			msg = data["messages"][0]
			text = msg["text"]
			time = msg["timestamp"]
			username = msg["username"]
			user_id = msg.get("tags", {}).get("user-id")

			if not user_id:
				continue;
			

			if not await check_opt_out(user_id, "randomquote"):
				optout = False
				response = (f"(time_ago{time}) {username} : {text}")
				break;

		except (aiohttp.ClientError, TimeoutError, ValueError) as e:
			response = "Error retrieving message logs"

	if optout and response == "No messages found":
		response = "Couldn't find any messages"
	await reply(broadcaster_id, response, app_access_token, message_id)

@safe_command
async def handle_first_line(broadcaster_id, user_id, username, parts, app_access_token, message_id=None, prefix='$'):

	if await check_opt_out(user_id, "firstmessage"):
		response = "User has opted out of random quote"
	else:
		try:
			data = await get_first_message(broadcaster_id, user_id)
			if not data:
				response = "No messages found"
			else:
				for msg in data["messages"]:
					text = msg["text"]
					time = time_ago(msg["timestamp"])
					username = msg["displayName"]
				response = (f"({time}) {username} : {text}")

		except (aiohttp.ClientError, TimeoutError, ValueError) as e:
			response = "Error retrieving message logs"
	await reply(broadcaster_id, response, app_access_token, message_id)


@safe_command
async def handle_opt_out(broadcaster_id, user_id, username, parts, app_access_token, message_id=None, prefix='$'):
	if len(parts) < 2:
		await reply(broadcaster_id, f"Usage: {prefix}optout <command>", app_access_token, message_id)
		return
	command_name = parts[1].lower()
	
	success = await edit_optout(user_id, command_name)
	if success:
		await reply(broadcaster_id, f"{username} has opted out of {command_name}", app_access_token, message_id)
	else:
		await reply(broadcaster_id, f"{username} was already opted out of {command_name}", app_access_token, message_id)

@safe_command
async def handle_followage(broadcaster_id, user_id, username, parts, app_access_token, message_id=None, prefix='$'):
	target = clean_login(parts[1]) if len(parts) > 1 else ""
	if not target:
		target_id, target_name = user_id, username   # default to the chatter
	else:
		target_id = get_user_id(target, app_access_token)
		target_name = target
		if not target_id:
			await reply(broadcaster_id, f"Could not find user {target}.", app_access_token, message_id)
			return
	
	broadcaster = await get_broadcaster(broadcaster_id)
	token = broadcaster["user_access_token"]
	age = get_follow_age(target_id, broadcaster_id, token)
	timeSince = time_ago(age)
	readable_age = format_date(age)
	await reply(broadcaster_id, f"{username} followed on {readable_age} ({timeSince})", app_access_token, message_id)



# Main router
@safe_command
async def route_command(row, parts, broadcaster_id, is_mod, is_vip, is_broadcaster, user_id, username, app_access_token, message_id=None, prefix='$', modified_by=None, latency_ms=0):
	command_name = "$" + canonical(parts[0].lower().removeprefix(prefix))
	response = row["response"]
	
	if command_name == "$timeout":
		await handle_timeout(broadcaster_id, parts, app_access_token, message_id, prefix)
	elif command_name == "$ban":
		await handle_ban(broadcaster_id, parts, app_access_token, message_id, prefix)
	elif command_name == "$createpoll":
		await handle_create_poll(broadcaster_id, parts, app_access_token, message_id, prefix)
	elif command_name == "$addcom":
		await handle_addcom(broadcaster_id, parts, app_access_token, message_id, prefix)
	elif command_name == "$editcom":
		await handle_editcom(broadcaster_id, parts, app_access_token, message_id, prefix, modified_by)
	elif command_name == "$delcom":
		await handle_delcom(broadcaster_id, parts, app_access_token, message_id, prefix)
	elif command_name == "$editperm":
		await handle_editperms(broadcaster_id, parts, app_access_token, message_id, prefix)
	#elif command_name == "$commands":
	#	await handle_commands_list(broadcaster_id, app_access_token, message_id, prefix)
	elif command_name == "$setprefix":
		await handle_set_prefix(broadcaster_id, parts, app_access_token, message_id, prefix)
	elif command_name == "$vod":
		await get_vod(broadcaster_id, username, app_access_token, message_id, prefix)
	elif command_name == "$vodinfo":
		await get_vod_info(broadcaster_id, username, app_access_token, message_id, prefix)
	elif command_name == "$uptime":
		await handle_uptime(broadcaster_id, username, parts, app_access_token, message_id, prefix)
	elif (command_name == "$randomquote"):
		await handle_random_quote(broadcaster_id, user_id, username, parts, app_access_token, message_id, prefix)
	elif command_name == "$randomline":
		await handle_random_line(broadcaster_id, parts, app_access_token, message_id, prefix)
	elif (command_name == "$firstmessage"):
		await handle_first_line(broadcaster_id, user_id, username, parts, app_access_token, message_id, prefix)
	elif command_name == "$optout":
		await handle_opt_out(broadcaster_id, user_id, username, parts, app_access_token, message_id, prefix)
	elif command_name == "$followage":
		await handle_followage(broadcaster_id, user_id, username, parts, app_access_token, message_id, prefix)
	elif command_name == "$skip":
		await handle_skip(broadcaster_id, app_access_token, message_id)

	
	elif response:
		await handle_static(response, broadcaster_id, user_id, username, parts, app_access_token, message_id, latency_ms)
	else:
		logger.error(f"[Route] No handler found for {command_name}")


	

