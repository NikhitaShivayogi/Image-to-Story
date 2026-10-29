# Image to Story

A Flask application that turns a photo into a multilingual story and narrated
audio. The existing MySQL account/story data layer, password hashing, OpenAI
generation, and per-user media organization are retained.

## Features

- Flask web interface with sign-up, sign-in, profile, and sign-out.
- Public product homepage for visitors and a personalized dashboard after sign-in.
- Private MySQL-backed story library with search and language filters.
- Stories in English, Hindi, Kannada, Tamil, Telugu, and Malayalam.
- Reflective, educational, heartwarming, adventure, inspirational, and bedtime
  story styles, with user-selected length, paragraph count, and narration voice.
- Story rename/delete, private image/audio playback, and downloads.
- Photos and narration stored in separate per-user `uploads/` and `outputs/`
  folders.
- CSRF protection for form submissions and ownership checks on private media.

## Setup on Windows

Requirements: Python 3.10+ and MySQL Server 8.

1. Open PowerShell in the project folder and create/activate a virtual
   environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Set up MySQL. Open `database\setup.sql` and replace
   `REPLACE_WITH_A_STRONG_PASSWORD` with a strong password for the app database
   user. Generate a safe random value with:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(24))"
   ```

   Use that same value in the SQL script and later in `.env`. Then run:

   ```powershell
   cmd /c "mysql -u root -p < database\setup.sql"
   ```

   The command prompts for your MySQL administrator password. It does not
   change the administrator password. If the app database user already
   exists, the script updates that app user's password to the value in the
   script so it can resolve a stale password mismatch.

3. Configure the project `.env` file. Keep any existing API keys and fill in
   the following MySQL and Flask settings (the project `.env.example` shows the
   same names):

   ```dotenv
   MYSQL_HOST=localhost
   MYSQL_PORT=3306
   MYSQL_DATABASE=image_to_story
   MYSQL_USER=image_to_story_app
   MYSQL_PASSWORD=paste_the_password_used_in_setup_sql
   FLASK_SECRET_KEY=paste_a_different_random_secret
   ```

   Generate the Flask secret separately using the same Python command above.
   Never use the example text as a real password or secret, and do not share
   your `.env` file.

4. Validate the Python files:

   ```powershell
   python -m compileall -q app.py utils
   ```

   No output and exit code `0` means syntax validation passed.

5. Start the Flask app:

   ```powershell
   python app.py
   ```

   Open `http://127.0.0.1:5000` for the public homepage. After signing in,
   the personalized home dashboard shows your story count, preferred language,
   and recent creations. Stop the local server with **Ctrl+C** in the PowerShell
   window.

## Media folders

```text
uploads/
  <user-id>/
    photo_<unique-id>.<jpg|png|webp>
outputs/
  <user-id>/
    narration_<unique-id>.mp3
```

The database stores each user's story metadata and relative media paths.
Existing files directly under the root `uploads/` or `outputs/` folders are
legacy files and are not moved or deleted automatically.

OpenAI is used for image understanding, story writing, and text-to-speech.
API usage may incur charges under the key configured in `.env`.

This local setup is intended for development. Public deployment needs HTTPS,
a durable `FLASK_SECRET_KEY`, account recovery and verification, rate limiting,
and private object storage rather than local disk.
