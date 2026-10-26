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

def get_device_battery(device_id, dot_api_key):
    headers = {
        "Authorization": f"Bearer {dot_api_key}",
        "Accept": "application/json"
    }
    
    # Method 1: Try querying the account devices list
    try:
        url_list = "https://dot.mindreset.tech/api/authV2/open/devices"
        res = requests.get(url_list, headers=headers, timeout=5)
        if res.status_code == 200:
            body = res.json()
            devices = body.get("data", body)
            if isinstance(devices, list):
                for dev in devices:
                    dev_id = str(dev.get("id") or dev.get("serial_number") or dev.get("device_id") or dev.get("deviceId") or "")
                    if device_id in dev_id or dev_id in device_id:
                        batt = (
                            dev.get("battery") or 
                            dev.get("battery_level") or 
                            dev.get("batteryLevel") or 
                            dev.get("level") or
                            dev.get("percentage")
                        )
                        if batt is not None:
                            if isinstance(batt, (int, float)):
                                return f"{int(batt)}%"
                            return str(batt).strip()
    except Exception as e:
        print(f"Could not fetch devices list for battery: {e}")

    # Method 2: Fall back to individual device status endpoint
    try:
        url_status = f"https://dot.mindreset.tech/api/authV2/open/device/{device_id}/status"
        res = requests.get(url_status, headers=headers, timeout=5)
        print(f"Battery API Response [{res.status_code}]: {res.text}")
        
        if res.status_code == 200:
            body = res.json()
            status_data = body.get("data", body)
            if isinstance(status_data, dict):
                for k in ['battery', 'battery_level', 'batteryLevel', 'level', 'percentage', 'soc']:
                    val = status_data.get(k)
                    if val is not None:
                        if isinstance(val, (int, float)):
                            return f"{int(val)}%"
                        return str(val).strip()
    except Exception as e:
        print(f"Could not fetch battery for {device_id}: {e}")
        
    return "--%"

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
