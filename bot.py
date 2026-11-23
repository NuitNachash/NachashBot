import asyncio
import time 
import shutil
import requests 
from logger import logger
from database_manager import *
from token_manager import *
from eventsub import connect
from config import *
from monitor import *

async def token_refresh(broadcasters):
    while True:
        await asyncio.sleep(TOKEN_CHECK_INTERVAL)
        try:
            get_app_token()
            get_bot_token()
            current_broadcasters = await get_active_broadcasters()
            for broadcaster in current_broadcasters:
                try:
                    new_access, new_refresh = refresh_user_token(broadcaster["user_refresh_token"])
                    await update_broadcaster_tokens(
                        broadcaster["broadcaster_id"],
                        new_access,
                        new_refresh,
                        int(time.time() + 14400) #4hrs
                    )
                    logger.info(f"[Token] Refreshed token for {broadcaster['broadcaster_name']}")
                except Exception as e:
                    logger.error(f"[Token] Failed to refresh token for {broadcaster['broadcaster_name']}")
                    requests.post(f"https://ntfy.sh/{NOTIFY}",
                        data = f"Failed to refresh token for {broadcaster['broadcaster_name']}")
        except Exception as e:
            logger.error(f"[Token] Refresh error: {e}")

async def startup():
    print("[BOT] Starting up...")
    logger.info("[BOT] Starting up...")
    await init_pool()
    print("[BOT] Database pool initialized...")
    logger.info("[BOT] Database pool initialized...")
    await init_vod_pool()
    
    tokens = load_tokens()

    app_access_token, _ = refresh_app_token()
    print("[BOT] App access token refreshed")
    logger.info("[BOT] App access token refreshed")

    bot_access_token = refresh_bot_token()
    print("[Bot] Bot token refreshed")
    logger.info("[Bot] Bot token refreshed")

    broadcasters = await get_active_broadcasters()
    if not broadcasters:
        print("[BOT] No active broadcasters found in DB")
        logger.info("[BOT] No active broadcasters found in DB")
        return None, None 
    for broadcaster in broadcasters:
        try:
            new_access, new_refresh = refresh_user_token(
                broadcaster["user_refresh_token"]
            )
            await update_broadcaster_tokens(
                broadcaster["broadcaster_id"],
                new_access,
                new_refresh,
                int(time.time() + 14400)
            )
        except Exception as e:
            print(f"[Bot] Failed to refresh token for {broadcaster['broadcaster_name']}: {e}")
            logger.error(f"[Bot] Failed to refresh token for {broadcaster['broadcaster_name']}: {e}")
    
    broadcasters = await get_active_broadcasters()
    print(f"[BOT] Found {len(broadcasters)} active broadcaster(s)")
    logger.info(f"[BOT] Found {len(broadcasters)} active broadcaster(s)")
    return app_access_token, broadcasters 

async def main():
    app_access_token, broadcasters = await startup()

    if not app_access_token or not broadcasters:
        print("[BOT] Startup failed, exiting...")
        logger.error("[BOT] Startup failed, exiting...")
        return 

    tasks = []

    for broadcaster in broadcasters:
        task = asyncio.create_task(
            connect(
                broadcaster_id = broadcaster["broadcaster_id"],
                moderator_id = BOT_USER_ID,
                app_access_token = app_access_token,
                user_access_token = broadcaster["user_access_token"]
            )
        )
        tasks.append(task)
        await asyncio.sleep(2)

    tasks.append(asyncio.create_task(token_refresh(broadcasters)))
    tasks.append(asyncio.create_task(disk_space_monitor()))

    print("[BOT] All broadcasters connected. Running...")
    logger.info("[BOT] All broadcasters connected. Running...")

    try: 
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        print("[Bot] Tasks cancelled")
        logger.error("[Bot] Tasks cancelled")
    finally:
        await close_pool()
        print("[Bot] Shutdown")
        logger.info("[Bot] Shutdown")


if __name__ == "__main__":
    asyncio.run(main())

