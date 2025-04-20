"""
Database interaction module for the Activity Tracker Bot.

Handles SQLite database connection, table creation, and data operations
for users and their activities, including settings like timezone,
polling window, and report time preferences.
"""
import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

# --- Constants ---
DB_FOLDER = "data"
DB_NAME = "activities.db"
DB_PATH = os.path.join(DB_FOLDER, DB_NAME)


# --- Private Helper Functions ---

def _get_db_connection() -> sqlite3.Connection:
    """
    Establishes a connection to the SQLite database.

    Ensures the data folder exists and enables foreign key support.

    Returns:
        sqlite3.Connection: The database connection object.

    Raises:
        sqlite3.Error: If connection fails.
        OSError: If directory creation fails.
    """
    try:
        # Ensure data directory exists
        if not os.path.exists(DB_FOLDER):
            os.makedirs(DB_FOLDER)
            logger.info(f"Created database folder at '{DB_FOLDER}'.")

        # Connect to the database file
        con = sqlite3.connect(DB_PATH)

        # Enable foreign key constraint enforcement for this connection
        con.execute("PRAGMA foreign_keys = ON;")
        logger.debug(
            "Database connection established with foreign keys enabled.")
        return con
    except sqlite3.Error as e:
        logger.error(f"Error connecting to DB '{DB_PATH}': {e}")
        raise  # Re-raise critical error
    except OSError as e:
        logger.error(f"Error creating directory '{DB_FOLDER}': {e}")
        raise  # Re-raise critical error


def _create_tables(con: sqlite3.Connection):
    """
    Creates the necessary database tables if they don't exist.

    Args:
        con: The active sqlite3 database connection.
    """
    logger.debug("Checking/creating database tables...")
    try:
        cur = con.cursor()

        # Users table: Stores user info and their preferences
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,          -- Telegram User ID
                telegram_username TEXT,               -- Username (can be NULL)
                first_name TEXT NOT NULL,             -- User's first name
                created_at TEXT NOT NULL,             -- Timestamp of first /start
                timezone TEXT DEFAULT NULL,           -- IANA timezone name (e.g., 'Asia/Almaty')
                last_daily_report_sent_date TEXT DEFAULT NULL, -- Tracks last sent report date (YYYY-MM-DD)
                poll_start_hour INTEGER DEFAULT 8,    -- Start hour for activity polling (local time)
                poll_end_hour INTEGER DEFAULT 22,     -- End hour for activity polling (local time)
                report_time_hour INTEGER DEFAULT 8      -- Preferred hour for daily report (local time)
            )
        """)

        # Activities table: Stores logged activities
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                activity_id INTEGER PRIMARY KEY AUTOINCREMENT, -- Unique ID for each activity
                user_id INTEGER NOT NULL,                      -- Link to the user
                timestamp TEXT NOT NULL,                       -- Timestamp (UTC ISO format) when logged
                description TEXT NOT NULL,                     -- User's activity description
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
        """)

        con.commit()
        logger.info("Database table structure check/creation complete.")
    except sqlite3.Error as e:
        logger.error(f"Error creating/updating tables: {e}")
        con.rollback()  # Rollback changes if table creation fails
        raise


# --- Public Database Functions ---

def initialize_database():
    """Initializes the database by ensuring connection and creating tables."""
    logger.info(f"Initializing database at '{DB_PATH}'...")
    try:
        con = _get_db_connection()
        _create_tables(con)
        con.close()
        logger.info("Database initialization finished successfully.")
    except Exception as e:
        # Log critical error if DB init fails, as bot likely cannot run
        logger.critical(
            f"Critical error during database initialization: {e}", exc_info=True
        )
        raise  # Stop bot startup


def add_user_if_not_exists(user_id: int, username: str | None, first_name: str):
    """
    Adds a user to the database if they don't already exist.
    Initializes settings with default values.

    Args:
        user_id: The user's Telegram ID.
        username: The user's Telegram username (can be None).
        first_name: The user's first name.
    """
    # INSERT OR IGNORE attempts to insert, but does nothing if user_id already exists
    sql = """
        INSERT OR IGNORE INTO users (
            user_id, telegram_username, first_name, created_at,
            timezone, last_daily_report_sent_date, poll_start_hour,
            poll_end_hour, report_time_hour
        )
        VALUES (?, ?, ?, ?, NULL, NULL, 8, 22, 8) -- Set default values here
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
                f"New user user_id={user_id}, username={username} added to DB."
            )
        else:
            logger.debug(
                f"User user_id={user_id}, username={username} already exists."
            )
    except sqlite3.Error as e:
        logger.error(
            f"Error adding/checking user user_id={user_id} in DB: {e}"
        )
    finally:
        if con:
            con.close()


def update_user_timezone(user_id: int, timezone_str: str | None) -> bool:
    """
    Updates the timezone for a given user.

    Args:
        user_id: The user's Telegram ID.
        timezone_str: The IANA timezone name string (or None).

    Returns:
        True if the update was successful (affected 1 row), False otherwise.
    """
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
                f"Timezone for user {user_id} updated to '{timezone_str}'."
            )
        else:
            logger.warning(
                f"Could not update timezone for user {user_id} (user not found?)."
            )
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error updating timezone for user {user_id}: {e}"
        )
        if con:
            con.rollback()
        success = False
    finally:
        if con:
            con.close()
    return success


def get_user_timezone_str(user_id: int) -> str | None:
    """
    Gets the timezone string (IANA name) for a given user.

    Args:
        user_id: The user's Telegram ID.

    Returns:
        The timezone string if set, otherwise None.
    """
    sql = "SELECT timezone FROM users WHERE user_id = ?"
    timezone_str = None
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id,))
        result = cur.fetchone()
        if result and result[0]:
            timezone_str = result[0]
        logger.debug(
            f"Timezone for user {user_id}: '{timezone_str if timezone_str else 'Not set'}'."
        )
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error retrieving timezone for user {user_id}: {e}"
        )
    finally:
        if con:
            con.close()
    return timezone_str


def get_all_user_ids_with_tz() -> list[int]:
    """Returns a list of unique user_ids that have a timezone set."""
    user_ids = []
    sql = "SELECT user_id FROM users WHERE timezone IS NOT NULL AND timezone != ''"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql)
        results = cur.fetchall()
        user_ids = [row[0] for row in results]
        logger.info(f"Found {len(user_ids)} users with timezone set.")
    except sqlite3.Error as e:
        logger.error(f"SQLite error retrieving users with timezone: {e}")
    finally:
        if con:
            con.close()
    return user_ids


def get_last_report_sent_date(user_id: int) -> str | None:
    """
    Gets the last date string ('YYYY-MM-DD') for which a daily report was sent.

    Args:
        user_id: The user's Telegram ID.

    Returns:
        The date string if found, otherwise None.
    """
    sql = "SELECT last_daily_report_sent_date FROM users WHERE user_id = ?"
    date_str = None
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id,))
        result = cur.fetchone()
        if result and result[0]:
            date_str = result[0]
        logger.debug(
            f"Last report sent date for user {user_id}: {date_str if date_str else 'Never'}"
        )
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error getting last report sent date for user {user_id}: {e}"
        )
    finally:
        if con:
            con.close()
    return date_str


def update_last_report_sent_date(user_id: int, date_str: str) -> bool:
    """
    Updates the last sent report date for the user.

    Args:
        user_id: The user's Telegram ID.
        date_str: The date string ('YYYY-MM-DD') to set.

    Returns:
        True if successful, False otherwise.
    """
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
                f"Updated last report sent date for user {user_id} to {date_str}."
            )
        else:
            # This might happen if the user was deleted between job start and update
            logger.warning(
                f"Could not update last report sent date for user {user_id}."
            )
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error updating last report sent date for user {user_id}: {e}"
        )
        if con:
            con.rollback()
        success = False
    finally:
        if con:
            con.close()
    return success


def save_activity_to_db(
        user_id: int, description: str, timestamp: datetime
) -> int | None:
    """
    Saves an activity record to the database.

    Args:
        user_id: The user's Telegram ID.
        description: The activity description text.
        timestamp: The UTC timestamp (as datetime object) when activity was logged.

    Returns:
        The activity_id of the newly inserted row, or None on error.
    """
    # Timestamp should be timezone-aware (UTC) before calling isoformat()
    sql = "INSERT INTO activities (user_id, description, timestamp) VALUES (?, ?, ?)"
    activity_id = None
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, description, timestamp.isoformat()))
        activity_id = cur.lastrowid
        con.commit()
        logger.info(
            f"Activity '{description[:20]}...' for user {user_id} saved "
            f"with ID {activity_id} at {timestamp.isoformat()}."
        )
    except sqlite3.Error as e:
        logger.error(f"Error saving activity for user {user_id} to DB: {e}")
        activity_id = None
    finally:
        if con:
            con.close()
    return activity_id


def get_activities_for_day(
        user_id: int, report_date: str
) -> list[tuple[int, str, str]]:
    """
    Retrieves activities for a specific user and date.

    Args:
        user_id: The user's Telegram ID.
        report_date: The date string in 'YYYY-MM-DD' format.

    Returns:
        A list of tuples (activity_id, timestamp_str_utc, description),
        ordered by timestamp. Returns empty list on error or if no data.
    """
    activities_list = []
    # Select activity_id needed for the edit feature
    sql = """
        SELECT activity_id, timestamp, description
        FROM activities
        WHERE user_id = ? AND DATE(timestamp) = ?
        ORDER BY timestamp ASC
    """
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, report_date))
        activities_list = cur.fetchall()
        logger.info(
            f"Found {len(activities_list)} activities for user {user_id} "
            f"on date {report_date}."
        )
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error retrieving activities for user {user_id} "
            f"on date {report_date}: {e}"
        )
        activities_list = []  # Ensure empty list on error
    finally:
        if con:
            con.close()
    return activities_list


def update_activity_description(
        activity_id: int, user_id: int, new_description: str
) -> bool:
    """
    Updates the description of a specific activity for a specific user.

    Args:
        activity_id: The ID of the activity to update.
        user_id: The Telegram ID of the user owning the activity.
        new_description: The new description text.

    Returns:
        True if the update was successful (affected 1 row), False otherwise.
    """
    sql = """
        UPDATE activities
        SET description = ?
        WHERE activity_id = ? AND user_id = ?
    """
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
                f"Activity ID {activity_id} for user {user_id} updated."
            )
        else:
            # Could be wrong activity_id or wrong user_id
            logger.warning(
                f"Attempted update for activity ID {activity_id} / user {user_id} "
                f"affected 0 rows."
            )
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error updating activity ID {activity_id} for user {user_id}: {e}"
        )
        if con:
            con.rollback()
        updated = False
    finally:
        if con:
            con.close()
    return updated


def get_user_poll_window(user_id: int) -> tuple[int, int] | None:
    """
    Gets the custom polling window (start_hour, end_hour) for the user.

    Args:
        user_id: The user's Telegram ID.

    Returns:
        A tuple (start_hour, end_hour) if set and valid, otherwise None.
    """
    sql = "SELECT poll_start_hour, poll_end_hour FROM users WHERE user_id = ?"
    window = None
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id,))
        result = cur.fetchone()
        if result and result[0] is not None and result[1] is not None:
            # Basic validation
            start_h, end_h = int(result[0]), int(result[1])
            if 0 <= start_h < end_h <= 23:
                window = (start_h, end_h)
            else:
                logger.warning(
                    f"Invalid poll window ({start_h}-{end_h}) found in DB for user {user_id}.")
        logger.debug(
            f"Poll window for user {user_id}: "
            f"{f'{window[0]}-{window[1]}' if window else 'Not set/Invalid (using defaults)'}."
        )
    except (sqlite3.Error, ValueError) as e:
        logger.error(
            f"Error retrieving/parsing poll window for user {user_id}: {e}"
        )
    finally:
        if con:
            con.close()
    return window


def update_user_poll_window(user_id: int, start_hour: int, end_hour: int) -> bool:
    """
    Updates the polling window start and end hours for the user.
    Assumes hours are already validated (0-23, start < end).

    Args:
        user_id: The user's Telegram ID.
        start_hour: The hour polling should start.
        end_hour: The hour polling should end.

    Returns:
        True if successful, False otherwise.
    """
    sql = "UPDATE users SET poll_start_hour = ?, poll_end_hour = ? WHERE user_id = ?"
    success = False
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (start_hour, end_hour, user_id))
        con.commit()
        if cur.rowcount > 0:
            success = True
            logger.info(
                f"Poll window for user {user_id} updated to {start_hour}-{end_hour}."
            )
        else:
            logger.warning(
                f"Could not update poll window for user {user_id} (user not found?)."
            )
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error updating poll window for user {user_id}: {e}"
        )
        if con:
            con.rollback()
        success = False
    finally:
        if con:
            con.close()
    return success


def get_user_report_hour(user_id: int) -> int | None:
    """
    Gets the preferred report hour (0-23) for the user.

    Args:
        user_id: The user's Telegram ID.

    Returns:
        The hour (int) if set and valid, otherwise None.
    """
    sql = "SELECT report_time_hour FROM users WHERE user_id = ?"
    hour = None
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id,))
        result = cur.fetchone()
        if result and result[0] is not None:
            # Basic validation
            h = int(result[0])
            if 0 <= h <= 23:
                hour = h
            else:
                logger.warning(
                    f"Invalid report hour ({h}) found in DB for user {user_id}.")
        logger.debug(
            f"Report hour for user {user_id}: "
            f"{hour if hour is not None else 'Not set/Invalid (using default)'}."
        )
    except (sqlite3.Error, ValueError) as e:
        logger.error(
            f"Error retrieving/parsing report hour for user {user_id}: {e}"
        )
    finally:
        if con:
            con.close()
    return hour


def update_user_report_hour(user_id: int, hour: int) -> bool:
    """
    Updates the preferred daily report hour for the user.
    Assumes hour is already validated (0-23).

    Args:
        user_id: The user's Telegram ID.
        hour: The preferred hour (0-23).

    Returns:
        True if successful, False otherwise.
    """
    sql = "UPDATE users SET report_time_hour = ? WHERE user_id = ?"
    success = False
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (hour, user_id))
        con.commit()
        if cur.rowcount > 0:
            success = True
            logger.info(f"Report hour for user {user_id} updated to {hour}.")
        else:
            logger.warning(
                f"Could not update report hour for user {user_id} (user not found?)."
            )
    except sqlite3.Error as e:
        logger.error(
            f"SQLite error updating report hour for user {user_id}: {e}"
        )
        if con:
            con.rollback()
        success = False
    finally:
        if con:
            con.close()
    return success
