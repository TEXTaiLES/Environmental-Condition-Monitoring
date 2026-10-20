import os
from pathlib import Path

import yaml


def _read_settings(path):
    with path.open(encoding="utf-8") as config_file:
        settings = yaml.safe_load(config_file)
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        raise ValueError(f"{path.name} must contain a mapping of settings")
    return {
        name: value
        for name, value in settings.items()
        if isinstance(name, str) and name.isupper()
    }


def load_config():
    directory = Path(__file__).resolve().parent
    settings = _read_settings(directory / "config.yml")

    # Preserve environment settings; local overrides take final precedence.
    environment_settings = {
        "PORT": "PORT",
        "API_BASE_URL": "SENSOR_API_BASE_URL",
        "API_TOKEN": "SENSOR_API_TOKEN",
        "DIRECTUS_URL": "DIRECTUS_URL",
        "SECRET_KEY": "FLASK_SECRET_KEY",
    }
    for setting, variable in environment_settings.items():
        if variable in os.environ:
            settings[setting] = os.environ[variable]

    try:
        overrides = _read_settings(directory / "config_override.yml")
    except FileNotFoundError:
        overrides = {}
    # Dictionary settings such as SENSOR_NAMES are replaced as a whole.
    settings.update(overrides)
    settings["PORT"] = int(settings["PORT"])
    return settings
