from datetime import datetime, timedelta, timezone
from collections import defaultdict

import requests
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    login_required,
    login_user,
    logout_user,
)

import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

_user_registry = {}


class User(UserMixin):
    def __init__(self, user_id, email=None, slug=None, full_name=None):
        self.id = user_id
        self.email = email
        self.slug = slug
        self.full_name = full_name


@login_manager.user_loader
def load_user(user_id):
    return _user_registry.get(str(user_id))


def safe_user_slug(email):
    base = email.split("@", 1)[0].strip().lower()
    return "".join(c for c in base if c.isalnum() or c in ("-", "_"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        resp = requests.post(
            f"{config.DIRECTUS_URL}/auth/login",
            json={"email": username, "password": password},
            headers={"Content-Type": "application/json"},
        )
        app.logger.info(f"Login response status: {resp.status_code}")

        if resp.ok:
            slug = safe_user_slug(username)
            user = User(
                user_id=slug,
                email=username,
                slug=slug,
                full_name=f"@{slug}",
            )
            _user_registry[str(user.id)] = user
            login_user(user)
            return redirect(url_for("index"))

        flash("Wrong Credentials.")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


METRICS = [
    {"key": "temperature", "label": "Temperature (°C)", "color": "#0d6efd"},
    {"key": "humidity", "label": "Humidity (%)", "color": "#dc3545"},
    {"key": "luminosity", "label": "Luminosity (lux)", "color": "#198754"},
]

RANGE_OPTIONS = [
    {"value": "6h", "label": "Last 6 hours"},
    {"value": "24h", "label": "Last 24 hours"},
    {"value": "7d", "label": "Last 7 days"},
    {"value": "30d", "label": "Last 30 days"},
    {"value": "all", "label": "All time"},
]

RANGE_DELTAS = {
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def fetch_sensor_readings(per_page=1000):
    url = f"{config.API_BASE_URL}/sensor-readings"
    headers = {"Authorization": f"Bearer {config.API_TOKEN}"}
    params = {"per_page": per_page}
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_timestamp(raw_value):
    if not raw_value:
        return None

    if isinstance(raw_value, datetime):
        parsed = raw_value
    else:
        try:
            parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def format_timestamp(raw_value):
    parsed = parse_timestamp(raw_value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def filter_readings_by_range(readings, range_value):
    if range_value == "all":
        return readings

    time_delta = RANGE_DELTAS.get(range_value)
    if not time_delta:
        return readings

    cutoff = datetime.now(timezone.utc) - time_delta
    filtered = []
    for reading in readings:
        reading_timestamp = parse_timestamp(reading.get("timestamp"))
        if reading_timestamp and reading_timestamp >= cutoff:
            filtered.append(reading)
    return filtered


def group_by_sensor(readings):
    grouped = defaultdict(list)
    for r in readings:
        grouped[r.get("sensor_id") or "unknown"].append(r)
    for rows in grouped.values():
        rows.sort(key=lambda r: parse_timestamp(r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
    return grouped


def build_sensor_options(readings):
    grouped = group_by_sensor(readings)
    sensor_options = []
    for sensor_id, rows in grouped.items():
        sensor_options.append(
            {
                "id": sensor_id,
                "name": config.SENSOR_NAMES.get(sensor_id, sensor_id),
                "count": len(rows),
            }
        )

    sensor_options.sort(key=lambda sensor: sensor["name"])
    return sensor_options


def build_selected_sensor(sensor_id, rows):
    if not sensor_id:
        return None

    datasets = []
    for metric in METRICS:
        points = []
        last_value = None
        last_timestamp = None
        
        for reading in rows:
            value = reading.get(metric["key"])
            reading_timestamp = format_timestamp(reading.get("timestamp"))
            if value is None or not reading_timestamp:
                continue
            points.append({"x": reading_timestamp, "y": value})
            last_value = value
            last_timestamp = reading_timestamp

        if points:
            datasets.append(
                {
                    "key": metric["key"],
                    "label": metric["label"],
                    "color": metric["color"],
                    "points": points,
                    "lastValue": last_value,
                    "lastTimestamp": last_timestamp,
                }
            )

    return {
        "id": sensor_id,
        "name": config.SENSOR_NAMES.get(sensor_id, sensor_id),
        "count": len(rows),
        "datasets": datasets,
    }


@app.route("/")
@login_required
def index():
    try:
        readings = fetch_sensor_readings()
    except requests.RequestException as e:
        flash(f"Could not reach sensor API: {e}", "error")
        readings = []

    sensor_options = build_sensor_options(readings)
    selected_sensor_id = request.args.get("sensor_id")
    selected_range = request.args.get("range", "all")

    if not selected_sensor_id and sensor_options:
        selected_sensor_id = sensor_options[0]["id"]
    elif selected_sensor_id and selected_sensor_id not in {sensor["id"] for sensor in sensor_options}:
        selected_sensor_id = sensor_options[0]["id"] if sensor_options else None

    filtered_readings = filter_readings_by_range(readings, selected_range)
    filtered_grouped = group_by_sensor(filtered_readings)
    selected_sensor = build_selected_sensor(selected_sensor_id, filtered_grouped.get(selected_sensor_id, []))

    selected_range_label = next(
        (option["label"] for option in RANGE_OPTIONS if option["value"] == selected_range),
        "Custom range",
    )

    return render_template(
        "index.html",
        sensor_options=sensor_options,
        selected_sensor=selected_sensor,
        selected_sensor_id=selected_sensor_id,
        selected_range=selected_range,
        selected_range_label=selected_range_label,
        range_options=RANGE_OPTIONS,
    )


@app.route("/api/debug")
@login_required
def debug_data():
    try:
        readings = fetch_sensor_readings(per_page=10)
    except requests.RequestException as e:
        return {"error": str(e)}, 500

    sample_reading = readings[0] if readings else None
    
    return {
        "total_readings": len(readings),
        "sample_reading": sample_reading,
        "parsed_timestamp": format_timestamp(sample_reading.get("timestamp")) if sample_reading else None,
        "sensor_options": build_sensor_options(readings),
    }


if __name__ == "__main__":
    app.run(debug=True,port=5000)