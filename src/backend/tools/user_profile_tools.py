# -*- coding: utf-8 -*-
"""用户画像工具函数"""
import json
import os

from config.settings import USER_PROFILE_PATH
from models.user_profile_schema import UserProfile


def _profile_path(user_id: str) -> str:
    os.makedirs(USER_PROFILE_PATH, exist_ok=True)
    safe_id = "".join(c for c in user_id if c.isalnum() or c in "-_")
    return os.path.join(USER_PROFILE_PATH, f"{safe_id}.json")


def load_user_profile(user_id: str = "default") -> str:
    """加载用户画像。

    Args:
        user_id: 用户ID

    Returns:
        用户画像JSON字符串
    """
    path = _profile_path(user_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return UserProfile(user_id=user_id).model_dump_json()


def save_user_profile(user_id: str, profile_json: str) -> str:
    """保存用户画像。

    Args:
        user_id: 用户ID
        profile_json: 用户画像JSON字符串

    Returns:
        操作结果
    """
    path = _profile_path(user_id)
    profile = UserProfile.model_validate_json(profile_json)
    with open(path, "w", encoding="utf-8") as f:
        f.write(profile.model_dump_json(indent=2))
    return json.dumps({"status": "ok", "message": "画像已保存"}, ensure_ascii=False)


def update_user_profile(user_id: str, updates_json: str) -> str:
    """增量更新用户画像。

    Args:
        user_id: 用户ID
        updates_json: 要更新的字段JSON，如 {"preferred_travel_mode": "driving"}

    Returns:
        更新后的完整画像JSON
    """
    existing = json.loads(load_user_profile(user_id))
    updates = json.loads(updates_json)

    for key, value in updates.items():
        if key not in existing:
            continue
        if isinstance(existing[key], list) and isinstance(value, list):
            existing[key] = list(set(existing[key] + value))
        elif isinstance(existing[key], dict) and isinstance(value, dict):
            existing[key].update(value)
        else:
            existing[key] = value

    profile = UserProfile.model_validate(existing)
    path = _profile_path(user_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(profile.model_dump_json(indent=2))
    return profile.model_dump_json()
