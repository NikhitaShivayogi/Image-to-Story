from pathlib import Path


def user_asset_directory(project_dir: Path, category: str, user_id: int) -> Path:
    if category not in {"uploads", "outputs"} or user_id < 1:
        raise ValueError("Invalid user asset location.")
    return project_dir / category / str(user_id)


def resolve_user_asset_path(
    project_dir: Path,
    category: str,
    user_id: int,
    relative_path: str,
) -> Path:
    user_directory = user_asset_directory(project_dir, category, user_id).resolve()
    asset_path = (project_dir / relative_path).resolve()
    if asset_path.parent != user_directory or asset_path.name in {"", ".", ".."}:
        raise ValueError("Story asset path is outside the current user's folder.")
    return asset_path
