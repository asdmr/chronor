import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_FOLDER = "data"
DB_NAME = "activities.db"
DB_PATH = os.path.join(DB_FOLDER, DB_NAME)


def _get_db_connection():
    try:
        if not os.path.exists(DB_FOLDER):
            os.makedirs(DB_FOLDER)
            logger.info(f"Created database folder at '{DB_FOLDER}'.")
        con = sqlite3.connect(DB_PATH)
        con.execute("PRAGMA foreign_keys = ON;")
        return con
    except sqlite3.Error as e:
        logger.error(f"Error connecting to DB '{DB_PATH}': {e}")
        raise
    except OSError as e:
        logger.error(f"Error creating directory '{DB_FOLDER}': {e}")
        raise


def _create_tables(con: sqlite3.Connection):
    try:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                telegram_username TEXT,
                first_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                timezone TEXT DEFAULT NULL,
                last_daily_report_sent_date TEXT DEFAULT NULL
            )
        """)
        logger.debug(
            "Table 'users' checked/created (with timezone, last_report_date).")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                description TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
        """)
        logger.debug("Table 'activities' checked/created.")
        con.commit()
        logger.info("Database table structure successfully checked/updated.")
    except sqlite3.Error as e:
        logger.error(f"Error creating/updating tables: {e}")
        con.rollback()
        raise


def initialize_database():
    logger.info(f"Initializing database at '{DB_PATH}'...")
    try:
        con = _get_db_connection()
        _create_tables(con)
        con.close()
        logger.info("Database initialization finished.")
    except Exception as e:
        logger.critical(
            f"Critical error during database initialization: {e}", exc_info=True)
        raise


def add_user_if_not_exists(user_id: int, username: str | None, first_name: str):
    sql = """
        INSERT OR IGNORE INTO users (user_id, telegram_username, first_name, created_at, timezone, last_daily_report_sent_date)
        VALUES (?, ?, ?, ?, NULL, NULL)
    """
    now_iso = datetime.now().isoformat()
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, username, first_name, now_iso))
        con.commit()
        if cur.rowcount > 0:
            logger.info(
                f"New user user_id={user_id}, username={username} added to DB.")
        else:
            logger.debug(
                f"User user_id={user_id}, username={username} already exists in DB.")
        con.close()
    except sqlite3.Error as e:
        logger.error(
            f"Error adding/checking user user_id={user_id} in DB: {e}")
        con.close() if con else None


def update_user_timezone(user_id: int, timezone_str: str | None) -> bool:
    sql = "UPDATE users SET timezone = ? WHERE user_id = ?"
    success = False
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (timezone_str, user_id))
        con.commit()
        if cur.rowcount > 0:
            success = True
            logger.info(
                f"Timezone for user {user_id} updated to '{timezone_str}'.")
        else:
            logger.warning(
                f"Could not update timezone for user {user_id} (user not found?).")
        con.close()
        return success
    except sqlite3.Error as e:
        logger.error(f"SQLite error updating timezone for user {user_id}: {e}")
        con.rollback() if con else None
        con.close() if con else None
        return False


def get_user_timezone_str(user_id: int) -> str | None:
    sql = "SELECT timezone FROM users WHERE user_id = ?"
    timezone_str = None
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id,))
        result = cur.fetchone()
        con.close()
        if result and result[0]:
            timezone_str = result[0]
            logger.debug(
                f"Retrieved timezone '{timezone_str}' for user {user_id}.")
        else:
            logger.debug(f"No timezone set for user {user_id}.")
        return timezone_str
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error retrieving timezone for user {user_id}: {e}")
        con.close() if con else None
        return None


def get_all_user_ids_with_tz() -> list[int]:
    user_ids = []
    sql = "SELECT user_id FROM users WHERE timezone IS NOT NULL"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql)
        results = cur.fetchall()
        con.close()
        user_ids = [row[0] for row in results]
        logger.info(f"Found {len(user_ids)} users with timezone set.")
        return user_ids
    except sqlite3.Error as e:
        logger.error(f"SQLite error retrieving users with timezone: {e}")
        con.close() if con else None
        return []


def get_last_report_sent_date(user_id: int) -> str | None:
    sql = "SELECT last_daily_report_sent_date FROM users WHERE user_id = ?"
    date_str = None
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id,))
        result = cur.fetchone()
        con.close()
        if result and result[0]:
            date_str = result[0]
        logger.debug(
            f"Last report sent date for user {user_id} is {date_str}.")
        return date_str
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error getting last report sent date for user {user_id}: {e}")
        con.close() if con else None
        return None


def update_last_report_sent_date(user_id: int, date_str: str) -> bool:
    sql = "UPDATE users SET last_daily_report_sent_date = ? WHERE user_id = ?"
    success = False
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (date_str, user_id))
        con.commit()
        if cur.rowcount > 0:
            success = True
            logger.info(
                f"Updated last report sent date for user {user_id} to {date_str}.")
        else:
            logger.warning(
                f"Could not update last report sent date for user {user_id} (user not found?).")
        con.close()
        return success
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error updating last report sent date for user {user_id}: {e}")
        con.rollback() if con else None
        con.close() if con else None
        return False


def save_activity_to_db(user_id: int, description: str, timestamp: datetime) -> int | None:
    sql = "INSERT INTO activities (user_id, description, timestamp) VALUES (?, ?, ?)"
    activity_id = None
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, description, timestamp.isoformat()))
        activity_id = cur.lastrowid
        con.commit()
        con.close()
        logger.info(
            f"Activity '{description[:20]}...' for user {user_id} saved with ID {activity_id}.")
        return activity_id
    except sqlite3.Error as e:
        logger.error(f"Error saving activity for user {user_id} to DB: {e}")
        con.close() if con else None
        return None


def get_activities_for_day(user_id: int, report_date: str) -> list[tuple[int, str, str]]:
    activities_list = []
    sql = "SELECT activity_id, timestamp, description FROM activities WHERE user_id = ? AND DATE(timestamp) = ? ORDER BY timestamp ASC"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, report_date))
        results = cur.fetchall()
        con.close()
        activities_list = results
        logger.info(
            f"Found {len(activities_list)} activities for user {user_id} on date {report_date}.")
        return activities_list
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error retrieving activities for user {user_id} on date {report_date}: {e}")
        con.close() if con else None
        return []


def update_activity_description(activity_id: int, user_id: int, new_description: str) -> bool:
    sql = "UPDATE activities SET description = ? WHERE activity_id = ? AND user_id = ?"
    updated = False
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (new_description, activity_id, user_id))
        con.commit()
        if cur.rowcount > 0:
            updated = True
            logger.info(
                f"Activity ID {activity_id} for user {user_id} updated successfully.")
        else:
            logger.warning(
                f"Attempted to update activity ID {activity_id} for user {user_id}, but no matching record found.")
        con.close()
        return updated
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error updating activity ID {activity_id} for user {user_id}: {e}")
        con.rollback() if con else None
        con.close() if con else None
        return False
