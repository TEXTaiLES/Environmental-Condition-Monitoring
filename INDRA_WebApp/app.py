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

from config_loader import load_config

config = load_config()

app = Flask(__name__)
app.secret_key = config['SECRET_KEY']

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
            f"{config['DIRECTUS_URL']}/auth/login",
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
    {"key": "temperature", "label": "Temperature (°C)", "name": "Temperature", "unit": "°C", "color": "#0d6efd"},
    {"key": "humidity", "label": "Humidity (%)", "name": "Humidity", "unit": "%", "color": "#dc3545"},
    {"key": "luminosity", "label": "Luminosity (lux)", "name": "Luminosity", "unit": "lux", "color": "#198754"},
]
METRICS_BY_KEY = {metric["key"]: metric for metric in METRICS}

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


def api_headers():
    return {"Authorization": f"Bearer {config['API_TOKEN']}"}


READINGS_PAGE_SIZE = 200
READINGS_MAX_PAGES = 50


def fetch_sensor_readings(sensor_id=None, start_date=None, per_page=READINGS_PAGE_SIZE, max_pages=READINGS_MAX_PAGES):
    """Page through /sensor-readings until it runs out (or max_pages is reached)."""
    url = f"{config['API_BASE_URL']}/sensor-readings"
    readings = []
    for page in range(1, max_pages + 1):
        params = {"per_page": per_page, "page": page}
        if sensor_id:
            params["sensor_id"] = sensor_id
        if start_date:
            params["start_date"] = start_date
        resp = requests.get(url, headers=api_headers(), params=params, timeout=15)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        readings.extend(batch)
    return readings


def fetch_latest_readings():
    """Most recent reading of every sensor in SENSOR_NAMES that has reported at least once."""
    latest = {}
    for sensor_id in config['SENSOR_NAMES']:
        rows = fetch_sensor_readings(sensor_id=sensor_id, per_page=1, max_pages=1)
        if rows:
            latest[sensor_id] = rows[0]
    return latest


def fetch_sensor_alerts(sensor_id=None, page=1, per_page=50):
    url = f"{config['API_BASE_URL']}/sensor-alerts"
    params = {"page": page, "per_page": per_page}
    if sensor_id:
        params["sensor_id"] = sensor_id
    resp = requests.get(url, headers=api_headers(), params=params, timeout=15)
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


def range_start(range_value):
    """ISO start of the selected time window, or None for all time."""
    time_delta = RANGE_DELTAS.get(range_value)
    if not time_delta:
        return None
    return (datetime.now(timezone.utc) - time_delta).isoformat()


def group_by_sensor(readings):
    grouped = defaultdict(list)
    for r in readings:
        grouped[r.get("sensor_id") or "unknown"].append(r)
    for rows in grouped.values():
        rows.sort(key=lambda r: parse_timestamp(r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
    return grouped


def build_sensor_options(latest_readings):
    sensor_options = []
    for sensor_id in latest_readings:
        sensor_options.append(
            {
                "id": sensor_id,
                "name": config['SENSOR_NAMES'].get(sensor_id, sensor_id),
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
        "name": config['SENSOR_NAMES'].get(sensor_id, sensor_id),
        "count": len(rows),
        "datasets": datasets,
    }


def thresholds_for(sensor_id):
    """Accepted range per metric for one sensor, from SENSOR_THRESHOLDS."""
    return (config.get("SENSOR_THRESHOLDS") or {}).get(sensor_id) or {}


def check_reading(sensor_id, reading):
    """Return one alert per metric of `reading` that falls outside its accepted range."""
    alerts = []
    for key, bounds in thresholds_for(sensor_id).items():
        bounds = bounds or {}
        metric = METRICS_BY_KEY.get(key, {"key": key, "name": key.replace("_", " ").capitalize(), "unit": ""})
        try:
            value = float(reading.get(key))
        except (TypeError, ValueError):
            continue

        min_value = bounds.get("min")
        max_value = bounds.get("max")
        if min_value is not None and value < min_value:
            direction, limit = "below", min_value
        elif max_value is not None and value > max_value:
            direction, limit = "above", max_value
        else:
            continue

        alerts.append(
            {
                "sensor_id": sensor_id,
                "sensor_name": config['SENSOR_NAMES'].get(sensor_id, sensor_id),
                "metric": key,
                "metric_name": metric["name"],
                "unit": metric["unit"],
                "value": value,
                "min_value": min_value,
                "max_value": max_value,
                "direction": direction,
                "limit": limit,
                "timestamp": reading.get("timestamp"),
                "display_timestamp": format_timestamp(reading.get("timestamp")),
            }
        )
    return alerts


def find_active_alerts(latest_readings):
    """Compare each sensor's most recent reading against its accepted ranges."""
    alerts = []
    for sensor_id, reading in latest_readings.items():
        alerts.extend(check_reading(sensor_id, reading))
    alerts.sort(key=lambda alert: (alert["sensor_name"], alert["metric"]))
    return alerts


# Alerts already saved to HESTIA by this process, so a page refresh doesn't re-post them.
# HESTIA ignores duplicates anyway; this only saves the round trip.
_recorded_alerts = set()


def record_alerts(alerts):
    for alert in alerts:
        alert_key = (alert["sensor_id"], alert["timestamp"], alert["metric"])
        if alert_key in _recorded_alerts:
            continue
        try:
            resp = requests.post(
                f"{config['API_BASE_URL']}/sensor-alerts",
                headers=api_headers(),
                json={
                    "sensor_id": alert["sensor_id"],
                    "timestamp": alert["timestamp"],
                    "metric": alert["metric"],
                    "value": alert["value"],
                    "min_value": alert["min_value"],
                    "max_value": alert["max_value"],
                },
                timeout=10,
            )
            resp.raise_for_status()
            _recorded_alerts.add(alert_key)
        except requests.RequestException as e:
            app.logger.warning(f"Could not save alert {alert_key} to HESTIA: {e}")


@app.route("/")
@login_required
def index():
    try:
        latest_readings = fetch_latest_readings()
    except requests.RequestException as e:
        flash(f"Could not reach sensor API: {e}", "error")
        latest_readings = {}

    sensor_options = build_sensor_options(latest_readings)
    selected_sensor_id = request.args.get("sensor_id")
    selected_range = request.args.get("range", "all")

    if not selected_sensor_id and sensor_options:
        selected_sensor_id = sensor_options[0]["id"]
    elif selected_sensor_id and selected_sensor_id not in {sensor["id"] for sensor in sensor_options}:
        selected_sensor_id = sensor_options[0]["id"] if sensor_options else None

    selected_rows = []
    if selected_sensor_id:
        try:
            selected_rows = fetch_sensor_readings(
                sensor_id=selected_sensor_id, start_date=range_start(selected_range)
            )
        except requests.RequestException as e:
            flash(f"Could not load readings for this sensor: {e}", "error")
    selected_sensor = build_selected_sensor(
        selected_sensor_id, group_by_sensor(selected_rows).get(selected_sensor_id, [])
    )

    selected_range_label = next(
        (option["label"] for option in RANGE_OPTIONS if option["value"] == selected_range),
        "Custom range",
    )

    active_alerts = find_active_alerts(latest_readings)
    record_alerts(active_alerts)
    selected_alert_metrics = {
        alert["metric"] for alert in active_alerts if alert["sensor_id"] == selected_sensor_id
    }

    return render_template(
        "index.html",
        sensor_options=sensor_options,
        selected_sensor=selected_sensor,
        selected_sensor_id=selected_sensor_id,
        selected_range=selected_range,
        selected_range_label=selected_range_label,
        range_options=RANGE_OPTIONS,
        active_alerts=active_alerts,
        selected_alert_metrics=selected_alert_metrics,
    )


@app.route("/alerts")
@login_required
def alerts():
    selected_sensor_id = request.args.get("sensor_id") or None
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    per_page = 50

    try:
        alert_rows = fetch_sensor_alerts(sensor_id=selected_sensor_id, page=page, per_page=per_page)
    except requests.RequestException as e:
        flash(f"Could not load alert history: {e}", "error")
        alert_rows = []

    for row in alert_rows:
        metric = METRICS_BY_KEY.get(row.get("metric"), {})
        row["sensor_name"] = config['SENSOR_NAMES'].get(row.get("sensor_id"), row.get("sensor_id"))
        row["metric_name"] = metric.get("name", row.get("metric"))
        row["unit"] = metric.get("unit", "")
        row["display_timestamp"] = format_timestamp(row.get("reading_timestamp"))

    sensor_options = [
        {"id": sensor_id, "name": name}
        for sensor_id, name in sorted(config['SENSOR_NAMES'].items(), key=lambda item: item[1])
    ]

    return render_template(
        "alerts.html",
        alerts=alert_rows,
        sensor_options=sensor_options,
        selected_sensor_id=selected_sensor_id,
        page=page,
        has_next=len(alert_rows) == per_page,
    )


@app.route("/api/debug")
@login_required
def debug_data():
    try:
        readings = fetch_sensor_readings(per_page=10, max_pages=1)
        latest_readings = fetch_latest_readings()
    except requests.RequestException as e:
        return {"error": str(e)}, 500

    sample_reading = readings[0] if readings else None

    return {
        "total_readings": len(readings),
        "sample_reading": sample_reading,
        "parsed_timestamp": format_timestamp(sample_reading.get("timestamp")) if sample_reading else None,
        "sensor_options": build_sensor_options(latest_readings),
    }

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=config['PORT'])
