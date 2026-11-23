import json
import os
import requests
import time 
from config import CLIENT_ID, CLIENT_SECRET

TOKENS_FILE = os.path.expanduser("~/twitch/TwitchBot/tokens.json")

def load_tokens():
	if not os.path.exists(TOKENS_FILE):
		save_tokens({})
		return {}
	with open(TOKENS_FILE, "r") as f:
		return json.load(f)

def save_tokens(tokens):
	with open(TOKENS_FILE, "w") as f:
		json.dump(tokens, f, indent=4)

#automatically refresh Client Credentials Grant Flow access token
def refresh_app_token():
	url = "https://id.twitch.tv/oauth2/token"
	params = {
		"client_id": CLIENT_ID,
		"client_secret": CLIENT_SECRET,
		"grant_type": "client_credentials"
	}
	response = requests.post(url, params=params)
	response.raise_for_status()
	data = response.json()

	#convert expires_in to timestamp
	expires_at_timestamp = time.time() + data["expires_in"]

	tokens = load_tokens()
	tokens["app_access_token"] = data["access_token"]
	tokens["app_token_expires_at"] = expires_at_timestamp
	save_tokens(tokens)

	return data["access_token"], expires_at_timestamp

def get_app_token():
	tokens = load_tokens()
	if not tokens.get("app_access_token") or time.time() >= tokens.get("app_token_expires_at", 0) - 300:
		return refresh_app_token()[0]
	return tokens["app_access_token"]

# User token - authorization code flow
def get_refresh_token():
	url = "https://id.twitch.tv/oauth2/token"
	params = {
		"grant_type": "refresh_token",
		"refresh_token": refresh_token,
		"client_id": CLIENT_ID,
		"client_secret": CLIENT_SECRET
	}
	response = requests.post(url, params=params)
	response.raise_for_status()
	data = response.json()
	return data["access_token"], data["refresh_token"]

def refresh_user_token(refresh_token):
	url = "https://id.twitch.tv/oauth2/token"
	params = {
		"grant_type": "refresh_token",
		"refresh_token": refresh_token,
		"client_id": CLIENT_ID,
		"client_secret": CLIENT_SECRET
	}
	response = requests.post(url, params=params)
	response.raise_for_status()
	data = response.json()
	return data["access_token"], data["refresh_token"]

def refresh_bot_token():
	tokens = load_tokens()
	if not tokens.get("bot_refresh_token"):
		print("[Token] No bot refresh token found")
		return None
	
	new_access, new_refresh = refresh_user_token(tokens["bot_refresh_token"])
	tokens["bot_access_token"] = new_access
	tokens["bot_refresh_token"] = new_refresh
	tokens["bot_token_expires_at"] = int(time.time() + 14400)
	save_tokens(tokens)
	return new_access

def get_bot_token():
	tokens = load_tokens()
	if not tokens.get("bot_access_token") or time.time() >= tokens.get("bot_token_expires_at", 0) - 300:
		return refresh_bot_token()
	return tokens["bot_access_token"]