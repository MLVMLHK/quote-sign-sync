import os
import time
import requests
from requests.exceptions import RequestException
from datetime import datetime, timezone, timedelta

ROBIN_SPACE_ID = "290741"
ROBIN_TOKEN = os.environ.get("ROBIN_TOKEN")
DOT_API_KEY = os.environ.get("DOT_API_KEY")
DOT_DEVICE_IDS = [d.strip().strip('"\'') for d in os.environ.get("DOT_DEVICE_ID", "").split(",") if d.strip().strip('"\'')]

HK_TZ = timezone(timedelta(hours=8))

def api_request_with_retry(method, url, retries=3, delay=2, **kwargs):
    for attempt in range(retries):
        try:
            response = requests.request(method, url, **kwargs)
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

def format_booker(event):
    for key in ['organizer', 'creator', 'user']:
        entity = event.get(key)
        if isinstance(entity, dict):
            name = entity.get("name")
            email = entity.get("email")
            if name:
                return f"Booked by: {name.strip()}"
            elif email:
                return f"Booked by: {email.strip()}"
    email = event.get("created_by_email") or event.get("organizer_email")
    if email:
        return f"Booked by: {email.strip()}"
    return "Booked by: Organizer"

def update_meeting_room_status():
    if not DOT_DEVICE_IDS:
        print("Error: No DOT_DEVICE_ID configured.")
        return

    now_utc = datetime.now(timezone.utc)
    now_hk = datetime.now(HK_TZ)
    
    # 1. Only execute on Monday to Friday (Monday=0, Friday=4)
    if now_hk.weekday() >= 5:
        print(f"Today is {now_hk.strftime('%A')}. Skipping update (Weekend sleep mode).")
        return

    # 2 & 3. Only execute between 07:58 and 19:58 HKT; otherwise sleep
    current_time_mins = now_hk.hour * 60 + now_hk.minute
    start_mins = 7 * 60 + 58   # 07:58 HKT
    end_mins = 19 * 60 + 58    # 19:58 HKT

    if not (start_mins <= current_time_mins <= end_mins):
        print(f"Current HKT time ({now_hk.strftime('%H:%M')}) is outside the 07:58 - 19:58 window. Devices remain in sleep mode.")
        return

    headers = {
        "Authorization": f"Access-Token {ROBIN_TOKEN}",
        "Accept": "application/json"
    }
    
    # Anchor query bounds strictly to HKT calendar day converted to UTC
    start_of_day_hk = now_hk.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_query_hk = start_of_day_hk + timedelta(days=7)
    
    start_of_query = start_of_day_hk.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    end_of_query = end_of_query_hk.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    
    url = f"https://api.robinpowered.com/v1.0/spaces/{ROBIN_SPACE_ID}/events"
    params = {
        "after": start_of_query,
        "before": end_of_query
    }
    
    try:
        response = api_request_with_retry('get', url, headers=headers, params=params, timeout=10)
        data = response.json()
        events = data.get("data", [])
    except Exception as e:
        print(f"Error fetching from Robin API after retries: {e}")
        return

    current_meeting = None
    today_future_meetings = []
    tomorrow_meetings = []
    weekend_meetings = []
    next_week_meetings = []

    today_date = now_hk.date()
    tomorrow_date = today_date + timedelta(days=1)

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
            
            event_obj = event.copy()
            event_obj['start_dt'] = parse_start
            event_obj['end_dt'] = parse_end
            event_hk_date = parse_start.astimezone(HK_TZ).date()
            
            if parse_start <= now_utc <= parse_end:
                current_meeting = event_obj
            elif parse_start > now_utc:
                if event_hk_date == today_date:
                    today_future_meetings.append(event_obj)
                elif event_hk_date == tomorrow_date:
                    tomorrow_meetings.append(event_obj)
                elif event_hk_date.weekday() in (5, 6):
                    weekend_meetings.append(event_obj)
                elif event_hk_date > today_date:
                    next_week_meetings.append(event_obj)
        except Exception as parse_err:
            print(f"Skipping event due to parse error: {parse_err}")

    # Sort upcoming lists chronologically
    today_future_meetings.sort(key=lambda x: x['start_dt'])
    tomorrow_meetings.sort(key=lambda x: x['start_dt'])
    weekend_meetings.sort(key=lambda x: x['start_dt'])
    next_week_meetings.sort(key=lambda x: x['start_dt'])

    date_str = f"Date: {now_hk.strftime('%d-%b-%y (%A)')}"
    sync_time_str = f"Last sync: {now_hk.strftime('%d/%m %H:%M')} HKT"

    if current_meeting:
        status_text = "CoLab: RESERVED"
        bg_color = "bg-black"
        main_text_color = "text-white"
        sub_text_color = "text-white"
        border_color = "border-gray-700"
        
        start_dt = current_meeting['start_dt']
        end_dt = current_meeting['end_dt']
        time_window = f"Time: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
        booker_str = format_booker(current_meeting)
        
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
            {"type": "span", "props": {"tw": f"text-xs font-bold {sub_text_color}", "children": booker_str}},
            {"type": "span", "props": {"tw": f"text-xs text-red-200 font-black", "children": remaining_text}}
        ]
        sync_text_color = "text-white"
    elif today_future_meetings:
        status_text = "CoLab: VACANT"
        bg_color = "bg-white"
        main_text_color = "text-black"
        sub_text_color = "text-black"
        border_color = "border-gray-300"
        
        next_meeting = today_future_meetings[0]
        next_start = next_meeting['start_dt'].astimezone(HK_TZ)
        next_end = next_meeting['end_dt'].astimezone(HK_TZ)
        booker_str = format_booker(next_meeting)
        
        subtext_children = [
            {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
            {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": f"Next: {next_start.strftime('%H:%M')} - {next_end.strftime('%H:%M')}"}},
            {"type": "span", "props": {"tw": f"text-xs font-bold {sub_text_color}", "children": booker_str}}
        ]
        sync_text_color = "text-black"
    else:
        status_text = "CoLab: VACANT"
        bg_color = "bg-white"
        main_text_color = "text-black"
        sub_text_color = "text-black"
        border_color = "border-gray-300"
        
        is_friday = (now_hk.weekday() == 4)
        
        if is_friday and not weekend_meetings:
            if next_week_meetings:
                next_meeting = next_week_meetings[0]
                nw_start = next_meeting['start_dt'].astimezone(HK_TZ)
                time_str = nw_start.strftime('%d-%b %H:%M')
                booker_str = format_booker(next_meeting)
                subtext_children = [
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation this week."}},
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "First reservation for next week"}},
                    {"type": "span", "props": {"tw": f"text-xs font-bold {sub_text_color}", "children": booker_str}},
                    {"type": "span", "props": {"tw": f"text-xs font-black text-black", "children": f"to start from: {time_str}"}}
                ]
            else:
                subtext_children = [
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation this week."}},
                    {"type": "span", "props": {"tw": f"text-xs font-black text-black", "children": "No upcoming reservations next week."}}
                ]
        elif is_friday and weekend_meetings:
            next_meeting = weekend_meetings[0]
            next_start = next_meeting['start_dt'].astimezone(HK_TZ)
            next_end = next_meeting['end_dt'].astimezone(HK_TZ)
            booker_str = format_booker(next_meeting)
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
                {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": f"Weekend: {next_start.strftime('%H:%M')} - {next_end.strftime('%H:%M')}"}},
                {"type": "span", "props": {"tw": f"text-xs font-bold {sub_text_color}", "children": booker_str}},
                {"type": "span", "props": {"tw": f"text-xs font-black text-black", "children": f"Starts at {next_start.strftime('%d-%b %H:%M')}"}}
            ]
        else:
            if tomorrow_meetings:
                next_meeting = tomorrow_meetings[0]
                tom_start = next_meeting['start_dt'].astimezone(HK_TZ)
                tom_time = tom_start.strftime('%H:%M')
                booker_str = format_booker(next_meeting)
                subtext_children = [
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation for today."}},
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "Tomorrow's first reservation"}},
                    {"type": "span", "props": {"tw": f"text-xs font-bold {sub_text_color}", "children": booker_str}},
                    {"type": "span", "props": {"tw": f"text-xs font-black text-black", "children": f"to start from: {tom_time}"}}
                ]
            else:
                all_future = weekend_meetings + next_week_meetings
                if all_future:
                    next_meeting = all_future[0]
                    fut_start = next_meeting['start_dt'].astimezone(HK_TZ)
                    fut_str = fut_start.strftime('%d-%b %H:%M')
                    booker_str = format_booker(next_meeting)
                    subtext_children = [
                        {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation for today."}},
                        {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "Next reservation"}},
                        {"type": "span", "props": {"tw": f"text-xs font-bold {sub_text_color}", "children": booker_str}},
                        {"type": "span", "props": {"tw": f"text-xs font-black text-black", "children": f"to start from: {fut_str}"}}
                    ]
                else:
                    subtext_children = [
                        {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
                        {"type": "span", "props": {"tw": f"text-xs font-black text-black", "children": "No more meetings scheduled."}}
                    ]
        sync_text_color = "text-black"

    dot_payload = {
        "refreshNow": True,  # Forces immediate refresh upon sync to overcome device sleep state
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

    for index, device_id in enumerate(DOT_DEVICE_IDS):
        dot_url = f"https://dot.mindreset.tech/api/authV2/open/device/{device_id}/canvas"
        try:
            if index > 0:
                time.sleep(0.5)
            api_request_with_retry('post', dot_url, headers=dot_headers, json=dot_payload, timeout=10)
            print(f"Successfully updated device {device_id}. Status: {status_text} | Sync: {sync_time_str}")
        except RequestException as e:
            resp_text = e.response.text if hasattr(e, 'response') and e.response is not None else "No response body"
            print(f"Error pushing to Dot API for device {device_id}: {e} | Response: {resp_text}")

if __name__ == "__main__":
    update_meeting_room_status()
