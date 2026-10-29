import os
import re
from typing import Any
from uuid import uuid4

import mysql.connector
from mysql.connector import IntegrityError

from utils.security import hash_password, verify_password


class DatabaseConfigurationError(ValueError):
    pass


class EmailAlreadyRegistered(ValueError):
    pass


def _connection_settings() -> dict[str, Any]:
    required = ("MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise DatabaseConfigurationError(
            "Set " + ", ".join(missing) + " in your project .env file."
        )
    try:
        port = int(os.getenv("MYSQL_PORT", "3306"))
    except ValueError as error:
        raise DatabaseConfigurationError("MYSQL_PORT must be a number.") from error
    if not 1 <= port <= 65535:
        raise DatabaseConfigurationError("MYSQL_PORT must be between 1 and 65535.")

    database = os.environ["MYSQL_DATABASE"].strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", database):
        raise DatabaseConfigurationError(
            "MYSQL_DATABASE may contain only letters, numbers, and underscores."
        )
    username = os.environ["MYSQL_USER"].strip()
    if not username:
        raise DatabaseConfigurationError("MYSQL_USER must not be empty.")
    return {
        "host": os.getenv("MYSQL_HOST", "localhost").strip(),
        "port": port,
        "database": database,
        "user": username,
        "password": os.environ["MYSQL_PASSWORD"],
        "connection_timeout": 10,
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
    }


def _connect() -> Any:
    return mysql.connector.connect(**_connection_settings())


def initialize_database() -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS app_users (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(254) NOT NULL UNIQUE,
            display_name VARCHAR(80) NOT NULL,
            bio VARCHAR(500) NOT NULL DEFAULT '',
            preferred_language VARCHAR(40) NOT NULL DEFAULT 'English',
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS stories (
            id CHAR(32) NOT NULL PRIMARY KEY,
            user_id BIGINT UNSIGNED NOT NULL,
            title VARCHAR(120) NOT NULL,
            scenario TEXT NOT NULL,
            story MEDIUMTEXT NOT NULL,
            language VARCHAR(40) NOT NULL,
            style VARCHAR(40) NOT NULL,
            word_limit SMALLINT UNSIGNED NOT NULL,
            paragraph_count TINYINT UNSIGNED NOT NULL,
            voice VARCHAR(30) NOT NULL,
            image_path VARCHAR(500) NOT NULL,
            audio_path VARCHAR(500) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_stories_user FOREIGN KEY (user_id)
                REFERENCES app_users(id) ON DELETE CASCADE,
            INDEX idx_stories_user_created (user_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
    )
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            for statement in statements:
                cursor.execute(statement)
            connection.commit()
        finally:
            cursor.close()
    finally:
        connection.close()


def register_user(email: str, display_name: str, password: str) -> int:
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO app_users (email, display_name, password_hash)
                VALUES (%s, %s, %s)
                """,
                (email.strip().lower(), display_name.strip(), hash_password(password)),
            )
            connection.commit()
            return int(cursor.lastrowid)
        except IntegrityError as error:
            connection.rollback()
            if error.errno == 1062:
                raise EmailAlreadyRegistered(
                    "An account with this email already exists."
                ) from error
            raise
        finally:
            cursor.close()
    finally:
        connection.close()


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    connection = _connect()
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT id, email, display_name, bio, preferred_language, password_hash
                FROM app_users WHERE email = %s
                """,
                (email.strip().lower(),),
            )
            user = cursor.fetchone()
        finally:
            cursor.close()
    finally:
        connection.close()
    if not user or not verify_password(password, user["password_hash"]):
        return None
    user["id"] = int(user["id"])
    user.pop("password_hash")
    return user


def update_profile(
    user_id: int,
    display_name: str,
    bio: str,
    preferred_language: str,
) -> None:
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE app_users
                SET display_name = %s, bio = %s, preferred_language = %s
                WHERE id = %s
                """,
                (display_name.strip(), bio.strip(), preferred_language, user_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
    finally:
        connection.close()


def create_story(
    user_id: int,
    title: str,
    scenario: str,
    story: str,
    language: str,
    style: str,
    word_limit: int,
    paragraph_count: int,
    voice: str,
    image_path: str,
    audio_path: str,
) -> str:
    story_id = uuid4().hex
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO stories (
                    id, user_id, title, scenario, story, language, style, word_limit,
                    paragraph_count, voice, image_path, audio_path
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    story_id, user_id, title.strip(), scenario, story, language, style,
                    word_limit, paragraph_count, voice, image_path, audio_path,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
    finally:
        connection.close()
    return story_id


def list_stories(
    user_id: int,
    search: str = "",
    language: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    conditions = ["user_id = %s"]
    values: list[Any] = [user_id]
    if search.strip():
        term = (
            "%"
            + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        conditions.append("(title LIKE %s OR scenario LIKE %s OR story LIKE %s)")
        values.extend((term, term, term))
    if language:
        conditions.append("language = %s")
        values.append(language)
    connection = _connect()
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            query = f"""
                SELECT id, title, scenario, story, language, style, word_limit,
                       paragraph_count, voice, image_path, audio_path, created_at
                FROM stories
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at DESC
            """
            if limit is not None:
                if limit < 1:
                    raise ValueError("Story list limit must be positive.")
                query += " LIMIT %s"
                values.append(limit)
            cursor.execute(query, tuple(values))
            return list(cursor.fetchall())
        finally:
            cursor.close()
    finally:
        connection.close()


def count_stories(user_id: int) -> int:
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM stories WHERE user_id = %s",
                (user_id,),
            )
            result = cursor.fetchone()
            return int(result[0])
        finally:
            cursor.close()
    finally:
        connection.close()


def get_story(user_id: int, story_id: str) -> dict[str, Any] | None:
    connection = _connect()
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT id, title, scenario, story, language, style, word_limit,
                       paragraph_count, voice, image_path, audio_path, created_at
                FROM stories
                WHERE user_id = %s AND id = %s
                """,
                (user_id, story_id),
            )
            return cursor.fetchone()
        finally:
            cursor.close()
    finally:
        connection.close()


def rename_story(user_id: int, story_id: str, title: str) -> bool:
    connection = _connect()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM stories WHERE id = %s AND user_id = %s",
                (story_id, user_id),
            )
            if cursor.fetchone() is None:
                connection.rollback()
                return False
            cursor.execute(
                "UPDATE stories SET title = %s WHERE id = %s AND user_id = %s",
                (title.strip(), story_id, user_id),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
    finally:
        connection.close()


def delete_story(user_id: int, story_id: str) -> dict[str, str] | None:
    connection = _connect()
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT image_path, audio_path FROM stories
                WHERE id = %s AND user_id = %s
                """,
                (story_id, user_id),
            )
            paths = cursor.fetchone()
            if not paths:
                connection.rollback()
                return None
            cursor.execute(
                "DELETE FROM stories WHERE id = %s AND user_id = %s",
                (story_id, user_id),
            )
            connection.commit()
            return paths
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
    finally:
        connection.close()
