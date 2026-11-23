import aiohttp
import requests
from logger import logger
from config import CLIENT_ID 

async def send_message(broadcaster_id, user_id, message, app_access_token, reply_message_id=None):
    url = "https://api.twitch.tv/helix/chat/messages"
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {app_access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "broadcaster_id": broadcaster_id,
        "sender_id": user_id,
        "message": message 
    }

    if reply_message_id:
        payload["reply_parent_message_id"] = reply_message_id
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"[Chat] Failed to send message: {text}")

async def get_random_message(broadcaster_id, user_id):

    URL = f"https://logs.cyex.app/channelid/{broadcaster_id}/userid/{user_id}/random?json="

    async with aiohttp.ClientSession() as session:
        async with session.get(URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return await resp.json()
   
async def get_first_message(broadcaster_id, user_id):

    URL = f"https://logs.cyex.app/channelid/{broadcaster_id}/userid/{user_id}/2026/7?json=&limit=1"

    async with aiohttp.ClientSession() as session:
        async with session.get(URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return await resp.json()

