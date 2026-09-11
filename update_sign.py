import os
import time
import requests
from requests.exceptions import RequestException
from datetime import datetime, timezone, timedelta

ROBIN_SPACE_ID = "290741"
ROBIN_TOKEN = os.environ.get("ROBIN_TOKEN")
DOT_API_KEY = os.environ.get("DOT_API_KEY")
# Robustly strip both whitespace and accidental quotes from secret values
DOT_DEVICE_IDS = [d.strip().strip('"\'') for d in os.environ.get("DOT_DEVICE_ID", "").split(",") if d.strip().strip('"\'')]

HK_TZ = timezone(timedelta(hours=8))

def parse_iso_time(iso_str):
    if not iso_str:
        return None
    if len(iso_str) >= 5 and iso_str[-5] in ('+', '-') and iso_str[-3] != ':':
        iso_str = iso_str[:-2] + ':' + iso_str[-2:]
    return datetime.fromisoformat(iso_str)

def update_meeting_room_status():
    if not DOT_DEVICE_IDS:
        print("Error: No DOT_DEVICE_ID configured.")
        return

    headers = {
        "Authorization": f"Access-Token {ROBIN_TOKEN}",
        "Accept": "application/json"
    }
    
    now_utc = datetime.now(timezone.utc)
    now_hk = datetime.now(HK_TZ)

    # Skip updates on weekends (Saturday=5, Sunday=6)
    if now_hk.weekday() >= 5:
        print(f"Today is {now_hk.strftime('%A')}. Skipping update on weekends.")
        return

    # Sleep mode: Skip updates between 20:00 and 07:00 HKT
    if not (7 <= now_hk.hour < 20):
        print(f"Current HKT time ({now_hk.strftime('%H:%M')}) is outside operating hours (07:00 - 20:00). Skipping update.")
        return
    
    # Sleep mode: Skip updates between 20:00 and 07:00 HKT
    if not (7 <= now_hk.hour < 20):
        print(f"Current HKT time ({now_hk.strftime('%H:%M')}) is outside operating hours (07:00 - 20:00). Skipping update.")
        return

    start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
    end_of_day = now_utc.replace(hour=23, minute=59, second=59, microsecond=0).isoformat().replace("+00:00", "Z")
    
    url = f"https://api.robinpowered.com/v1.0/spaces/{ROBIN_SPACE_ID}/events"
    params = {
        "after": start_of_day,
        "before": end_of_day
    }
    
    # Use a persistent session for Robin API as well
    with requests.Session() as session:
        session.headers.update(headers)
        try:
            response = session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            events = data.get("data", [])
        except RequestException as e:
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
        status_text = "CoLab: RESERVED"
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
            {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
            {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": time_window}},
            {"type": "span", "props": {"tw": f"text-xs text-red-200 font-black", "children": remaining_text}}
        ]
        sync_text_color = "text-white"
    else:
        status_text = "CoLab: VACANT"
        bg_color = "bg-white"
        main_text_color = "text-black"
        sub_text_color = "text-black"
        border_color = "border-gray-300"
        
        if next_meeting:
            next_start = next_meeting['start_dt']
            next_title = next_meeting.get("title", "Upcoming Meeting")
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
                {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": f"Next: {next_title}"}},
                {"type": "span", "props": {"tw": f"text-xs font-black text-black", "children": f"Starts at {next_start.strftime('%H:%M')}"}}
            ]
        else:
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
                {"type": "span", "props": {"tw": f"text-xs font-black text-black", "children": "No more meetings today"}}
            ]
        sync_text_color = "text-black"

    dot_payload = {
        "windowData": {
            "default": [
                {
                    "type": "div",
                    "props": {
                        "tw": f"flex flex-col w-full h-full justify-between p-1.5 {bg_color} {main_text_color}",
                        "children": [
                            {
                                "type": "div",
                                "props": {
                                    "tw": f"flex items-center border-b {border_color} pb-0.5",
                                    "children": [
                                        {"type": "span", "props": {"tw": "text-2xl font-black tracking-tight text-white" if current_meeting else "text-2xl font-black tracking-tight text-green-700", "children": status_text}}
                                    ]
                                }
                            },
                            {
                                "type": "div",
                                "props": {
                                    "tw": "flex flex-col justify-between py-0.5",
                                    "children": subtext_children
                                }
                            },
                            {
                                "type": "div",
                                "props": {
                                    "tw": f"flex items-center border-t {border_color} pt-0.5",
                                    "children": [
                                        {"type": "span", "props": {"tw": f"text-xs font-extrabold {sync_text_color}", "children": sync_time_str}}
                                    ]
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }

    dot_headers = {
        "Authorization": f"Bearer {DOT_API_KEY}",
        "Content-Type": "application/json"
    }

    # Use a session for Dot API requests to reuse connections and prevent cold-start drops
    with requests.Session() as dot_session:
        dot_session.headers.update(dot_headers)
        for index, device_id in enumerate(DOT_DEVICE_IDS):
            dot_url = f"https://dot.mindreset.tech/api/authV2/open/device/{device_id}/canvas"
            try:
                # Brief pause between devices to avoid rate limiting or socket congestion
                if index > 0:
                    time.sleep(0.5)
                
                response = dot_session.post(dot_url, json=dot_payload, timeout=10)
                response.raise_for_status()
                print(f"Successfully updated device {device_id}. Status: {status_text} | Sync: {sync_time_str}")
            except RequestException as e:
                resp_text = e.response.text if hasattr(e, 'response') and e.response is not None else "No response body"
                print(f"Error pushing to Dot API for device {device_id}: {e} | Response: {resp_text}")

if __name__ == "__main__":
    update_meeting_room_status()
