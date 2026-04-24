import json
import os
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv()

TALLINN_TZ = ZoneInfo("Europe/Tallinn")

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = [
    os.getenv("EMAIL_RECEIVER_1"),
    os.getenv("EMAIL_RECEIVER_2")
]

GOOD_WIND_MAX = 5.0
STORM_LIMIT = 10.0

def fmt_dt(dt):
    return dt.astimezone(TALLINN_TZ).strftime("%d.%m %H:%M")

def parse_api_time(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(tzinfo=TALLINN_TZ)

def sea_ok(direction, min_dir, max_dir):
    if min_dir <= max_dir:
        return min_dir <= direction <= max_dir
    return direction >= min_dir or direction <= max_dir

def get_weather(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "windspeed_10m,winddirection_10m,precipitation,temperature_2m",
        "past_days": 2,
        "forecast_days": 2,
        "timezone": "Europe/Tallinn"
    }
    return requests.get(url, params=params).json()

def evaluate_point(point, speeds, dirs):
    past_speeds = speeds[:48]
    past_dirs = dirs[:48]
    future_speeds = speeds[48:96]
    future_dirs = dirs[48:96]

    # 1. Torm minevikus
    if any(s > STORM_LIMIT for s in past_speeds):
        return False, "torm minevikus"

    # 2. Meretuule püsivus minevikus
    good_past = sum(
        1 for s, d in zip(past_speeds, past_dirs)
        if sea_ok(d, point["sea_wind_min"], point["sea_wind_max"]) and s <= GOOD_WIND_MAX
    )

    if good_past < 12:
        return False, "meretuul pole olnud piisav"

    # 3. Tulevik (esimene 24h)
    future_day = list(zip(future_speeds[:24], future_dirs[:24]))

    good_future = sum(
        1 for s, d in future_day
        if sea_ok(d, point["sea_wind_min"], point["sea_wind_max"]) and s <= GOOD_WIND_MAX
    )

    if good_future < 8:
        return False, "tulevik ei sobi"

    return True, "tingimused head"

def build_rows(point, times, speeds, dirs, precip, temp, indices):
    rows = []
    last_day = None

    for i in indices:
        dt = parse_api_time(times[i])
        day = dt.strftime("%d.%m")

        if last_day and day != last_day:
            rows.append(f"----- {day} -----")

        sea = "YES" if sea_ok(dirs[i], point["sea_wind_min"], point["sea_wind_max"]) else "NO"

        rows.append(
            f"{fmt_dt(dt)} | {dirs[i]:3.0f}° | {speeds[i]:4.1f} m/s | "
            f"sea:{sea} | rain:{precip[i]:4.1f} mm | air:{temp[i]:4.1f}°C"
        )

        last_day = day

    return rows

def build_series(point):
    data = get_weather(point["lat"], point["lon"])

    times = data["hourly"]["time"]
    speeds = data["hourly"]["windspeed_10m"]
    dirs = data["hourly"]["winddirection_10m"]
    precip = data["hourly"]["precipitation"]
    temp = data["hourly"]["temperature_2m"]

    parsed_times = [parse_api_time(t) for t in times]
    now = datetime.now(TALLINN_TZ)

    past_idx = [i for i, t in enumerate(parsed_times) if t <= now][-24:]
    future_idx = [i for i, t in enumerate(parsed_times) if t > now][:48]

    # sampling
    past_idx = past_idx[::2]      # iga 2h
    future_idx = future_idx[::3]  # iga 3h

    past_rows = build_rows(point, times, speeds, dirs, precip, temp, past_idx)
    future_rows = build_rows(point, times, speeds, dirs, precip, temp, future_idx)

    return past_rows, future_rows, speeds, dirs

def send_email(body):
    msg = MIMEText(body)
    msg["Subject"] = "Forellipüügi raport"
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(EMAIL_RECEIVERS)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, msg.as_string())

def main():
    with open("locations.json", "r", encoding="utf-8") as f:
        points = json.load(f)["points"]

    now = datetime.now(TALLINN_TZ)

    head_spots = []
    bad_spots = []
    details = []

    for p in points:
        past, future, speeds, dirs = build_series(p)

        ok, reason = evaluate_point(p, speeds, dirs)

        if ok:
            head_spots.append((p["name"], reason))
        else:
            bad_spots.append((p["name"], reason))

        details.append((p, past, future))

    lines = []
    lines.append(f"Forellipüügi raport")
    lines.append(f"Aeg: {fmt_dt(now)}")
    lines.append("")

    # HEAD
    lines.append("HEAD KOHAD:")
    if head_spots:
        for name, reason in head_spots:
            lines.append(f"{name} – OK")
            lines.append(f"- {reason}")
    else:
        lines.append("Puuduvad")

    lines.append("")
    lines.append("Halvad kohad:")
    for name, reason in bad_spots:
        lines.append(f"{name} – EI")
        lines.append(f"- {reason}")

    lines.append("")
    lines.append("="*60)

    # detail
    for p, past, future in details:
        lines.append(f"{p['name']} (sektor {p['sea_wind_min']}-{p['sea_wind_max']}°)")

        lines.append("--- Minevik ---")
        lines.extend(past)

        lines.append("================================")
        lines.append("============ TULEVIK ===========")
        lines.append("================================")

        lines.append("--- Tulevik ---")
        lines.extend(future)

        lines.append("")

    body = "\n".join(lines)

    print(body)
    send_email(body)
    print("Email saadetud")

if __name__ == "__main__":
    main()
