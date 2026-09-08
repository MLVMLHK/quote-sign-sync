import os
import time
import requests
from requests.exceptions import RequestException
from datetime import datetime, timezone, timedelta

ROBIN_SPACE_ID = "290741"
ROBIN_TOKEN = os.environ.get("ROBIN_TOKEN")
DOT_API_KEY = os.environ.get("DOT_API_KEY")
DOT_DEVICE_ID = os.environ.get("DOT_DEVICE_ID")

HK_TZ = timezone(timedelta(hours=8))

def api_request_with_retry(method, url, retries=3, delay=2, **kwargs):
    for attempt in range(retries):
        try:
            if method.lower() == 'get':
                response = requests.get(url, **kwargs)
            else:
                response = requests.post(url, **kwargs)
            response.raise_for_status()
            return response
        except RequestException as e:
            print(f"API request failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise

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
    
    now_utc = datetime.now(timezone.utc)
    now_hk = datetime.now(HK_TZ)
    
    start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    end_of_day = now_utc.replace(hour=23, minute=59, second=59, microsecond=0).isoformat().replace("+00:00", "Z")
    
    url = f"https://api.robinpowered.com/v1.0/spaces/{ROBIN_SPACE_ID}/events"
    params = {
        "after": start_of_day,
        "before": end_of_day
    }
    
    try:
        response = api_request_with_retry('get', url, headers=headers, params=params)
        data = response.json()
        events = data.get("data", [])
    except Exception as e:
        print(f"Error fetching from Robin API after retries: {e}")
        return

    current_meeting = None
    next_meeting = None
    
    for event in events:
        try:
            start_str = event.get("start", {}).get("utc") or event.get("started_at")
            end_str = event.get("end", {}).get("utc") or event.get("ended_at")
            
            if not start_str or not end_str:
                continue
                
            parse_start = parse_iso_time(start_str)
            parse_end = parse_iso_time(end_str)
            
            if not parse_start or not parse_end:
                continue
            
            if parse_start <= now_utc <= parse_end:
                current_meeting = event
                current_meeting['start_dt'] = parse_start
                current_meeting['end_dt'] = parse_end
                break
            elif parse_start > now_utc:
                if not next_meeting or parse_start < next_meeting['start_dt']:
                    next_meeting = event
                    next_meeting['start_dt'] = parse_start
        except Exception as parse_err:
            print(f"Skipping event due to parse error: {parse_err}")

    date_str = f"Date: {now_hk.strftime('%d-%b-%y (%A)')}"
    sync_time_str = f"Last sync: {now_hk.strftime('%H:%M:%S')} HKT"

    if current_meeting:
        status_text = "RESERVED"
        bg_color = "bg-black"
        main_text_color = "text-white"
        sub_text_color = "text-white"
        border_color = "border-gray-700"
        
        start_dt = current_meeting['start_dt']
        end_dt = current_meeting['end_dt']
        
        time_window = f"Time: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
        
        remaining_seconds = (end_dt - now_utc).total_seconds()
        remaining_mins = max(0, int(remaining_seconds // 60))
        if remaining_mins >= 60:
            hrs = remaining_mins // 60
            mins = remaining_mins % 60
            remaining_text = f"{hrs}h {mins}m remaining"
        else:
            remaining_text = f"{remaining_mins} mins remaining"
            
        subtext_children = [
            {"type": "span", "props": {"tw": f"text-sm font-bold {sub_text_color}", "children": date_str}},
            {"type": "span", "props": {"tw": f"text-sm font-bold {sub_text_color} mt-1", "children": time_window}},
            {"type": "span", "props": {"tw": f"text-sm text-red-300 font-extrabold mt-1", "children": remaining_text}}
        ]
        sync_text_color = "text-gray-300"
    else:
        status_text = "VACANT"
        bg_color = "bg-white"
        main_text_color = "text-black"
        sub_text_color = "text-black"
        border_color = "border-gray-300"
        
        if next_meeting:
            next_start = next_meeting['start_dt']
            next_title = next_meeting.get("title", "Upcoming Meeting")
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-sm font-bold {sub_text_color}", "children": date_str}},
                {"type": "span", "props": {"tw": f"text-sm font-bold {sub_text_color} mt-1", "children": f"Next: {next_title}"}},
                {"type": "span", "props": {"tw": f"text-sm font-extrabold text-gray-900 mt-1", "children": f"Starts at {next_start.strftime('%H:%M')}"}}
            ]
        else:
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-sm font-bold {sub_text_color}", "children": date_str}},
                {"type": "span", "props": {"tw": f"text-sm font-extrabold text-gray-900 mt-1", "children": "No more meetings today"}}
            ]
        sync_text_color = "text-gray-700"

    dot_payload = {
        "windowData": {
            "default": [
                {
                    "type": "div",
                    "props": {
                        "tw": f"flex flex-col w-full h-full p-3 {bg_color} {main_text_color}",
                        "children": [
                            {
                                "type": "div",
                                "props": {
                                    "tw": f"flex items-center border-b-2 {border_color} pb-1.5",
                                    "children": [
                                        {"type": "span", "props": {"tw": "text-3xl font-black tracking-tight text-white" if current_meeting else "text-3xl font-black tracking-tight text-green-700", "children": status_text}}
                                    ]
                                }
                            },
                            {
                                "type": "div",
                                "props": {
                                    "tw": "flex flex-col pt-2 pb-2",
                                    "children": subtext_children
                                }
                            },
                            {
                                "type": "div",
                                "props": {
                                    "tw": f"flex items-center border-t-2 {border_color} pt-1.5 mt-auto",
                                    "children": [
                                        {"type": "span", "props": {"tw": f"text-xs font-bold {sync_text_color}", "children": sync_time_str}}
                                    ]
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
        api_request_with_retry('post', dot_url, headers=dot_headers, json=dot_payload)
        print(f"Successfully updated Room Status display. Status: {status_text} | Sync: {sync_time_str}")
    except Exception as e:
        print(f"Error pushing to Dot. API after retries: {e}")

if __name__ == "__main__":
    update_meeting_room_status()
