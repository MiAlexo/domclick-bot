import json
import os

CONFIG_FILE = "users_config.json"


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_config(user_id: int) -> dict:
    data = load_config()
    return data.get(str(user_id))


def update_user_config(user_id: int, updates: dict):
    data = load_config()
    key = str(user_id)
    if key not in data:
        data[key] = {}
    data[key].update(updates)
    save_config(data)
