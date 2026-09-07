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
    next_meeting = None
    
    for event in events:
        try:
            start_str = event.get("start", {}).get("utc") or event.get("started_at")
            end_str = event.get("end", {}).get("utc") or event.get("ended_at")
            
            if not start_str or not end_str:
                continue
                
            start = parse_iso_time(start_str)
            end = parse_iso_time(end_str)
            
            if not start or not end:
                continue
            
            if start <= now <= end:
                current_meeting = event
                current_meeting['start_dt'] = start
                current_meeting['end_dt'] = end
                break
            elif start > now:
                if not next_meeting or start < next_meeting['start_dt']:
                    next_meeting = event
                    next_meeting['start_dt'] = start
        except Exception as parse_err:
            print(f"Skipping event due to parse error: {parse_err}")

    if current_meeting:
        status_text = "RESERVED / IN USE"
        meeting_title = current_meeting.get("title", "Meeting in Progress")
        status_color = "text-white"
        bg_color = "bg-black"
        main_text_color = "text-white"
        sub_text_color = "text-gray-300"
        border_color = "border-gray-800"
        
        start_dt = current_meeting['start_dt']
        end_dt = current_meeting['end_dt']
        
        time_window = f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
        
        remaining_seconds = (end_dt - now).total_seconds()
        remaining_mins = max(0, int(remaining_seconds // 60))
        if remaining_mins >= 60:
            hrs = remaining_mins // 60
            mins = remaining_mins % 60
            remaining_text = f"{hrs}h {mins}m remaining"
        else:
            remaining_text = f"{remaining_mins} mins remaining"
            
        subtext_children = [
            {"type": "span", "props": {"tw": f"text-lg font-bold {main_text_color} truncate", "children": meeting_title}},
            {"type": "span", "props": {"tw": f"text-base {sub_text_color} mt-1", "children": f"Time: {time_window}"}},
            {"type": "span", "props": {"tw": f"text-base text-red-400 font-semibold mt-1", "children": remaining_text}}
        ]
    else:
        status_text = "VACANT"
        status_color = "text-green-600"
        bg_color = "bg-white"
        main_text_color = "text-black"
        sub_text_color = "text-gray-700"
        border_color = "border-gray-200"
        
        if next_meeting:
            next_start = next_meeting['start_dt']
            next_title = next_meeting.get("title", "Upcoming Meeting")
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-lg font-bold {main_text_color}", "children": "Room is available"}},
                {"type": "span", "props": {"tw": f"text-base {sub_text_color} mt-1", "children": f"Next: {next_title}"}},
                {"type": "span", "props": {"tw": f"text-base text-gray-500 mt-1", "children": f"Starts at {next_start.strftime('%H:%M')}"}}
            ]
        else:
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-lg font-bold {main_text_color}", "children": "Room is available"}},
                {"type": "span", "props": {"tw": f"text-base {sub_text_color} mt-1", "children": "No more meetings today"}}
            ]

    dot_payload = {
        "windowData": {
            "default": [
                {
                    "type": "div",
                    "props": {
                        "tw": f"flex flex-col h-full justify-between p-3 {bg_color} {main_text_color}",
                        "children": [
                            {
                                "type": "div",
                                "props": {
                                    "tw": f"flex justify-between items-center border-b {border_color} pb-1",
                                    "children": [
                                        {"type": "span", "props": {"tw": f"text-3xl font-bold {status_color}", "children": status_text}},
                                        {"type": "span", "props": {"tw": "text-base text-gray-400", "children": datetime.now().strftime('%H:%M')}}
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

    dot_url = f"https://dot.mindreset.tech/api/authV2/open/device/{DOT_DEVICE_ID}/canvas"
    dot_headers = {
        "Authorization": f"Bearer {DOT_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        dot_response = requests.post(dot_url, headers=dot_headers, json=dot_payload)
        dot_response.raise_for_status()
        print(f"Successfully updated Quote/0 display. Status: {status_text}")
    except Exception as e:
        print(f"Error pushing to Dot. API: {e}")

if __name__ == "__main__":
    update_meeting_room_status()
