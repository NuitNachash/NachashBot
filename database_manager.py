import asyncpg
import asyncio
import requests
import psycopg2
import psycopg2.extras
from logger import logger
from functools import partial
from datetime import datetime, timezone
from config import *
from twitch_api import get_chatters

pool = None

def canonical(cmd):
    return COMMAND_ALIASES.get(cmd.lower(), cmd.lower())

async def init_pool():
    global pool
    pool = await asyncpg.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        min_size=2,
        max_size=10
    )
    logger.info("[DB] Connection pool created")

async def close_pool():
    global pool
    if pool:
        await pool.close()
        print("[DB] Connection pool closed")

async def add_broadcaster(broadcaster_id, broadcaster_name, access_token, refresh_token, expires_at):
    async with pool.acquire() as conn:
        await conn.execute("""
        INSERT INTO broadcasters (broadcaster_id, broadcaster_name, user_access_token, user_refresh_token, token_expires_at)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (broadcaster_id) DO UPDATE
        SET broadcaster_name = $2,
            user_access_token = $3,
            user_refresh_token = $4,
            token_expires_at = $5,
            active = TRUE
        """, broadcaster_id, broadcaster_name, access_token, refresh_token, expires_at)

async def get_broadcaster(broadcaster_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT * FROM broadcasters WHERE broadcaster_id = $1
            """, broadcaster_id)

async def get_active_broadcasters():
    async with pool.acquire() as conn:
        return await conn.fetch("""
            SELECT * FROM broadcasters WHERE active = TRUE
            """)

async def update_broadcaster_tokens(broadcaster_id, access_token, refresh_token, expires_at):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE broadcasters
            SET user_access_token = $2,
                user_refresh_token = $3,
                token_expires_at = $4
            WHERE broadcaster_id = $1
            """, broadcaster_id, access_token, refresh_token, expires_at)

async def upsert_user(user_id, username):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, last_seen)
            VALUES ($1, $2, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET username = $2,
                last_seen = NOW()
            """, user_id, username)

async def get_user(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT * FROM users WHERE user_id = $1
        """, user_id)

async def get_username(user_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT username FROM users WHERE user_id = $1
        """, user_id)

async def log_messages(broadcaster_id, user_id, message):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO messages (broadcaster_id, user_id, message)
            VALUES ($1, $2, $3)
        """, broadcaster_id, user_id, message)

async def get_first_message(broadcaster_id, user_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT message, sent_at FROM messages
            WHERE user_id = $2 AND broadcaster_id = $1
            ORDER BY sent_at ASC
           LIMIT 1
       """, broadcaster_id, user_id)
       #                AND message !~ '^[\!@#$%^&*()]'


async def get_random_messageDB(broadcaster_id, user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT message, sent_at FROM messages
            WHERE user_id = $2 AND broadcaster_id = $1
            ORDER BY RANDOM()
            LIMIT 1
        """, broadcaster_id, user_id)

        return row

async def get_command(broadcaster_id, command_name, prefix="$"):
    logger.info("[DB] get_command called")
    async with pool.acquire() as conn:        
        bare_name = command_name.removeprefix(prefix)
        db_command = "$" + canonical(bare_name)

        logger.debug(f"[DB] DB command name: {db_command}")

        #return Response, Command Type, and Permission level for Channel Specific
        row = await conn.fetchrow("""
            SELECT response, permission_level FROM commands
            WHERE broadcaster_id = $1
            AND command_name = $2
            AND enabled = TRUE
        """, broadcaster_id, db_command)

        if row:
            return row

        #return Response, Command Type, and Permission level for General 
        row = await conn.fetchrow("""
            SELECT response, permission_level FROM commands
            WHERE broadcaster_id IS NULL
            AND command_name = $1
            AND enabled = TRUE
        """, db_command)

        return row

async def add_command(broadcaster_id, command_name, response, permission_level="everyone"):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO commands (broadcaster_id, command_name, response)
            VALUES ($1, $2, $3)
            ON CONFLICT (broadcaster_id, command_name) DO UPDATE
            SET response = $3,
                enabled = TRUE
        """, broadcaster_id, command_name, response)

# add edit_command option
async def edit_command(broadcaster_id, command_name, response, modified_by):
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE commands
            SET response = $3,
                modified_at = NOW(),
                modified_by = $4
            WHERE broadcaster_id=$1
            AND command_name = $2
            AND enabled = TRUE
        """, broadcaster_id, command_name, response, modified_by)

async def del_command(broadcaster_id, command_name):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE commands SET enabled = FALSE
            WHERE broadcaster_id = $1 AND command_name = $2
        """, broadcaster_id, command_name)

# add edit_command_permissions 
#async def edit_command_permission(broadcaster_id, command_name, new_permission):
#    return NULL


async def track_chat_time(broadcaster_id, moderator_id, access_token, is_live):
    while True:
        await asyncio.sleep(60)
        try:
            chatters = await asyncio.to_thread(get_chatters, broadcaster_id, moderator_id, access_token)

            if not chatters:
                continue

            async with pool.acquire() as conn:
                await conn.executemany("""
                    INSERT INTO users (user_id, username, last_seen)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (user_id) DO UPDATE
                    SET username = $2,
                        last_seen = NOW()
                """, [(c["user_id"], c["user_login"]) for c in chatters])
            
                column = "live_seconds" if is_live[0] else "offline_seconds"
                await conn.executemany(f"""
                    INSERT INTO chat_time (user_id, broadcaster_id, {column}, last_seen)
                    VALUES ($1, $2, 60, NOW())
                    ON CONFLICT (user_id, broadcaster_id) DO UPDATE
                    SET {column} = chat_time.{column} + 60,
                        last_seen = NOW()
                """, [(c["user_id"], broadcaster_id) for c in chatters])

        except Exception as e:
            logger.error(f"[ChatTime/{broadcaster_id}] Error: {e}")

async def get_live_time(user_id, broadcaster_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT live_seconds FROM chat_time
            WHERE broadcaster_id = $2
            AND user_id = $1
        """, user_id, broadcaster_id)

async def get_offline_time(user_id, broadcaster_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT offline_seconds FROM chat_time
            WHERE broadcaster_id = $2
            AND user_id = $1
        """, user_id, broadcaster_id)
        
async def start_trackers(broadcasters, moderator_id, app_access_token, is_live):
    for i, broadcaster in enumerate(broadcasters):
        asyncio.create_task(track_chat_time(
            broadcaster["broadcaster_id"],
            moderator_id,
            app_access_token,
            is_live
        ))
        await asyncio.sleep(10)

async def start_stream_session(broadcaster_id, started_at):
    async with pool.acquire() as conn:
        return await conn.execute("""
            INSERT INTO stream_sessions (broadcaster_id, started_at)
            VALUES ($1, $2)
        """, broadcaster_id, started_at)

async def end_stream_session(broadcaster_id):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE stream_sessions
            SET ended_at = NOW(),
                duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at))::BIGINT
            WHERE broadcaster_id = $1
            AND ended_at IS NULL
        """, broadcaster_id)
    
async def get_current_uptime(broadcaster_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT started_at FROM stream_sessions
            WHERE broadcaster_id = $1
            AND ended_at IS NULL
            ORDER BY started_at DESC
            LIMIT 1
        """, broadcaster_id)
    if not row:
        return -1

    now = datetime.now(timezone.utc)
    return now - row["started_at"] 

#async def  get_all_commands(broadcaster_id):
    

async def get_broadcaster_prefix(broadcaster_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT command_prefix FROM broadcasters
            WHERE broadcaster_id = $1
        """, broadcaster_id)
        return row["command_prefix"] if row else "$"

async def set_broadcaster_prefix(broadcaster_id, prefix):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE broadcasters
            SET command_prefix = $2
            WHERE broadcaster_id = $1
        """, broadcaster_id, prefix)

async def init_vod_pool():
    global pool2
    pool2 = await asyncpg.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        database=VOD_DB_NAME,
        user=VOD_DB_USER,
        password=VOD_DB_PASSWORD,
        min_size=2,
        max_size=10
    )

def _database_query_sync(filename, channel):
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=VOD_DB_NAME,
        user=VOD_DB_USER,
        password=VOD_DB_PASSWORD,
    )

    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute("""
        SELECT 
            s.started_at, 
            s.time_live, 
            s.title, 
            v.vod_url,  
            STRING_AGG(DISTINCT g.game_name, ', ' ORDER BY g.game_name) AS games_played
        FROM stream AS s
        JOIN vod AS v ON v.id = s.id
        JOIN gamesplayed AS g ON g.id = s.id
        WHERE v.filename = %s AND v.streamer = %s
        GROUP BY
            s.streamer,
            s.started_at,
            s.time_live,
            s.title,
            v.vod_url;
    """, (filename, channel))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return None

    for row in rows:
        return {
            "title": row["title"],
            "started_at": row["started_at"],
            "time_live": row["time_live"],
            "gamesplayed": row["games_played"],
            "vod_url": row["vod_url"]
        }

async def database_query(filename, channel):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_database_query_sync, filename, channel))

async def check_opt_out(user_id, command):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT EXISTS (
                SELECT 1 FROM user_opt_out 
                WHERE user_id = $1 AND command = $2
            ) AS is_opted_out;
        """, user_id, command)  
    return row["is_opted_out"]

async def edit_optout(user_id, command_name):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO user_opt_out (user_id, command)
            VALUES ($1, $2)
            ON CONFLICT (user_id, command) DO NOTHING
            RETURNING user_id
        """, user_id, command_name)
        return row is not None
        

prefix_cache = {}   # broadcaster_id -> prefix

async def get_broadcaster_prefix(broadcaster_id):
    if broadcaster_id in prefix_cache:
        return prefix_cache[broadcaster_id]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT command_prefix FROM broadcasters WHERE broadcaster_id = $1", broadcaster_id)
    prefix_cache[broadcaster_id] = row["command_prefix"] if row else "$"
    return prefix_cache[broadcaster_id]

async def set_broadcaster_prefix(broadcaster_id, prefix):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE broadcasters SET command_prefix = $2 WHERE broadcaster_id = $1",
            broadcaster_id, prefix)
    prefix_cache[broadcaster_id] = prefix