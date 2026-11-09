import os
import time
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


def send_low_battery_email(device_id, battery_level):
    recipient = "michael.li@vml.com"
    subject = f"⚠️ Low Battery Alert: Meeting Room Display ({device_id})"
    body = (
        f"Hello Michael,\n\n"
        f"This is an automated notification from your meeting room sign manager.\n\n"
        f"Device ID: {device_id}\n"
        f"Current Battery Level: {battery_level}%\n\n"
        f"The battery level has dropped below the 15% threshold. Please recharge or replace "
        f"the device battery soon to prevent synchronization failures.\n\n"
        f"Best regards,\nMeeting Room Sign Automation"
    )
    
    print(f"ALERT: Battery for device {device_id} is at {battery_level}%. Sending notification email to {recipient}...")
    try:
        gmail.send_message(
            to=[recipient],
            subject=subject,
            body=body
        )
        print(f"Low battery email successfully sent for device {device_id}.")
    except Exception as e:
        print(f"Failed to send low battery email for device {device_id}: {e}")


def check_device_battery_status(device_id, dot_api_key):
    try:
        url = f"https://dot.mindreset.tech/api/authV2/open/device/{device_id}/status"
        headers = {
            "Authorization": f"Bearer {dot_api_key}",
            "Accept": "application/json"
        }
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            battery = data.get("battery") or data.get("batteryLevel") or data.get("data", {}).get("battery")
            if battery is not None:
                try:
                    battery_val = float(battery)
                    print(f"Device {device_id} battery level: {battery_val}%")
                    if battery_val < 15.0:
                        send_low_battery_email(device_id, battery_val)
                except ValueError:
                    pass
    except Exception as e:
        print(f"Could not check battery status for {device_id}: {e}")


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
            else:
                subtext_children = [
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation this week."}},
                    {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": "No upcoming reservations next week."}}
                ]
        elif is_friday and weekend_meetings:
            next_meeting = weekend_meetings[0]
            next_start = next_meeting['start_dt'].astimezone(HK_TZ)
            next_end = next_meeting['end_dt'].astimezone(HK_TZ)
            subtext_children = [
                {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
                {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": f"Weekend: {next_start.strftime('%H:%M')} - {next_end.strftime('%H:%M')}"}},
                {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": f"Starts at {next_start.strftime('%d-%b %H:%M')}"}}
            ]
        else:
            if tomorrow_meetings:
                tom_start = tomorrow_meetings[0]['start_dt'].astimezone(HK_TZ)
                tom_time = tom_start.strftime('%H:%M')
                subtext_children = [
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "No more reservation for today."}},
                    {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": "Tomorrow's first reservation"}},
                    {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": f"to start from: {tom_time}"}}
                ]
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
                else:
                    subtext_children = [
                        {"type": "span", "props": {"tw": f"text-xs font-extrabold {sub_text_color}", "children": date_str}},
                        {"type": "span", "props": {"tw": "text-xs font-black text-black", "children": "No more meetings scheduled."}}
                    ]
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

    return status_text, sync_time_str, window_data


def main():
    if not DOT_DEVICE_IDS:
        print("Error: No DOT_DEVICE_ID configured.")
        return

    now_utc = datetime.now(timezone.utc)
    now_hk = datetime.now(HK_TZ)

    # 1. Guard: Skip on weekends
    if now_hk.weekday() >= 5:
        print(f"Today is {now_hk.strftime('%A')}. Skipping update (Weekend mode).")
        return

    # 2. Guard: Skip outside 07:58 to 19:58 HKT
    current_time_mins = now_hk.hour * 60 + now_hk.minute
    start_mins = 7 * 60 + 58
    end_mins = 19 * 60 + 58
    if not (start_mins <= current_time_mins <= end_mins):
        print(f"Current HKT time ({now_hk.strftime('%H:%M')}) is outside active window. Skipping.")
        return

    print(f"Running one-shot meeting room sync at {now_hk.strftime('%H:%M')} HKT...")
    status_text, sync_time_str, window_data = fetch_robin_state(now_utc, now_hk)

    dot_headers = {
        "Authorization": f"Bearer {DOT_API_KEY}",
        "Content-Type": "application/json"
    }
    device_tasks_cache = {}

    for index, device_id in enumerate(DOT_DEVICE_IDS):
        if index > 0:
            time.sleep(1)

        # Check battery & send email alert if < 15%
        check_device_battery_status(device_id, DOT_API_KEY)

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
                    print(f"Updated {device_id} ({task_type}, {taskKey if 'taskKey' in locals() else 'task'}) -> {status_text}")
            else:
                payload = {
                    "taskType": "loop",
                    "refreshNow": True,
                    "windowData": window_data
                }
                api_request_with_retry('post', dot_url, headers=dot_headers, json=payload, timeout=10)
                print(f"Updated {device_id} (default loop) -> {status_text}")
        except RequestException as e:
            resp_text = e.response.text if hasattr(e, 'response') and e.response is not None else "No response body"
            print(f"Error updating device {device_id}: {e} | Response: {resp_text}")


if __name__ == "__main__":
    main()
