CREATE DATABASE IF NOT EXISTS image_to_story
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- Replace this placeholder with a strong local password before running.
CREATE USER IF NOT EXISTS 'image_to_story_app'@'localhost'
    IDENTIFIED BY 'REPLACE_WITH_A_STRONG_PASSWORD';

ALTER USER 'image_to_story_app'@'localhost'
    IDENTIFIED BY 'REPLACE_WITH_A_STRONG_PASSWORD';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, ALTER
    ON image_to_story.*
    TO 'image_to_story_app'@'localhost';

FLUSH PRIVILEGES;
