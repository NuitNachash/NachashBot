import asyncio
import aiohttp
import json
import time
from logger import logger
from datetime import datetime, timezone
from config import CLIENT_ID, BOT_USER_ID, COMMAND_PREFIX, TRUSTED_USERS
from database_manager import *
from commands import route_command
from twitch_api import channel_uptime, get_chatters
from token_manager import refresh_user_token, get_bot_token
from chat import send_message
from commands import reply


EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws"
KEEPALIVE_TIMEOUT = 30  # seconds before assuming connection is dead

async def subscribe_to_event(session, session_id, event_type, broadcaster_id, moderator_id, app_access_token, bot_access_token, user_access_token):
	url = "https://api.twitch.tv/helix/eventsub/subscriptions"

	token = bot_access_token

	headers = {
		"Client-ID": CLIENT_ID,
		"Authorization": f"Bearer {token}",
		"Content-Type": "application/json"
	}

	condition = {"broadcaster_user_id": broadcaster_id}

	if event_type == "channel.chat.message":
		condition["user_id"] = moderator_id

	payload = {
		"type": event_type,
		"version": "1",
		"condition": condition,
		"transport": {
			"method": "websocket",
			"session_id": session_id
		}
	}

	async with session.post(url, headers=headers, json=payload) as resp:
		if resp.status != 202:
			text = await resp.text()
			logger.error(f"[EventSub] Failed to subscribe to {event_type}: {text}")
			return False
		else:
			logger.info(f"[EventSub] Subscribed to {event_type} for {broadcaster_id}")
			return True

async def handle_message(message, broadcaster_id, moderator_id, app_access_token, bot_access_token, user_access_token, is_live_ref, prefix_ref):
	msg_type = message.get("metadata", {}).get("message_type")
	payload = message.get("payload", {})

	if msg_type == "session_welcome":
		session_id = payload["session"]["id"]
		async with aiohttp.ClientSession() as session:
			results = [
				await subscribe_to_event(session, session_id, "channel.chat.message", broadcaster_id, moderator_id, app_access_token, bot_access_token, user_access_token),
				await subscribe_to_event(session, session_id, "stream.online", broadcaster_id, moderator_id, app_access_token, bot_access_token, user_access_token),
				await subscribe_to_event(session, session_id, "stream.offline", broadcaster_id, moderator_id, app_access_token, bot_access_token, user_access_token),
			]
		if not all(results):
			await asyncio.sleep(5)
			raise ReconnectException(EVENTSUB_URL)

	elif msg_type == "notification":
		event_type = payload.get("subscription", {}).get("type")
		event = payload.get("event", {})

		if event_type == "channel.chat.message":
			twitch_time = message.get("metadata", {}).get("message_timestamp")
			if twitch_time:
				send_dt = datetime.fromisoformat(twitch_time.replace("Z", "+00:00"))
				now = datetime.now(timezone.utc)
				latency_ms = round((now - send_dt).total_seconds() * 1000, 1)
				
			user_id = event["chatter_user_id"]
			username = event["chatter_user_login"]
			message_text = event["message"]["text"]
			message_id = event["message_id"]
			badges = event.get("badges", [])

			# parse permissions from badges
			badge_names = [b["set_id"] for b in badges]
			is_mod = "moderator" in badge_names
			is_vip = "vip" in badge_names
			is_broadcaster = "broadcaster" in badge_names

			# log into database
			await upsert_user(user_id, username)
			await log_messages(broadcaster_id, user_id, message_text)

			# get channel command prefix
			prefix = await get_broadcaster_prefix(broadcaster_id)

			# handle commands
			if message_text.startswith(prefix):
				#logger.info(f"[Cmd] handle command if=true")
				await handle_command(
					message_text, 
					user_id,
					username,
					broadcaster_id,
					is_mod,
					is_vip,
					is_broadcaster,
					app_access_token,
					message_id,
					prefix,
					latency_ms
				)

		elif event_type == "stream.online":
			started_at = datetime.fromisoformat(event["started_at"].replace("Z", "+00:00"))
			await start_stream_session(broadcaster_id, started_at)
			logger.info(f"[EventSub] {broadcaster_id} went live")
			is_live_ref[0] = True

		elif event_type == "stream.offline":
			await end_stream_session(broadcaster_id)
			logger.info(f"[EventSub] {broadcaster_id} went offline")
			is_live_ref[0] = False

	elif msg_type == "session_keepalive":
		pass  # connection is healthy

	elif msg_type == "session_reconnect":
		reconnect_url = payload["session"]["reconnect_url"]
		logger.info(f"[EventSub] Reconnect requested for {broadcaster_id}")
		raise ReconnectException(reconnect_url)

	elif msg_type == "revocation":
		logger.error(f"[EventSub] Revoked for {broadcaster_id}: {payload}")
		raise ReconnectException(EVENTSUB_URL)

async def handle_command(message_text, user_id, username, broadcaster_id, is_mod, is_vip, is_broadcaster, app_access_token, message_id=None, prefix="$", latency_ms=0):
	parts = message_text.strip().split()
	command = parts[0].lower()

	# look up command in database
	row = await get_command(broadcaster_id, command, prefix)
	if not row:
		return 
	
	# check user permissions
	permission = row["permission_level"]
	if permission == "everyone":
		pass 
	elif permission == "vip":
		if not (is_vip or is_mod or is_broadcaster or username.lower() in TRUSTED_USERS):
			return 
	elif permission == "moderator":
		if not (is_mod or is_broadcaster or username.lower() in TRUSTED_USERS):
			return 
	elif permission == "broadcaster":
		if not (is_broadcaster or username.lower() in TRUSTED_USERS):
			return
	elif permission == "trusted":
		if username.lower() not in TRUSTED_USERS:
			return 
	
	# hand off to command.py
	await route_command(row, parts, broadcaster_id, is_mod, is_vip, is_broadcaster, user_id, username, app_access_token, message_id, prefix, latency_ms)

class ReconnectException(Exception):
	def __init__(self, url):
		self.url = url

async def check_bot_is_mod(broadcaster_id, user_access_token):
	url = "https://api.twitch.tv/helix/moderation/moderators"
	headers = {
		"Client-ID": CLIENT_ID,
		"Authorization": f"Bearer {user_access_token}"
	}
	params = {
		"broadcaster_id": broadcaster_id,
		"user_id": BOT_USER_ID
	}

	async with aiohttp.ClientSession() as session:
		async with session.get(url, headers=headers, params=params) as resp:
			data = await resp.json()
			return len(data.get("data", [])) > 0

async def connect(broadcaster_id, moderator_id, app_access_token, user_access_token, url=None):
	broadcaster = await get_broadcaster(broadcaster_id)
	if not broadcaster:
		logger.error(f"[EventSub] Broadcaster {broadcaster_id} not found in database")
		return
	
	is_mod = await check_bot_is_mod(broadcaster_id, user_access_token)
	if not is_mod and (moderator_id != broadcaster_id):
		logger.error(f"[EventSub] Bot is not modded in {broadcaster_id}, waiting..")
		while not is_mod:
			await asyncio.sleep(60)
			is_mod = await check_bot_is_mod(broadcaster_id, app_access_token)
		logger.error(f"[EventSub] Bot is now modded in {broadcaster_id}, connecting...")
	
	user_access_token = broadcaster["user_access_token"]
	bot_access_token = get_bot_token()
	if not bot_access_token:
		logger.error(f"[EventSub] No bot token found in tokens.json")
		return 

	token_expires_at = broadcaster["token_expires_at"]
	
	is_live_ref = [channel_uptime(broadcaster_id, app_access_token) != -1]
	prefix_ref = [await get_broadcaster_prefix(broadcaster_id)]

	asyncio.create_task(track_chat_time(broadcaster_id, moderator_id, app_access_token, is_live_ref))

	connect_url = url or EVENTSUB_URL
	last_keepalive = time.time()
	if not token_expires_at or time.time() >= token_expires_at - 300:
		logger.info(f"[EventSub] Refreshing token for {broadcaster_id}")
		try:
			new_access, new_refresh = refresh_user_token(broadcaster["user_refresh_token"])
			await update_broadcaster_tokens(
				broadcaster_id,
				new_access,
				new_refresh,
				int(time.time() + 14400)
			)
			user_access_token = new_access
		except Exception as e:
			logger.error(f"[EventSub] Failed to refresh token for {broadcaster_id}: {e}")
			return
	while True: 
		try:
			bot_access_token = await asyncio.to_thread(get_bot_token)
			b = await get_broadcaster(broadcaster_id)
			user_access_token = b["user_access_token"]

			async with aiohttp.ClientSession() as session:
				async with session.ws_connect(connect_url, heartbeat=20) as ws:
					logger.info(f"[EventSub] Connected for {broadcaster_id}")
					while True:
						#Twitch sends a keepalive every ~10s, silence -> dead
						msg = await ws.receive(timeout=KEEPALIVE_TIMEOUT)

						if msg.type == aiohttp.WSMsgType.TEXT:
							data = json.loads(msg.data)
							try:
								await handle_message(data, broadcaster_id, moderator_id, app_access_token,
									bot_access_token, user_access_token, is_live_ref, prefix_ref)
							except ReconnectException as e:
								connect_url = e.url
								break
							except Exception as e:
								print(f"[EventSub] Handler error: {e}")
						elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
							connect_url = EVENTSUB_URL
							break
				logger.info(f"[EventSub] {broadcaster_id} closed, code={ws.close_code}")
		except asyncio.TimeoutError:
			print(f"[EventSub] No keepalive for {broadcaster_id}, reconnecting...")
			connect_url = EVENTSUB_URL
		except Exception as e:
			logger.error(f"[EventSub] Connection error for {broadcaster_id}: {e}")
			connect_url = EVENTSUB_URL
			await asyncio.sleep(5)