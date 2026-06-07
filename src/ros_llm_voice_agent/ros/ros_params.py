import io
import os

import rospkg
import yaml


def load_yaml(path):
    if not path:
        return {}
    with io.open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def package_path(package_name="ros_llm_voice_agent"):
    return rospkg.RosPack().get_path(package_name)


def default_config_path(name):
    return os.path.join(package_path(), "config", name)


def deep_merge(base, override):
    result = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def env_value(name, default=""):
    if not name:
        return default
    return os.environ.get(name, default)
