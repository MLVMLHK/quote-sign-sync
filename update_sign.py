import os
import sys
import time
import signal
import requests
from requests.exceptions import RequestException
from datetime import datetime, timezone, timedelta

ROBIN_SPACE_ID = "290741"
ROBIN_TOKEN = os.environ.get("ROBIN_TOKEN")
DOT_API_KEY = os.environ.get("DOT_API_KEY")
DOT_DEVICE_IDS = [
    d.strip().strip('"\'')
    for d in os.environ.get("DOT_DEVICE_ID", "").split(",")
    if d.strip().strip('"\'')
]

HK_TZ = timezone(timedelta(hours=8))

ROBIN_POLL_INTERVAL_SECONDS = 60
RESERVED_HEARTBEAT_SECONDS = 900   # 15 mins when RESERVED
VACANT_HEARTBEAT_SECONDS = 1800    # 30 mins when VACANT
MAX_RUNTIME_MINS = int(os.environ.get("MAX_RUNTIME_MINS", "300"))


def handle_cancel_signal(signum, frame):
    print(f"Received stop signal ({signum}). Exiting daemon immediately.")
    sys.exit(0)


signal.signal(signal.SIGINT, handle_cancel_signal)
signal.signal(signal.SIGTERM, handle_cancel_signal)


def interruptible_sleep(seconds):
    """Sleeps in 1-second increments so GitHub cancel signals take effect immediately."""
    for _ in range(int(seconds)):
        time.sleep(1)


def api_request_with_retry(method, url, retries=3, delay=2, **kwargs):
    for attempt in range(retries):
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except RequestException as e:
            print(f"API request failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                interruptible_sleep(delay * (attempt + 1))
            else:
                raise


def parse_iso_time(iso_str):
    if not iso_str:
        return None
    if len(iso_str) >= 5 and iso_str[-5] in ('+', '-') and iso_str[-3] != ':':
        iso_str = iso_str[:-2] + ':' + iso_str[-2:]
    return datetime.fromisoformat(iso_str)


def discover_canvas_tasks(device_id, dot_api_key):
    headers = {
        "Authorization": f"Bearer {dot_api_key}",
        "Accept": "application/json"
    }
    discovered = []

    for task_type in ("loop", "fixed"):
        url = f"https://dot.mindreset.tech/api/authV2/open/device/{device_id}/{task_type}/list"
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                body = res.json()
                items = body.get("data", body) if isinstance(body, dict) else body
                if isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        item_str = str(item).upper()
                        key = item.get("key") or item.get("taskKey") or item.get("id")
                        if key and ("CANVAS" in item_str or len(items) == 1):
                            discovered.append((task_type, str(key)))
        except Exception as e:
            print(f"Note: Could not query {task_type} list for {device_id}: {e}")

    return discovered


def fetch_robin_state(now_utc, now_hk):
    headers = {
        "Authorization": f"Access-Token {ROBIN_TOKEN}",
        "Accept": "application/json"
    }

    start_of_day_hk = now_hk.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_query_hk = start_of_day_hk + timedelta(days=7)

    start_of_query = start_of_day_hk.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    end_of_query = end_of_query_hk.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    url = f"https://api.robinpowered.com/v1.0/spaces/{ROBIN_SPACE_ID}/events"
    params = {
        "after": start_of_query,
        "before": end_of_query
    }

    response = api_request_with_retry('get', url, headers=headers, params=params, timeout=10)
    events = response.json().get("data", [])

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

    today_future_meetings.sort(key=lambda x: x['start_dt'])
    tomorrow_meetings.sort(key=lambda x: x['start_dt'])
    weekend_meetings.sort(key=lambda x: x['start_dt'])
    next_week_meetings.sort(key=lambda x: x['start_dt'])

    date_str = f"Date: {now_hk.strftime('%d-%b-%y (%A)')}"
    sync_time_str = f"Last sync: {now_hk.strftime('%d/%m %H:%M')} HKT"
    is_reserved = bool(current_meeting)

    if current_meeting:
        status_text = "CoLab: RESERVED"
        bg_color = "bg-black"
        main_text_color = "text-white"
        sub_text_color = "text-white"
        border_color = "border-gray-700"

        start_dt = current_meeting['start_dt'].astimezone(HK_TZ)
        end_dt = current_meeting['end_dt'].astimezone(HK_TZ)
        time_window = f"Time: {start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"

        remaining_seconds = (current_meeting['end_dt'] - now_utc).total_seconds()
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
            {"type": "span", "props": {"tw": "text-xs text-red-200 font-black", "children": remaining_text}}
        ]
        sync_text_color = "text-white"
        state_signature = f"RESERVED|{time_window}"

    elif today_future_meetings:
        status_text = "CoLab: VACANT"
        bg_color = "bg-white"
        main_text_color = "text-black"
        sub_text_color = "text-black"
        border_color = "border-gray-300"

        next_meeting = today_future_meetings[0]
        next_start = next_meeting['start_dt'].astimezone(HK_TZ)
        next_end = next_meeting['end_dt'].astimezone(HK_TZ)
        next_str = f"Next: {next_start.strftime('%H:%M')} - {next_end.strftime('%H:%M')}"
        subtext_children = [
            {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
            {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": next_str}}
        ]
        sync_text_color = "text-black"
        state_signature = f"VACANT_TODAY|{next_str}"

    else:
        status_text = "CoLab: VACANT"
        bg_color = "bg-white"
        main_text_color = "text-black"
        sub_text_color = "text-black"
        border_color = "border-gray-300"

        is_friday = (now_hk.weekday() == 4)

        if is_friday and not weekend_meetings:
            if next_week_meetings:
                nw_start = next_week_meetings[0]['start_dt'].astimezone(HK_TZ)
                time_str = nw_start.strftime('%d-%b %H:%M')
                subtext_children = [
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation this week."}},
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "First reservation for next week"}},
                    {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": f"to start from: {time_str}"}}
                ]
                state_signature = f"VACANT_NW|{time_str}"
            else:
                subtext_children = [
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation this week."}},
                    {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": "No upcoming reservations next week."}}
                ]
                state_signature = "VACANT_NONE_WEEK"
        elif is_friday and weekend_meetings:
            next_meeting = weekend_meetings[0]
            next_start = next_meeting['start_dt'].astimezone(HK_TZ)
            next_end = next_meeting['end_dt'].astimezone(HK_TZ)
            wk_str = f"{next_start.strftime('%d-%b %H:%M')}-{next_end.strftime('%H:%M')}"
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
                {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": f"Weekend: {next_start.strftime('%H:%M')} - {next_end.strftime('%H:%M')}"}},
                {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": f"Starts at {next_start.strftime('%d-%b %H:%M')}"}}
            ]
            state_signature = f"VACANT_WK|{wk_str}"
        else:
            if tomorrow_meetings:
                tom_start = tomorrow_meetings[0]['start_dt'].astimezone(HK_TZ)
                tom_time = tom_start.strftime('%H:%M')
                subtext_children = [
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation for today."}},
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "Tomorrow's first reservation"}},
                    {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": f"to start from: {tom_time}"}}
                ]
                state_signature = f"VACANT_TOM|{tom_time}"
            else:
                all_future = weekend_meetings + next_week_meetings
                if all_future:
                    fut_start = all_future[0]['start_dt'].astimezone(HK_TZ)
                    fut_str = fut_start.strftime('%d-%b %H:%M')
                    subtext_children = [
                        {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation for today."}},
                        {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "Next reservation"}},
                        {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": f"to start from: {fut_str}"}}
                    ]
                    state_signature = f"VACANT_FUT|{fut_str}"
                else:
                    subtext_children = [
                        {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
                        {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": "No more meetings scheduled."}}
                    ]
                    state_signature = f"VACANT_EMPTY|{date_str}"
        sync_text_color = "text-black"

    window_data = {
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
                                    {
                                        "type": "span",
                                        "props": {
                                            "tw": "text-2xl font-black tracking-tight text-white" if current_meeting else "text-2xl font-black tracking-tight text-green-700",
                                            "children": status_text
                                        }
                                    }
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
                                    {
                                        "type": "span",
                                        "props": {
                                            "tw": f"text-xs font-extrabold {sync_text_color}",
                                            "children": sync_time_str
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            }
        ]
    }

    return status_text, sync_time_str, state_signature, is_reserved, window_data


def push_to_dot_devices(window_data, status_text, sync_time_str, device_tasks_cache):
    dot_headers = {
        "Authorization": f"Bearer {DOT_API_KEY}",
        "Content-Type": "application/json"
    }

    for index, device_id in enumerate(DOT_DEVICE_IDS):
        if index > 0:
            interruptible_sleep(1)

        dot_url = f"https://dot.mindreset.tech/api/authV2/open/device/{device_id}/canvas"
        tasks = device_tasks_cache.get(device_id)
        if tasks is None:
            tasks = discover_canvas_tasks(device_id, DOT_API_KEY)
            device_tasks_cache[device_id] = tasks

        try:
            if tasks:
                for task_type, task_key in tasks:
                    payload = {
                        "taskType": task_type,
                        "taskKey": task_key,
                        "refreshNow": True,
                        "windowData": window_data
                    }
                    api_request_with_retry('post', dot_url, headers=dot_headers, json=payload, timeout=10)
                    print(f"[{sync_time_str}] Updated {device_id} (taskType={task_type}, taskKey={task_key}) -> {status_text}")
            else:
                payload = {
                    "taskType": "loop",
                    "refreshNow": True,
                    "windowData": window_data
                }
                api_request_with_retry('post', dot_url, headers=dot_headers, json=payload, timeout=10)
                print(f"[{sync_time_str}] Updated {device_id} (default loop) -> {status_text}")

        except RequestException as e:
            resp_text = e.response.text if hasattr(e, 'response') and e.response is not None else "No response body"
            print(f"Error pushing to Dot API for device {device_id}: {e} | Response: {resp_text}")


def run_workday_daemon():
    if not DOT_DEVICE_IDS:
        print("Error: No DOT_DEVICE_ID configured.")
        return

    job_start_time = time.time()
    device_tasks_cache = {}
    last_state_signature = None
    last_push_timestamp = 0

    print(f"Starting Battery-Balanced Workday Daemon (max shift runtime: {MAX_RUNTIME_MINS} mins)...")

    while True:
        elapsed_mins = (time.time() - job_start_time) / 60.0
        if elapsed_mins >= MAX_RUNTIME_MINS:
            print(f"Reached shift limit ({MAX_RUNTIME_MINS} mins). Handing over to next shift.")
            break

        now_utc = datetime.now(timezone.utc)
        now_hk = datetime.now(HK_TZ)

        if now_hk.weekday() >= 5:
            print(f"Today is {now_hk.strftime('%A')}. Weekend sleep mode.")
            break

        current_time_mins = now_hk.hour * 60 + now_hk.minute
        start_mins = 7 * 60 + 58   # 07:58 HKT
        end_mins = 19 * 60 + 58    # 19:58 HKT

        if current_time_mins > end_mins:
            print(f"Current HKT time ({now_hk.strftime('%H:%M')}) is past 19:58 HKT. Entering night sleep mode.")
            break

        if current_time_mins < start_mins:
            wait_mins = start_mins - current_time_mins
            sleep_secs = min(300, max(15, wait_mins * 60))
            print(f"Current HKT time is {now_hk.strftime('%H:%M')} (before 07:58 HKT). Waiting {sleep_secs}s...")
            interruptible_sleep(sleep_secs)
            continue

        try:
            status_text, sync_time_str, state_signature, is_reserved, window_data = fetch_robin_state(now_utc, now_hk)
            now_ts = time.time()

            target_heartbeat = RESERVED_HEARTBEAT_SECONDS if is_reserved else VACANT_HEARTBEAT_SECONDS

            state_changed = (state_signature != last_state_signature)
            heartbeat_due = ((now_ts - last_push_timestamp) >= target_heartbeat)

            if state_changed or heartbeat_due:
                reason = "INSTANT BOOKING/STATUS CHANGE" if state_changed else f"PERIODIC HEARTBEAT ({target_heartbeat // 60}m)"
                print(f"Triggering Dot push [{reason}]: {state_signature}")
                push_to_dot_devices(window_data, status_text, sync_time_str, device_tasks_cache)
                last_state_signature = state_signature
                last_push_timestamp = now_ts
        except Exception as e:
            print(f"Error during sync cycle: {e}")

        interruptible_sleep(ROBIN_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_workday_daemon()
