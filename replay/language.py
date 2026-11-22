"""Carry the game's selected language into the private Naninovel profile."""
import json
from pathlib import Path
import re

from . import isolation as iso
from .migration import _read


SETTINGS = Path("NaninovelData/Saves/Settings.json")
MANAGER = "Naninovel.LocalizationManager+Settings"
DEFAULT_TYPE = MANAGER + ", Elringus.Naninovel.Runtime, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"


def _i2_locale(value):
    # Unity PlayerPrefs writes its strings as NUL-terminated UTF-8 REG_BINARY.
    if isinstance(value, bytes):
        try:
            value = value.removesuffix(b"\0").decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    return {"chinese (simplified)": "zh-CN", "english": "en", "japanese": "ja"}.get(value.casefold())


def _official_i2_locale():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\{iso.SOURCE_COMPANY}\{iso.GAME}") as key:
            value, kind = winreg.QueryValueEx(key, "I2 Language_h3293684300")
    except OSError:
        return None
    return _i2_locale(value) if kind in (winreg.REG_BINARY, winreg.REG_SZ) else None


def _settings(path):
    try:
        state = json.loads(_read(path, 4 * 1024 * 1024))
    except FileNotFoundError:
        state = {"objectJsonMap": {"keys": [], "values": []}}
    entries = state.get("objectJsonMap") if isinstance(state, dict) else None
    if not isinstance(entries, dict):
        raise ValueError("无法识别语言设置文件：" + str(path))
    keys, values = entries.get("keys"), entries.get("values")
    if (not isinstance(keys, list) or not isinstance(values, list) or len(keys) != len(values)
            or not all(isinstance(k, str) for k in keys)):
        raise ValueError("语言设置记录不完整：" + str(path))
    positions = [i for i,k in enumerate(keys) if k.partition(",")[0] == MANAGER]
    if not positions:
        return state, None, {}
    if len(positions) != 1 or not isinstance(values[positions[0]], str):
        raise ValueError("无法识别语言设置记录：" + str(path))
    record = json.loads(values[positions[0]])
    if not isinstance(record, dict):
        raise ValueError("无法识别语言设置内容：" + str(path))
    return state, positions[0], record


def sync_replay_language(game):
    low = iso.local_low()
    if not re.fullmatch(r"Or16[0-9a-f]{7}", game.company) or game.profile != low / game.company / iso.GAME:
        raise ValueError("只能为已验证的回放副本同步语言。")
    source = low / iso.SOURCE_COMPANY / iso.GAME / SETTINGS
    type_name = DEFAULT_TYPE
    try:
        state, index, record = _settings(source)
        locale = record.get("SelectedLocale")
        if index is not None:
            type_name = state["objectJsonMap"]["keys"][index]
    except (ValueError, OSError):
        locale = None
    if not isinstance(locale, str) or not re.fullmatch(r"[a-zA-Z]{2,8}(?:[-_][a-zA-Z0-9]{1,8})*", locale):
        locale = _official_i2_locale()
    if not locale:
        return None

    # Naninovel applies SelectedLocale during startup and then refreshes I2.
    # Preserve private audio, UI, progress and any future localization options.
    path = iso._check_path(game.profile / SETTINGS, allow_missing=True)
    try:
        state, index, record = _settings(path)
    except ValueError as exc:
        raise ValueError("无法更新回放的语言设置，请检查文件：" + str(path)) from exc
    if record.get("SelectedLocale") == locale:
        return locale
    record["SelectedLocale"] = locale
    entries = state["objectJsonMap"]
    encoded = json.dumps(record, ensure_ascii=False)
    if index is None:
        entries["keys"].append(type_name)
        entries["values"].append(encoded)
    else:
        entries["values"][index] = encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    iso.atomic_json(path, state)
    return locale
