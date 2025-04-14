import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

DB_FOLDER = "data"
DB_NAME = "activities.db"
DB_PATH = os.path.join(DB_FOLDER, DB_NAME)


def _get_db_connection():
    """ Creating a database if not exists, used only in this code """
    try:
        if not os.path.exists(DB_FOLDER):
            os.makedirs(DB_FOLDER)
            logger.info(f"{DB_FOLDER} is created for database")

        con = sqlite3.connect(DB_PATH) # creates an object
        con.execute("pragma foreign_keys = on;")
        return con # return the object
    except sqlite3.Error as e:
        logger.error(f"Database initializing failed: {e}")
        raise
    except OSError as e:
        logger.error(f"Data folder creation is failed: {e}")
        raise


def _create_tables(con: sqlite3.Connection):
    """ Creating tables if not exists, used only in this code """
    try:
        cur = con.cursor()
        cur.execute("""
            create table if not exists users (
                user_id integer primary key,
                telegram_username text,
                first_name text not null,
                created_at text
            )
        """)
        logger.debug("'users' table is created/checked")

        cur.execute("""
            create table if not exists tags (
                tag_id integer primary key autoincrement,
                user_id integer not null,
                tag_name text not null collate nocase,
                foreign key (user_id) references users (user_id) on delete cascade,
                unique (user_id, tag_name)
            )
        """)
        logger.debug("'tags' table is created/checked")

        cur.execute("""
            create table if not exists activities (
                activity_id integer primary key autoincrement,
                user_id integer not null,
                timestamp text not null,
                description text not null,
                foreign key (user_id) references users (user_id) on delete cascade
            )
        """)
        logger.debug("'activities' table is created/checked")

        cur.execute("""
            create table if not exists activity_tags (
                activity_id integer not null,
                tag_id integer not null,
                foreign key (activity_id) references activities (activity_id) on delete cascade,
                foreign key (tag_id) references tags (tag_id) on delete cascade,
                primary key (activity_id, tag_id)
            )
        """)
        logger.debug("'activities' table is created/checked")

        con.commit()
        logger.info("A database structure is created/checked succesfully")
    except sqlite3.Error as e:
        logger.error(f"Tables creation is failed: {e}")
        con.rollback()
        raise


def initialize_database():
    """ initializing database, used in other code """
    logger.info(f"Initialization of '{DB_PATH}' database is started")
    try:
        con = _get_db_connection() # gets the object of sqlite3
        _create_tables(con) # checks whether tables exist, if not tables wil be created
        con.close()
        logger.info("Database is initialized successfully")
    except Exception as e:
        logger.critical(f"Critical error in database initialization: {e}")
        raise


def save_activity_to_db(user_id: int, description: str, timestamp: datetime) -> int | None:
    sql = "insert into activities (user_id, description, timestamp) values (?, ?, ?)"
    activity_id = None
    try:
        con = _get_db_connection() # gets the object of sqlite3
        cur = con.cursor() # checks whether tables exist, if not tables wil be created
        cur.execute(sql, (user_id, description, timestamp.isoformat()))
        activity_id = cur.lastrowid # the most recent added activity_id
        con.commit()
        con.close()
        logger.info(
            f"The activity '{description[:20]}...' for user {user_id} is saved with id: {activity_id}")
        return activity_id
    except sqlite3.Error as e:
        logger.error(
            f"Saving an activity for user {user_id} to database is failed: {e}")
        if con:
            con.close()
        return None


def add_user_if_not_exists(user_id: int, username: str | None, first_name: str):
    """ adds user_id so it can be used in activities table """
    
    sql = """
        insert or ignore into users (user_id, telegram_username, first_name, created_at)
        values (?, ?, ?, ?)
    """
    now_iso = datetime.now().isoformat()

    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, username, first_name, now_iso))
        con.commit()

        if cur.rowcount > 0:
            logger.info(f"New user with user_id = {user_id}, username = {username} is added to database")
        else:
            logger.debug(f"The user with user_id = {user_id}, username = {username} already exists in database")
        con.close()
    except sqlite3.Error as e:
        logger.error(f"Adding/checking user {user_id} is failed in database: {e}")
        if con: con.close()

def add_tag(user_id: int, tag_name: str) -> int | None:
    """ adds user created tag to db and returns tag_id of that tag """

    tag_name_lower = tag_name.lower()
    tag_id = None

    sql_insert = "insert into tags (user_id, tag_name) values (?, ?)"
    sql_select = "select tag_id from tags where user_id = ? and tag_name = ?"

    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()

        cur.execute(sql_insert, (user_id, tag_name_lower))
        tag_id = cur.lastrowid
        con.commit()
        logger.info(f"New tag '{tag_name_lower}' is added for user {user_id} with tag_id {tag_id}")
        con.close()
        return tag_id
    
    except sqlite3.IntegrityError:
        logger.info(f"The tag '{tag_name_lower}' already exists for user {user_id}. Getting tag_id")
        if con:
            cur = con.cursor()
            try:
                cur.execute(sql_select, (user_id, tag_name_lower))
                result = cur.fetchone()
                if result:
                    tag_id = result[0]
                    logger.info(f"The tag {tag_name_lower} is found for user {user_id}, which has tag_id {tag_id}")
                    con.close()
                    return tag_id
                else:
                    # weird situation: tag exists because of IntegrityError; however select query cannot find tag_id
                    logger.error(f"The tag {tag_name_lower} is not found for user {user_id} after IntegrityError")
                    con.close()
                    return None
            except sqlite3.Error as select_e:
                logger.error(f"Select query for tag {tag_name_lower} is failed: {select.e}")
                if con: con.close()
                return None
        else:
            logger.error(f"Connection with database is closed before select query")
            return None
    except sqlite3.Error as e:
        logger.error(f"SQLite error occured, while adding the tag {tag_name_lower} for user {user_id}: {e}")
        if con: con.rollback(); con.close()
        return None

def get_tag_id(user_id: int, tag_name: str) -> int | None:
    """ searches tag and returns tag_id """
    tag_id = None
    sql = "select tag_id from tags where user_id = ? and tag_name = LOWER(?)"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, tag_name.lower()))
        result = cur.fetchone()
        con.close()
        if result:
            tag_id = result[0]
            logger.debug(f"A tag_id {tag_id} for the tag '{tag_name}' is found for user {user_id}")
        else:
            logger.debug(f"A tag '{tag_name}' is not found for user {user_id}")
        return tag_id
    
    except sqlite3.Error as e:
        logger.error(f"SQLite error occured, while searching the tag {tag_name_lower} for user {user_id}: {e}")
        if con: con.close()
        return None


def link_activity_tag(activity_id: int, tag_id: int):
    """ links activity to its tag in activity_tags table """

    sql = "insert or ignore into activity_tags (activity_id, tag_id) values (?, ?)"
    success = False
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (activity_id, tag_id))
        con.commit()

        if cur.rowcount > 0:
            logger.info(f"Link is created: activity_id={activity_id}, tag_id={tag_id}")
        else:
            logger.info(f"The link activity_id={activity_id}, tag_id={tag_id} is already exists or not yet created")
        con.close()
        success = True
    except sqlite3.Error as e:
        logger.error(f"SQLite error occured, while linking activity {activity_id} and tag {tag_id}: {e}")
        if con: con.rollback(); con.close()
        success = False
    return success


def get_user_tags(user_id: int) -> list[str]:
    """ returns user created tags in list from database """
    
    tags_list = []
    sql = "select tag_name from tags where user_id = ? order by tag_name"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id,))
        results = cur.fetchall()
        con.close()

        tags_list = [row[0] for row in results]
        logger.info(f"Got {len(tags_list)} tags for user {user_id}")
        return tags_list
    except sqlite3.Error as e:
        logger.error(f"SQLite error occured for user {user_id}: {e}")
        if con: con.close()
        return []

def delete_tag(user_id: int, tag_name: str) -> bool:
    """ returns true if tag is deleted successfully, else false """

    tag_name_lower = tag_name.lower()
    deleted = False
    sql = "delete from tags where user_id = ? and tag_name = ?"
    con = None
    try:
        con = _get_db_connection()
        cur = con.cursor()
        cur.execute(sql, (user_id, tag_name_lower))
        con.commit()
    
        if cur.rowcount > 0:
            deleted = True
            logger.info(f"Tag '{tag_name_lower} for user {user_id} is deleted")
        else:
            logger.warning(f"Attempt to delete the tag '{tag_name_lower} for user {user_id}, but it is not found")
        con.close()
        return deleted
    
    except sqlite3.Error as e:
        logger.error(f"SQLite error occured while deleting tag '{tag_name_lower} for user {user_id}: {e}")
        if con: con.rollback(); con.close()
        return False