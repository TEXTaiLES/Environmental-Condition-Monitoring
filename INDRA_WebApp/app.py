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


def fetch_alert_summary(start_date):
    """Newest alert per sensor and metric since start_date, with how many there were."""
    url = f"{config['API_BASE_URL']}/sensor-alerts/summary"
    resp = requests.get(url, headers=api_headers(), params={"start_date": start_date}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_sensor_ranges(sensor_id):
    """Accepted ranges of one sensor, kept in HESTIA, as {metric: {"min": ..., "max": ...}}."""
    url = f"{config['API_BASE_URL']}/sensor-ranges"
    resp = requests.get(url, headers=api_headers(), params={"sensor_id": sensor_id}, timeout=15)
    resp.raise_for_status()
    return {row["metric"]: {"min": row["min_value"], "max": row["max_value"]} for row in resp.json()}


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


def out_of_range_metrics(reading, ranges):
    """Metrics of `reading` outside their accepted range, for highlighting the chart cards.

    Display only: HESTIA checks every incoming reading and records the alerts itself.
    """
    metrics = set()
    for key, bounds in ranges.items():
        try:
            value = float(reading.get(key))
        except (TypeError, ValueError):
            continue
        if (bounds["min"] is not None and value < bounds["min"]) or \
           (bounds["max"] is not None and value > bounds["max"]):
            metrics.add(key)
    return metrics


def build_recent_alerts():
    """Alerts from the last ALERT_WINDOW_HOURS, one entry per sensor and metric, newest first.

    Returns None if HESTIA can't be reached, so the page can say alerts are unavailable.
    """
    window_start = datetime.now(timezone.utc) - timedelta(hours=config.get("ALERT_WINDOW_HOURS") or 24)
    try:
        rows = fetch_alert_summary(window_start.isoformat())
    except requests.RequestException as e:
        app.logger.warning(f"Could not load recent alerts from HESTIA: {e}")
        return None

    recent = []
    for row in rows:
        metric = METRICS_BY_KEY.get(row.get("metric"), {})
        value, min_value, max_value = row.get("value"), row.get("min_value"), row.get("max_value")
        below = min_value is not None and value is not None and value < min_value
        recent.append({
            "key": f"{row.get('sensor_id')}|{row.get('metric')}|{row.get('reading_timestamp')}",
            "sensor_id": row.get("sensor_id"),
            "sensor_name": config['SENSOR_NAMES'].get(row.get("sensor_id"), row.get("sensor_id")),
            "metric_name": metric.get("name", row.get("metric")),
            "unit": metric.get("unit", ""),
            "value": value,
            "direction": "below" if below else "above",
            "limit": min_value if below else max_value,
            "display_timestamp": format_timestamp(row.get("reading_timestamp")),
            "count": row.get("count") or 1,
        })
    return recent


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

    selected_ranges = {}
    if selected_sensor_id:
        try:
            selected_ranges = fetch_sensor_ranges(selected_sensor_id)
        except requests.RequestException as e:
            app.logger.warning(f"Could not load accepted ranges from HESTIA: {e}")
    selected_alert_metrics = out_of_range_metrics(
        latest_readings.get(selected_sensor_id) or {}, selected_ranges
    )

    return render_template(
        "index.html",
        sensor_options=sensor_options,
        selected_sensor=selected_sensor,
        selected_sensor_id=selected_sensor_id,
        selected_range=selected_range,
        selected_range_label=selected_range_label,
        range_options=RANGE_OPTIONS,
        recent_alerts=build_recent_alerts(),
        alert_window_hours=config.get("ALERT_WINDOW_HOURS") or 24,
        selected_ranges=selected_ranges,
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
