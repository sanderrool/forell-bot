import json
import requests
import matplotlib.pyplot as plt
import numpy as np

def get_weather(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "windspeed_10m,winddirection_10m",
        "forecast_days": 1
    }
    return requests.get(url, params=params).json()

def create_map():
    with open("locations.json", "r", encoding="utf-8") as f:
        points = json.load(f)["points"]

    fig, ax = plt.subplots(figsize=(8, 10))

    for p in points:
        data = get_weather(p["lat"], p["lon"])

        speed = data["hourly"]["windspeed_10m"][0]
        direction = data["hourly"]["winddirection_10m"][0]

        ax.scatter(p["lon"], p["lat"])

        angle = np.deg2rad(direction)
        dx = np.sin(angle) * 0.05
        dy = np.cos(angle) * 0.05

        ax.arrow(p["lon"], p["lat"], dx, dy, head_width=0.02, color="blue")

        ax.text(
            p["lon"], p["lat"],
            f"{p['name']}\n{speed:.1f} m/s\n{int(direction)}°",
            fontsize=8
        )

    ax.set_title("Tuule suund ja tugevus")
    ax.set_xlabel("Lon")
    ax.set_ylabel("Lat")

    plt.grid()
    plt.tight_layout()

    filename = "wind_map.png"
    plt.savefig(filename)
    plt.close()

    return filename
