import os

API_BASE_URL = os.environ.get("SENSOR_API_BASE_URL", "ADD_URL")
API_TOKEN = os.environ.get("SENSOR_API_TOKEN", "ADD_KEY")

DIRECTUS_URL = os.environ.get("DIRECTUS_URL", "ADD_URL")

SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-please")

SENSOR_NAMES = {
    "TEXTaiLES-Indra-Box-1": "Indra Box 1",
    "TEXTaiLES-Indra-Box-2": "Indra Box 2",
    "TEXTaiLES-Indra-Box-3": "Indra Box 3",
    "TEXTaiLES-Indra-Box-4": "Indra Box 4",
    "TEXTaiLES-Indra-Box-5": "Indra Box 5",
    "TEXTaiLES-Indra-Box-6": "Indra Box 6",
    "TEXTaiLES-Indra-Box-7": "Indra Box 7",
    "TEXTaiLES-Indra-Box-8": "Indra Box 8",
    "TEXTaiLES-Indra-Box-9": "Indra Box 9",
    "TEXTaiLES-Indra-Box-10": "Indra Box 10"
}
