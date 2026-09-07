import os
import requests
from datetime import datetime, timezone

ROBIN_SPACE_ID = "290741"
ROBIN_TOKEN = os.environ.get("ROBIN_TOKEN")
DOT_API_KEY = os.environ.get("DOT_API_KEY")
DOT_DEVICE_ID = os.environ.get("DOT_DEVICE_ID")

LAT = 22.2877
LON = 114.2127

def parse_iso_time(iso_str):
    if not iso_str:
        return None
    if len(iso_str) >= 5 and iso_str[-5] in ('+', '-') and iso_str[-3] != ':':
        iso_str = iso_str[:-2] + ':' + iso_str[-2:]
    return datetime.fromisoformat(iso_str)

def get_device_battery():
    status_url = f"https://dot.mindreset.tech/api/authV2/open/device/{DOT_DEVICE_ID}/status"
    headers = {
        "Authorization": f"Bearer {DOT_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(status_url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            battery = data.get("battery")
            if isinstance(battery, dict):
                return battery.get("level") or battery.get("percent") or battery.get("value")
            return battery
    except Exception as e:
        print(f"Error fetching device status: {e}")
    return None

def get_battery_display(pct):
    if pct is None:
        return ""
    if pct >= 88:
        return "[■■■■] 100%"
    elif pct >= 63:
        return "[■■■□] 75%"
    elif pct >= 38:
        return "[■■□□] 50%"
    else:
        return "[■□□□] 25%"

def weather_code_to_text(code):
    if code == 0:
        return "Clear"
    elif code in [1, 2]:
        return "Partly Cloudy"
    elif code == 3:
        return "Overcast"
    elif code in [45, 48]:
        return "Foggy"
    elif code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]:
        return "Rain"
    elif code in [71, 73, 75, 77]:
        return "Snow"
    elif code >= 95:
        return "Thunder"
    return "Fair"

def fetch_quarry_bay_weather():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current=temperature_2m,weather_code&hourly=temperature_2m,weather_code&timezone=auto"
    try:
        res = requests.get(url)
        res.raise_for_status()
        data = res.json()
        
        current_temp = data.get("current", {}).get("temperature_2m", 0)
        current_code = data.get("current", {}).get("weather_code", 0)
        curr_desc = weather_code_to_text(current_code)
        
        hourly_times = data.get("hourly", {}).get("time", [])
        hourly_temps = data.get("hourly", {}).get("temperature_2m", [])
        
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:00")
        start_idx = 0
        for i, t in enumerate(hourly_times):
            if t >= now_iso:
                start_idx = i
                break
                
        forecasts = []
        for i in range(1, 5):
            idx = start_idx + i
            if idx < len(hourly_times):
                time_label = datetime.fromisoformat(hourly_times[idx]).strftime("%H:%M")
                temp = hourly_temps[idx]
                forecasts.append({"time": time_label, "temp": f"{temp}°C"})
                
        return {
            "temp": f"{current_temp}°C",
            "desc": curr_desc,
            "forecasts": forecasts
        }
    except Exception as e:
        print(f"Error fetching weather: {e}")
        return None

def main():
    battery_pct = get_device_battery()
    battery_display = get_battery_display(battery_pct)

    # Alternate screens every 10 minutes based on the current minute block
    show_weather = ((datetime.now().minute // 10) % 2 == 1)

    dot_url = f"https://dot.mindreset.tech/api/authV2/open/device/{DOT_DEVICE_ID}/canvas"
    dot_headers = {
        "Authorization": f"Bearer {DOT_API_KEY}",
        "Content-Type": "application/json"
    }

    if show_weather:
        weather_data = fetch_quarry_bay_weather()
        if weather_data:
            forecast_children = []
            for f in weather_data["forecasts"]:
                forecast_children.append({
                    "type": "div",
                    "props": {
                        "tw": "flex flex-col items-center justify-center flex-1 p-1 bg-gray-100 rounded",
                        "children": [
                            {"type": "span", "props": {"tw": "text-xs text-gray-600", "children": f["time"]}},
                            {"type": "span", "props": {"tw": "text-xs font-bold text-black mt-1", "children": f["temp"]}}
                        ]
                    }
                })

            dot_payload = {
                "windowData": {
                    "default": [
                        {
                            "type": "div",
                            "props": {
                                "tw": "flex flex-col w-full h-full justify-between p-3 bg-white text-black",
                                "children": [
                                    {
                                        "type": "div",
                                        "props": {
                                            "tw": "flex justify-between items-center border-b border-gray-200 pb-1",
                                            "children": [
                                                {"type": "span", "props": {"tw": "text-lg font-bold tracking-tight", "children": "QUARRY BAY WEATHER"}},
                                                {"type": "span", "props": {"tw": "text-xs text-gray-500", "children": battery_display}}
                                            ]
                                        }
                                    },
                                    {
                                        "type": "div",
                                        "props": {
                                            "tw": "flex flex-col justify-center my-auto px-2",
                                            "children": [
                                                {"type": "span", "props": {"tw": "text-3xl font-bold", "children": weather_data["temp"]}},
                                                {"type": "span", "props": {"tw": "text-sm text-gray-600 mt-1", "children": weather_data["desc"]}}
                                            ]
                                        }
                                    },
                                    {
                                        "type": "div",
                                        "props": {
                                            "tw": "flex justify-between space-x-2 pt-1 border-t border-gray-100",
                                            "children": forecast_children
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
            requests.post(dot_url, headers=dot_headers, json=dot_payload)
            print("Successfully updated Quote/0 display with Quarry Bay Weather.")
            return

    # Room Status Flow
    headers = {
        "Authorization": f"Access-Token {ROBIN_TOKEN}",
        "Accept": "application/json"
    }
    
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat().replace("+00:00", "Z")
    
    url = f"https://api.robinpowered.com/v1.0/spaces/{ROBIN_SPACE_ID}/events"
    params = {"after": start_of_day, "before": end_of_day}
    
    current_meeting = None
    next_meeting = None
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        events = response.json().get("data", [])
        
        for event in events:
            start_str = event.get("start", {}).get("utc") or event.get("started_at")
            end_str = event.get("end", {}).get("utc") or event.get("ended_at")
            if not start_str or not end_str:
                continue
            parse_start = parse_iso_time(start_str)
            parse_end = parse_iso_time(end_str)
            if not parse_start or not parse_end:
                continue
            
            if parse_start <= now <= parse_end:
                current_meeting = event
                current_meeting['start_dt'] = parse_start
                current_meeting['end_dt'] = parse_end
                break
            elif parse_start > now:
                if not next_meeting or parse_start < next_meeting['start_dt']:
                    next_meeting = event
                    next_meeting['start_dt'] = parse_start
    except Exception as e:
        print(f"Error fetching from Robin API: {e}")

    date_str = f"Date: {now.strftime('%d-%b-%y (%A)')}"

    if current_meeting:
        status_text = "RESERVED"
        bg_color = "bg-black"
        main_text_color = "text-white"
        sub_text_color = "text-gray-300"
        border_color = "border-gray-800"
        
        start_dt = current_meeting['start_dt']
        end_dt = current_meeting['end_dt']
        time_window = f"Time: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
        
        remaining_seconds = (end_dt - now).total_seconds()
        remaining_mins = max(0, int(remaining_seconds // 60))
        if remaining_mins >= 60:
            hrs = remaining_mins // 60
            mins = remaining_mins % 60
            remaining_text = f"{hrs}h {mins}m remaining"
        else:
            remaining_text = f"{remaining_mins} mins remaining"
            
        subtext_children = [
            {"type": "span", "props": {"tw": f"text-base {sub_text_color}", "children": date_str}},
            {"type": "span", "props": {"tw": f"text-base {sub_text_color} mt-0.5", "children": time_window}},
            {"type": "span", "props": {"tw": f"text-base text-red-400 font-semibold mt-0.5", "children": remaining_text}}
        ]
    else:
        status_text = "VACANT"
        bg_color = "bg-white"
        main_text_color = "text-black"
        sub_text_color = "text-gray-700"
        border_color = "border-gray-200"
        
        if next_meeting:
            next_start = next_meeting['start_dt']
            next_title = next_meeting.get("title", "Upcoming Meeting")
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-base {sub_text_color}", "children": date_str}},
                {"type": "span", "props": {"tw": f"text-base {sub_text_color} mt-0.5", "children": f"Next: {next_title}"}},
                {"type": "span", "props": {"tw": f"text-base text-gray-500 mt-0.5", "children": f"Starts at {next_start.strftime('%H:%M')}"}}
            ]
        else:
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-base {sub_text_color}", "children": date_str}},
                {"type": "span", "props": {"tw": f"text-base {sub_text_color} mt-0.5", "children": "No more meetings today"}}
            ]

    dot_payload = {
        "windowData": {
            "default": [
                {
                    "type": "div",
                    "props": {
                        "tw": f"flex flex-col w-full h-full justify-between p-2 {bg_color} {main_text_color}",
                        "children": [
                            {
                                "type": "div",
                                "props": {
                                    "tw": f"flex justify-between items-center border-b {border_color} pb-1",
                                    "children": [
                                        {"type": "span", "props": {"tw": "text-2xl font-bold tracking-tight text-white" if current_meeting else "text-2xl font-bold tracking-tight text-green-600", "children": status_text}},
                                        {"type": "span", "props": {"tw": f"text-xs {sub_text_color if current_meeting else 'text-gray-500'}", "children": battery_display}}
                                    ]
                                }
                            },
                            {
                                "type": "div",
                                "props": {
                                    "tw": "flex flex-col justify-center my-auto",
                                    "children": subtext_children
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }

    try:
        response = requests.post(dot_url, headers=dot_headers, json=dot_payload)
        response.raise_for_status()
        print(f"Successfully updated Room Status display. Status: {status_text}")
    except Exception as e:
        print(f"Error pushing to Dot. API: {e}")

if __name__ == "__main__":
    main()
