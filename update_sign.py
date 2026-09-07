import os
import requests
from datetime import datetime, timezone

ROBIN_SPACE_ID = "290741"
ROBIN_TOKEN = os.environ.get("ROBIN_TOKEN")
DOT_API_KEY = os.environ.get("DOT_API_KEY")
DOT_DEVICE_ID = os.environ.get("DOT_DEVICE_ID")

def parse_iso_time(iso_str):
    if not iso_str:
        return None
    # Fix timezone offsets like +0800 so Python's fromisoformat can parse them
    if len(iso_str) >= 5 and iso_str[-5] in ('+', '-') and iso_str[-3] != ':':
        iso_str = iso_str[:-2] + ':' + iso_str[-2:]
    return datetime.fromisoformat(iso_str)

def update_meeting_room_status():
    headers = {
        "Authorization": f"Access-Token {ROBIN_TOKEN}",
        "Accept": "application/json"
    }
    
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat().replace("+00:00", "Z")
    
    url = f"https://api.robinpowered.com/v1.0/spaces/{ROBIN_SPACE_ID}/events"
    params = {
        "after": start_of_day,
        "before": end_of_day
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        events = data.get("data", [])
    except Exception as e:
        print(f"Error fetching from Robin API: {e}")
        return

    current_meeting = None
    
    for event in events:
        try:
            start_str = event.get("start", {}).get("utc") or event.get("started_at")
            end_str = event.get("end", {}).get("utc") or event.get("ended_at")
            
            if not start_str or not end_str:
                continue
                
            start = parse_iso_time(start_str)
            end = parse_iso_time(end_str)
            
            if start and end and start <= now <= end:
                current_meeting = event
                break
        except Exception as parse_err:
            print(f"Skipping event due to parse error: {parse_err}")

    if current_meeting:
        status_text = "IN USE"
        meeting_title = current_meeting.get("title", "Meeting in Progress")
        color_class = "text-red-600"
    else:
        status_text = "VACANT"
        meeting_title = "Room is available"
        color_class = "text-green-600"

    dot_payload = {
        "windowData": {
            "default": [
                {
                    "type": "div",
                    "props": {
                        "tw": f"flex flex-col h-full justify-center items-center p-4 bg-white {color_class}",
                        "children": [
                            {"type": "span", "props": {"tw": "text-2xl font-bold", "children": status_text}},
                            {"type": "span", "props": {"tw": "text-sm text-gray-600 mt-2", "children": meeting_title}}
                        ]
                    }
                }
            ]
        }
    }

    # Corrected official Dot. API endpoint path
    dot_url = f"https://dot.mindreset.tech/api/authV2/open/device/{DOT_DEVICE_ID}/canvas"
    dot_headers = {
        "Authorization": f"Bearer {DOT_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        dot_response = requests.post(dot_url, headers=dot_headers, json=dot_payload)
        dot_response.raise_for_status()
        print(f"Successfully updated Quote/0 display. Status: {status_text} | Meeting: {meeting_title}")
    except Exception as e:
        print(f"Error pushing to Dot. API: {e}")

if __name__ == "__main__":
    update_meeting_room_status()
