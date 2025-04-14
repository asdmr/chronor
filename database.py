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
            CREATE TABLE IF NOT EXISTS tags (
                tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tag_name TEXT NOT NULL COLLATE NOCASE,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
                UNIQUE (user_id, tag_name)
            )
        """)
        logger.debug("Table 'tags' checked/created.")

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

        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_tags (
                activity_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                FOREIGN KEY (activity_id) REFERENCES activities (activity_id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags (tag_id) ON DELETE CASCADE,
                PRIMARY KEY (activity_id, tag_id)
            )
        """)
        logger.debug("Table 'activity_tags' checked/created.")

        con.commit()
        logger.info("Database table structure successfully checked/created.")

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
        if cur.rowcount > 0:
            logger.info(f"New user user_id={user_id}, username={username} added to DB.")
        else:
            logger.debug(f"User user_id={user_id}, username={username} already exists in DB.")
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

def add_tag(user_id: int, tag_name: str) -> int | None:
    tag_name_lower = tag_name.lower()
    tag_id = None
    sql_insert = "INSERT INTO tags (user_id, tag_name) VALUES (?, ?)"
    sql_select = "SELECT tag_id FROM tags WHERE user_id = ? AND tag_name = ?"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql_insert, (user_id, tag_name_lower))
        tag_id = cur.lastrowid
        con.commit()
        logger.info(f"New tag '{tag_name_lower}' added for user {user_id} with ID {tag_id}.")
        con.close()
        return tag_id
    except sqlite3.IntegrityError:
        logger.info(f"Tag '{tag_name_lower}' for user {user_id} already exists. Fetching its ID.")
        if con:
            cur = con.cursor()
            try:
                 cur.execute(sql_select, (user_id, tag_name_lower))
                 result = cur.fetchone()
                 if result:
                     tag_id = result[0]
                     logger.info(f"Found existing tag '{tag_name_lower}' for user {user_id} with ID {tag_id}.")
                     con.close()
                     return tag_id
                 else:
                     logger.error(f"Could not find tag '{tag_name_lower}' for user {user_id} after IntegrityError.")
                     con.close()
                     return None
            except sqlite3.Error as select_e:
                 logger.error(f"Error selecting existing tag '{tag_name_lower}' for user {user_id}: {select_e}")
                 if con: con.close()
                 return None
        else:
            logger.error("DB connection was closed before attempting to select existing tag.")
            return None
    except sqlite3.Error as e:
        logger.error(f"SQLite error adding tag '{tag_name_lower}' for user {user_id}: {e}")
        if con: con.rollback(); con.close()
        return None

def get_tag_id(user_id: int, tag_name: str) -> int | None:
    tag_id = None
    sql = "SELECT tag_id FROM tags WHERE user_id = ? AND tag_name = LOWER(?)"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, tag_name.lower()))
        result = cur.fetchone()
        con.close()
        if result:
            tag_id = result[0]
            logger.debug(f"Found ID {tag_id} for tag '{tag_name}' for user {user_id}")
        else:
            logger.debug(f"Tag '{tag_name}' not found for user {user_id}")
        return tag_id
    except sqlite3.Error as e:
        logger.error(f"SQLite error finding tag '{tag_name}' for user {user_id}: {e}")
        if con: con.close()
        return None

def link_activity_tag(activity_id: int, tag_id: int) -> bool:
    sql = "INSERT OR IGNORE INTO activity_tags (activity_id, tag_id) VALUES (?, ?)"
    success = False
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (activity_id, tag_id))
        con.commit()
        if cur.rowcount > 0:
            logger.info(f"Link created: activity_id={activity_id}, tag_id={tag_id}")
        else:
            logger.info(f"Link activity_id={activity_id}, tag_id={tag_id} already exists or not created.")
        con.close()
        success = True
    except sqlite3.Error as e:
        logger.error(f"SQLite error linking activity {activity_id} and tag {tag_id}: {e}")
        if con: con.rollback(); con.close()
        success = False
    return success

def get_user_tags(user_id: int) -> list[str]:
    tags_list = []
    sql = "SELECT tag_name FROM tags WHERE user_id = ? ORDER BY tag_name"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id,))
        results = cur.fetchall()
        con.close()
        tags_list = [row[0] for row in results]
        logger.info(f"Retrieved {len(tags_list)} tags for user {user_id}.")
        return tags_list
    except sqlite3.Error as e:
        logger.error(f"SQLite error retrieving tags for user {user_id}: {e}")
        if con: con.close()
        return []

def delete_tag(user_id: int, tag_name: str) -> bool:
    tag_name_lower = tag_name.lower()
    deleted = False
    sql = "DELETE FROM tags WHERE user_id = ? AND tag_name = ?"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, tag_name_lower))
        con.commit()
        if cur.rowcount > 0:
            deleted = True
            logger.info(f"Tag '{tag_name_lower}' for user {user_id} deleted.")
        else:
            logger.warning(f"Attempted to delete tag '{tag_name_lower}' for user {user_id}, but it was not found.")
        con.close()
        return deleted
    except sqlite3.Error as e:
        logger.error(f"SQLite error deleting tag '{tag_name_lower}' for user {user_id}: {e}")
        if con: con.rollback(); con.close()
        return False

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

def get_activities_with_tags_for_day(user_id: int, report_date: str) -> list[tuple[str, str | None]]:
    results_list = []
    sql = """
        SELECT
            a.timestamp,
            GROUP_CONCAT(t.tag_name ORDER BY t.tag_name ASC) AS concatenated_tags
        FROM activities a
        LEFT JOIN activity_tags at ON a.activity_id = at.activity_id
        LEFT JOIN tags t ON at.tag_id = t.tag_id AND t.user_id = a.user_id
        WHERE a.user_id = ? AND DATE(a.timestamp) = ?
        GROUP BY a.activity_id
        ORDER BY a.timestamp ASC;
    """
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, report_date))
        results = cur.fetchall()
        con.close()
        results_list = results
        logger.info(f"Found {len(results_list)} activities (with tags) for user {user_id} on date {report_date}.")
        return results_list
    except sqlite3.Error as e:
        logger.error(f"SQLite error retrieving activities with tags for user {user_id} on date {report_date}: {e}")
        if con: con.close()
        return []