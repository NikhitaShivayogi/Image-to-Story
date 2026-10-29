import mimetypes
import os
import re
import secrets
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeGuard, TypeVar
from uuid import uuid4

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from mysql.connector import Error as MySQLError
from openai import OpenAIError
from werkzeug.utils import secure_filename

from utils.database import (
    DatabaseConfigurationError,
    EmailAlreadyRegistered,
    authenticate_user,
    count_stories,
    create_story,
    delete_story,
    get_story,
    initialize_database,
    list_stories,
    register_user,
    rename_story,
    update_profile,
)
from utils.generation import (
    VoiceName,
    generate_speech_from_text,
    generate_story_from_text,
    generate_text_from_image,
)
from utils.storage import resolve_user_asset_path, user_asset_directory

PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")

LANGUAGES = ("English", "Hindi", "Kannada", "Tamil", "Telugu", "Malayalam")
STORY_STYLES = (
    "Reflective",
    "Educational",
    "Heartwarming",
    "Adventure",
    "Inspirational",
    "Bedtime",
)
VOICE_OPTIONS: dict[str, VoiceName] = {
    "Alloy · balanced": "alloy",
    "Nova · warm": "nova",
    "Shimmer · gentle": "shimmer",
    "Onyx · expressive": "onyx",
}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
T = TypeVar("T", bound=Callable[..., Any])


def _is_voice_name(value: str) -> TypeGuard[VoiceName]:
    return value in VOICE_OPTIONS.values()


def _database_setup_message(error: Exception) -> str:
    if isinstance(error, DatabaseConfigurationError):
        return str(error)
    if isinstance(error, MySQLError):
        if error.errno == 1045:
            return (
                "MySQL denied the configured account (error 1045). Set "
                "MYSQL_USER=image_to_story_app and make MYSQL_PASSWORD match the "
                "app-user password in database\\setup.sql. Run that SQL script "
                "using your MySQL administrator account."
            )
        return (
            f"MySQL could not connect (error {error.errno}). Check that the server "
            "is running and that MYSQL_HOST, MYSQL_PORT, and MYSQL_DATABASE are correct."
        )
    return "MySQL could not connect. Check the local database setup and try again."


def _ensure_database(application: Flask) -> None:
    if not application.config["DATABASE_READY"]:
        initialize_database()
        application.config["DATABASE_READY"] = True


def create_app() -> Flask:
    application = Flask(__name__)
    application.config.update(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024 + 128 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        DATABASE_READY=False,
    )

    @application.context_processor
    def inject_template_helpers() -> dict[str, Callable[[], str]]:
        return {"csrf_token": _csrf_token}

    @application.before_request
    def prepare_request() -> Any:
        if request.endpoint == "static":
            return None

        session.setdefault("_csrf_token", secrets.token_urlsafe(32))
        if request.method == "POST":
            submitted_token = request.form.get("_csrf_token", "")
            if not secrets.compare_digest(
                submitted_token, str(session.get("_csrf_token", ""))
            ):
                abort(400, description="The form expired. Reload the page and try again.")

        return None

    def login_required(view: T) -> T:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not isinstance(session.get("user"), dict):
                flash("Sign in to continue.", "info")
                return redirect(url_for("login"))
            try:
                _ensure_database(application)
            except (DatabaseConfigurationError, MySQLError) as error:
                return render_template(
                    "database_unavailable.html",
                    setup_error=_database_setup_message(error),
                ), 503
            return view(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    @application.get("/")
    def index() -> Any:
        if session.get("user"):
            return redirect(url_for("dashboard"))
        return render_template("home.html", languages=LANGUAGES)

    @application.get("/dashboard")
    @login_required
    def dashboard() -> Any:
        user = session["user"]
        user_id = int(user["id"])
        return render_template(
            "dashboard.html",
            saved_count=count_stories(user_id),
            recent_stories=list_stories(user_id, limit=4),
            languages=LANGUAGES,
        )

    @application.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        if session.get("user"):
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            if not email or not password:
                flash("Enter your email and password.", "error")
            else:
                try:
                    _ensure_database(application)
                    user = authenticate_user(email, password)
                except (DatabaseConfigurationError, MySQLError) as error:
                    return render_template(
                        "login.html",
                        database_message=_database_setup_message(error),
                    ), 503
                if user is None:
                    flash("The email or password is incorrect.", "error")
                else:
                    session.clear()
                    session["user"] = user
                    session["_csrf_token"] = secrets.token_urlsafe(32)
                    flash(f"Welcome back, {user['display_name']}.", "success")
                    return redirect(url_for("dashboard"))
        return render_template("login.html")

    @application.route("/signup", methods=["GET", "POST"])
    def signup() -> Any:
        if session.get("user"):
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            display_name = request.form.get("display_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirmation = request.form.get("confirm_password", "")

            if not display_name:
                flash("Enter a name for your profile.", "error")
            elif len(display_name) > 80:
                flash("Your name must be 80 characters or fewer.", "error")
            elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                flash("Enter a valid email address.", "error")
            elif len(password) < 12:
                flash("Use a password with at least 12 characters.", "error")
            elif password != confirmation:
                flash("The passwords do not match.", "error")
            else:
                try:
                    _ensure_database(application)
                    user_id = register_user(email, display_name, password)
                    session.clear()
                    session["user"] = {
                        "id": user_id,
                        "email": email,
                        "display_name": display_name,
                        "bio": "",
                        "preferred_language": "English",
                    }
                    session["_csrf_token"] = secrets.token_urlsafe(32)
                    flash("Your account is ready. Let’s create a story.", "success")
                    return redirect(url_for("dashboard"))
                except EmailAlreadyRegistered as error:
                    flash(str(error), "error")
                except (DatabaseConfigurationError, MySQLError) as error:
                    return render_template(
                        "signup.html",
                        database_message=_database_setup_message(error),
                    ), 503
        return render_template("signup.html")

    @application.post("/logout")
    def logout() -> Any:
        if not isinstance(session.get("user"), dict):
            return redirect(url_for("index"))
        session.clear()
        flash("You have signed out.", "info")
        return redirect(url_for("index"))

    @application.route("/create", methods=["GET", "POST"])
    @login_required
    def create_story_page() -> Any:
        user = session["user"]
        if request.method == "GET":
            return render_template(
                "create.html",
                languages=LANGUAGES,
                styles=STORY_STYLES,
                voices=VOICE_OPTIONS,
                saved_count=count_stories(int(user["id"])),
            )

        if not os.getenv("OPENAI_API_KEY"):
            flash("Add OPENAI_API_KEY to your .env file before generating stories.", "error")
            return redirect(url_for("create_story_page"))

        image = request.files.get("photo")
        if image is None or not image.filename:
            flash("Choose a photo to create your story.", "error")
            return redirect(url_for("create_story_page"))
        extension = Path(secure_filename(image.filename)).suffix.lower()
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            flash("Choose a JPG, PNG, or WEBP image.", "error")
            return redirect(url_for("create_story_page"))

        language = request.form.get("language", "")
        style = " ".join(request.form.get("style", "").split())
        voice = request.form.get("voice", "")
        try:
            word_limit = int(request.form.get("word_limit", "120"))
            paragraph_count = int(request.form.get("paragraph_count", "2"))
        except ValueError:
            flash("Choose a valid story length and paragraph count.", "error")
            return redirect(url_for("create_story_page"))
        if (
            language not in LANGUAGES
            or not style
            or len(style) > 40
            or not _is_voice_name(voice)
        ):
            flash("One or more story settings are invalid. Please try again.", "error")
            return redirect(url_for("create_story_page"))
        if not 50 <= word_limit <= 500 or not 1 <= paragraph_count <= 5:
            flash("Story length must be 50–500 words and paragraphs 1–5.", "error")
            return redirect(url_for("create_story_page"))
        user_id = int(user["id"])
        run_id = uuid4().hex
        image_directory = user_asset_directory(PROJECT_DIR, "uploads", user_id)
        audio_directory = user_asset_directory(PROJECT_DIR, "outputs", user_id)
        image_path = image_directory / f"photo_{run_id}{extension}"
        audio_path = audio_directory / f"narration_{run_id}.mp3"

        try:
            image_directory.mkdir(parents=True, exist_ok=True)
            audio_directory.mkdir(parents=True, exist_ok=True)
            image.save(image_path)
            scenario = generate_text_from_image(str(image_path), language)
            story = generate_story_from_text(
                scenario, language, word_limit, style, paragraph_count
            )
            generate_speech_from_text(story, audio_path, language, voice)
            title = scenario.strip().split(".")[0][:120] or "A new story"
            story_id = create_story(
                user_id,
                title,
                scenario,
                story,
                language,
                style,
                word_limit,
                paragraph_count,
                voice,
                image_path.relative_to(PROJECT_DIR).as_posix(),
                audio_path.relative_to(PROJECT_DIR).as_posix(),
            )
        except (OpenAIError, MySQLError, OSError, ValueError) as error:
            image_path.unlink(missing_ok=True)
            audio_path.unlink(missing_ok=True)
            flash(f"Story generation failed: {error}", "error")
            return redirect(url_for("create_story_page"))

        flash("Your story and narration are ready.", "success")
        return redirect(url_for("story_detail", story_id=story_id))

    @application.get("/library")
    @login_required
    def library() -> Any:
        user = session["user"]
        query = request.args.get("q", "").strip()
        language = request.args.get("language", "")
        if language not in LANGUAGES:
            language = ""
        stories = list_stories(
            int(user["id"]),
            search=query,
            language=language or None,
        )
        return render_template(
            "library.html",
            stories=stories,
            query=query,
            selected_language=language,
            languages=LANGUAGES,
        )

    @application.get("/stories/<story_id>")
    @login_required
    def story_detail(story_id: str) -> Any:
        story = get_story(int(session["user"]["id"]), story_id)
        if story is None:
            abort(404)
        return render_template("story.html", story=story, styles=STORY_STYLES)

    @application.get("/media/<story_id>/<kind>")
    @login_required
    def private_media(story_id: str, kind: str) -> Any:
        if kind not in {"photo", "audio"}:
            abort(404)
        story = get_story(int(session["user"]["id"]), story_id)
        if story is None:
            abort(404)
        category = "uploads" if kind == "photo" else "outputs"
        relative_path = story["image_path"] if kind == "photo" else story["audio_path"]
        try:
            path = resolve_user_asset_path(
                PROJECT_DIR, category, int(session["user"]["id"]), relative_path
            )
        except ValueError:
            abort(404)
        if not path.is_file():
            abort(404)
        return send_file(
            path,
            mimetype=mimetypes.guess_type(path.name)[0],
            as_attachment=request.args.get("download") == "1",
            download_name=path.name,
            conditional=True,
        )

    @application.post("/stories/<story_id>/rename")
    @login_required
    def rename_story_page(story_id: str) -> Any:
        title = request.form.get("title", "").strip()
        if not title or len(title) > 120:
            flash("Story titles must be between 1 and 120 characters.", "error")
        elif rename_story(int(session["user"]["id"]), story_id, title):
            flash("Story title updated.", "success")
        else:
            abort(404)
        return redirect(url_for("story_detail", story_id=story_id))

    @application.post("/stories/<story_id>/delete")
    @login_required
    def delete_story_page(story_id: str) -> Any:
        user_id = int(session["user"]["id"])
        paths = delete_story(user_id, story_id)
        if paths is None:
            abort(404)
        cleanup_failed = False
        for category, key in (("uploads", "image_path"), ("outputs", "audio_path")):
            try:
                path = resolve_user_asset_path(
                    PROJECT_DIR, category, user_id, paths[key]
                )
                path.unlink(missing_ok=True)
            except (OSError, ValueError):
                cleanup_failed = True
        if cleanup_failed:
            flash("Story deleted, but a media file could not be removed.", "warning")
        else:
            flash("Story and its media have been deleted.", "success")
        return redirect(url_for("library"))

    @application.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile() -> Any:
        user = session["user"]
        if request.method == "POST":
            display_name = request.form.get("display_name", "").strip()
            bio = request.form.get("bio", "").strip()
            language = request.form.get("preferred_language", "")
            if not display_name or len(display_name) > 80:
                flash("Display name must be between 1 and 80 characters.", "error")
            elif len(bio) > 500:
                flash("Your bio must be 500 characters or fewer.", "error")
            elif language not in LANGUAGES:
                flash("Choose a valid preferred language.", "error")
            else:
                update_profile(int(user["id"]), display_name, bio, language)
                user.update(
                    display_name=display_name,
                    bio=bio,
                    preferred_language=language,
                )
                session["user"] = user
                flash("Your profile has been updated.", "success")
                return redirect(url_for("profile"))
        return render_template("profile.html", user=user, languages=LANGUAGES)

    @application.errorhandler(400)
    def bad_request(error: Any) -> tuple[str, int]:
        return render_template(
            "message.html",
            title="Please refresh and try again",
            message=getattr(error, "description", "That request could not be completed."),
        ), 400

    @application.errorhandler(404)
    def not_found(_: Any) -> tuple[str, int]:
        return render_template(
            "message.html",
            title="We couldn't find that page",
            message="It may have been moved or may not belong to your account.",
        ), 404

    @application.errorhandler(413)
    def too_large(_: Any) -> tuple[str, int]:
        return render_template(
            "message.html",
            title="That image is too large",
            message="Please upload an image smaller than 20 MB.",
        ), 413

    @application.errorhandler(MySQLError)
    def database_unavailable(error: MySQLError) -> tuple[str, int]:
        application.config["DATABASE_READY"] = False
        setup_error = _database_setup_message(error)
        if isinstance(session.get("user"), dict):
            return render_template(
                "database_unavailable.html", setup_error=setup_error
            ), 503
        return render_template("login.html", database_message=setup_error), 503

    return application


def _csrf_token() -> str:
    token = session.get("_csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
