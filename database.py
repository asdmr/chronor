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
                created_at TEXT NOT NULL
            )
        """)
        logger.debug("Table 'users' checked/created.")
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
        logger.info("Database table structure successfully checked/created (user/activity only).")
    except sqlite3.Error as e:
        logger.error(f"Error creating tables: {e}")
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
        logger.critical(f"Critical error during database initialization: {e}", exc_info=True)
        raise

def add_user_if_not_exists(user_id: int, username: str | None, first_name: str):
    sql = """
        INSERT OR IGNORE INTO users (user_id, telegram_username, first_name, created_at)
        VALUES (?, ?, ?, ?)
    """
    now_iso = datetime.now().isoformat()
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, username, first_name, now_iso))
        con.commit()
        if cur.rowcount > 0: logger.info(f"New user user_id={user_id}, username={username} added to DB.")
        else: logger.debug(f"User user_id={user_id}, username={username} already exists in DB.")
        con.close()
    except sqlite3.Error as e:
        logger.error(f"Error adding/checking user user_id={user_id} in DB: {e}")
        if con: con.close()

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
        logger.info(f"Activity '{description[:20]}...' for user {user_id} saved with ID {activity_id}.")
        return activity_id
    except sqlite3.Error as e:
        logger.error(f"Error saving activity for user {user_id} to DB: {e}")
        if con: con.close()
        return None

def get_activities_for_day(user_id: int, report_date: str) -> list[tuple[str, str]]:
    activities_list = []
    sql = """
        SELECT timestamp, description
        FROM activities
        WHERE user_id = ? AND DATE(timestamp) = ?
        ORDER BY timestamp ASC
    """
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, report_date))
        results = cur.fetchall()
        con.close()
        activities_list = results
        logger.info(f"Found {len(activities_list)} activities for user {user_id} on date {report_date}.")
        return activities_list
    except sqlite3.Error as e:
        logger.error(f"SQLite error retrieving activities for user {user_id} on date {report_date}: {e}")
        if con: con.close()
        return []
