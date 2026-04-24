import json
import os
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

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


# -------------------------
# ANALÜÜS
# -------------------------
def evaluate_point(point, speeds, dirs):
    past_speeds = speeds[:48]
    past_dirs = dirs[:48]
    future_speeds = speeds[48:96]
    future_dirs = dirs[48:96]

    if any(s > STORM_LIMIT for s in past_speeds):
        return False, "torm minevikus"

    good_past = sum(
        1 for s, d in zip(past_speeds, past_dirs)
        if sea_ok(d, point["sea_wind_min"], point["sea_wind_max"]) and s <= GOOD_WIND_MAX
    )

    if good_past < 12:
        return False, "meretuul pole olnud piisav"

    good_future = sum(
        1 for s, d in zip(future_speeds[:24], future_dirs[:24])
        if sea_ok(d, point["sea_wind_min"], point["sea_wind_max"]) and s <= GOOD_WIND_MAX
    )

    if good_future < 8:
        return False, "tulevik ei sobi"

    return True, "tingimused head"


def calculate_rank(point, speeds, dirs):
    future_speeds = speeds[48:96]
    future_dirs = dirs[48:96]

    return sum(
        1 for s, d in zip(future_speeds[:24], future_dirs[:24])
        if sea_ok(d, point["sea_wind_min"], point["sea_wind_max"]) and s <= GOOD_WIND_MAX
    )


# -------------------------
# AJARIDA
# -------------------------
def build_rows(point, indices, times, speeds, dirs, precip, temp):
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


def build_series_from_data(point, data):
    times = data["hourly"]["time"]
    speeds = data["hourly"]["windspeed_10m"]
    dirs = data["hourly"]["winddirection_10m"]
    precip = data["hourly"]["precipitation"]
    temp = data["hourly"]["temperature_2m"]

    parsed_times = [parse_api_time(t) for t in times]
    now = datetime.now(TALLINN_TZ)

    past_idx = [i for i, t in enumerate(parsed_times) if t <= now][-24:]
    future_idx = [i for i, t in enumerate(parsed_times) if t > now][:48]

    past_idx = past_idx[::2]
    future_idx = future_idx[::3]

    past_rows = build_rows(point, past_idx, times, speeds, dirs, precip, temp)
    future_rows = build_rows(point, future_idx, times, speeds, dirs, precip, temp)

    return past_rows, future_rows, speeds, dirs


# -------------------------
# KAART (CACHE BAASIL)
# -------------------------
def create_map(points, weather_cache):
    fig, ax = plt.subplots(figsize=(8, 10))

    for p in points:
        data = weather_cache[p["name"]]

        speed = data["hourly"]["windspeed_10m"][0]
        direction = data["hourly"]["winddirection_10m"][0]

        ax.scatter(p["lon"], p["lat"])

        angle = np.deg2rad(direction)
        dx = np.sin(angle) * 0.05
        dy = np.cos(angle) * 0.05

        ax.arrow(p["lon"], p["lat"], dx, dy, head_width=0.02)

        ax.text(
            p["lon"], p["lat"],
            f"{p['name']}\n{speed:.1f} m/s",
            fontsize=8
        )

    filename = "wind_map.png"
    plt.savefig(filename)
    plt.close()

    return filename


# -------------------------
# EMAIL
# -------------------------
def send_email(body, image_file):
    msg = MIMEMultipart()
    msg["Subject"] = "Forellipüügi raport"
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(EMAIL_RECEIVERS)

    msg.attach(MIMEText(body))

    if image_file and os.path.exists(image_file):
        with open(image_file, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())

        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={image_file}")
        msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, msg.as_string())


# -------------------------
# MAIN
# -------------------------
def main():
    with open("locations.json", "r", encoding="utf-8") as f:
        points = json.load(f)["points"]

    now = datetime.now(TALLINN_TZ)

    weather_cache = {}

    for p in points:
        weather_cache[p["name"]] = get_weather(p["lat"], p["lon"])

    results = []

    for p in points:
        data = weather_cache[p["name"]]

        past, future, speeds, dirs = build_series_from_data(p, data)
        ok, reason = evaluate_point(p, speeds, dirs)
        rank = calculate_rank(p, speeds, dirs)

        results.append({
            "name": p["name"],
            "point": p,
            "past": past,
            "future": future,
            "ok": ok,
            "reason": reason,
            "rank": rank
        })

    results.sort(key=lambda x: x["rank"], reverse=True)

    best = results[0] if results else None

    image_file = create_map(points, weather_cache)

    lines = []
    lines.append("Forellipüügi raport")
    lines.append(f"Aeg: {fmt_dt(now)}")
    lines.append("")

    lines.append("PARIM VÕIMALUS:")
    if best:
        status = "GO" if best["ok"] else "WAIT"
        lines.append(f"{best['name']} – {status}")
        lines.append(f"- {best['reason']}")
    else:
        lines.append("Puudub")

    lines.append("")
    lines.append("=" * 60)

    for r in results:
        status = "GO" if r["ok"] else "WAIT"

        lines.append(f"{r['name']} – {status}")
        lines.append(f"- {r['reason']}")

        lines.append("--- Minevik ---")
        lines.extend(r["past"])

        lines.append("================================")
        lines.append("============ TULEVIK ===========")
        lines.append("================================")

        lines.append("--- Tulevik ---")
        lines.extend(r["future"])

        lines.append("")

    body = "\n".join(lines)

    print(body)
    send_email(body, image_file)
    print("Email saadetud")


if __name__ == "__main__":
    main()
