import requests
from datetime import datetime, timezone
from config import CLIENT_ID 

def get_chatters(broadcaster_id, moderator_id, app_access_token):
    url = "https://api.twitch.tv/helix/chat/chatters"
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {app_access_token}"
    }

    chatters = []
    cursor = None

    while True:
        params = {
            "broadcaster_id": broadcaster_id,
            "moderator_id": moderator_id,
            "first": 1000
        }

        if cursor:
            params["after"] = cursor
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        chatters.extend(data.get("data", []))

        cursor = data.get("pagination", {}).get("cursor")
        if not cursor:
            break 
    
    return chatters

def channel_uptime(broadcaster_id, access_token):
    url = "https://api.twitch.tv/helix/streams"
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers, params={"broadcaster_id": broadcaster_id})
    response.raise_for_status()
    data = response.json().get("data", [])
    if not data:
        return -1

    started_at = data[0]["started_at"]
    started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return now - started_dt

def get_stream_info(user_id, access_token):
    url = "https://api.twitch.tv/helix/streams"
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers, params={"user_id": user_id})
    response.raise_for_status()
    data = response.json().get("data", [])
    if not data:
        return -1
    
    return data

def get_offline_info(broadcaster_id, access_token):
    url = "https://api.twitch.tv/helix/channels"
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers, params={"broadcaster_id": broadcaster_id})
    response.raise_for_status()
    data = response.json().get("data", [])
    if not data:
        return -1
    return data

def get_user_id(username, access_token):
    url = "https://api.twitch.tv/helix/users"
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers, params={"login": username})
    response.raise_for_status()
    data = response.json().get("data", [])
    return data[0]["id"] if data else None

def get_follow_age(user_id, broadcaster_id, access_token):
    url = "https://api.twitch.tv/helix/channels/followers"
    headers = {
        "Client-Id": CLIENT_ID,
        "Authorization": f"Bearer {access_token}"
    }

    response = requests.get(url, headers=headers, params={"broadcaster_id": broadcaster_id, "user_id": user_id})
    response.raise_for_status()
    data = response.json().get("data", [])
    return data[0]["followed_at"] if data else None