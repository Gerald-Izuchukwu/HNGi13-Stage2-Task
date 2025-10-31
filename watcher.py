import os
import json
import time
import requests
import datetime
from collections import deque
import re
from threading import Lock

print("Watcher started and monitoring /var/log/nginx/access.log", flush=True)


# --- Configuration (Global Constants) ---
LOG_FILE = '/var/log/nginx/access.log'
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
MAINTENANCE_MODE = os.environ.get('MAINTENANCE_MODE', 'False').lower() in ('true', '1')
ALERT_COOLDOWN_SEC = int(os.environ.get('ALERT_COOLDOWN_SEC', 60))
ERROR_RATE_THRESHOLD = float(os.environ.get('ERROR_RATE_THRESHOLD', 0.01))
WINDOW_SIZE = int(os.environ.get('WINDOW_SIZE', 60)) # Time window in seconds

# --- State Management ---
class State:
    """Manages the current state for rate limiting and error tracking."""
    def __init__(self):
        # Last time an alert was successfully sent
        self.last_alert_time = 0 
        # State to track if an error rate alert is currently active
        self.error_alert_active = False 
        # A deque to store (timestamp, status_code) tuples for the sliding window
        self.request_window = deque()
        # Thread safety lock (important if this were multi-threaded, but good practice)
        self.lock = Lock()


state = State()

# --- Utility Functions ---

def get_current_pool(active_pool_env):
    """
    Determines the current active pool based on the Nginx log entry.
    Since Nginx logs both, we check the one that returned a 200.
    """
    # The first pool in the upstream_addr is the primary one Nginx tried
    primary_pool = "blue" if os.environ.get('ACTIVE_POOL') == "blue" else "green"
    secondary_pool = "green" if primary_pool == "blue" else "blue"

    # We can't parse the log here, so we just return the value from the environment
    return active_pool_env


def format_slack_message(title, details, color="danger"):
    """Creates the standard Slack payload structure."""
    SLACK_BOT_NAME = "Chaos Watcher 🤖"
    SLACK_BOT_ICON = ":robot_face:"

    return {
        "username": SLACK_BOT_NAME, 
        "icon_emoji": SLACK_BOT_ICON, 
        "text": f"🚨 *{title}*",
        "attachments": [{
            "color": color,
            "fields": [
                {"title": "Details", "value": details, "short": False},
                {"title": "Timestamp", "value": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'), "short": True}
            ]
        }]
    }


def send_slack_alert(title, details, color="danger"):
    """Posts a rich, formatted alert to Slack, with robust error logging and state updates."""

    # 1. Maintenance and Cooldown Checks
    if MAINTENANCE_MODE:
        print(f"MAINTENANCE MODE: Suppressing alert: {title}")
        return

    current_time = time.time()
    if (current_time - state.last_alert_time) < ALERT_COOLDOWN_SEC:
        print(f"Alert suppressed due to cooldown ({ALERT_COOLDOWN_SEC}s).")
        return

    # Check for Error Rate Alert deduplication
    if state.error_alert_active and "Error Rate High" in title:
        print("Skipping duplicate Error Rate alert.")
        return
    
    # 2. Payload Construction
    payload = format_slack_message(title, details, color)
        
    print(f"--- Attempting to Send Alert: {title} ---")

    # 3. Network Call and Error Handling
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        print(f"DEBUG: Sending alert to Slack with payload: {json.dumps(payload)}")


        # Successful HTTP connection, but check if Slack accepted the payload (200 OK)
        if response.status_code != 200:
            print(f"SLACK API REJECTED: Failed to send message. HTTP Status: {response.status_code}")
            print(f"SLACK API REJECTED: Response Content: {response.text}")
            
        else:
            # 🚀 SUCCESS PATH
            print("SLACK SUCCESS: Alert payload sent successfully.")
            
            # Update state only if the alert was successfully sent (HTTP 200)
            state.last_alert_time = current_time 
            if "Error Rate High" in title:
                state.error_alert_active = True
            elif "Failover Detected" in title:
                state.error_alert_active = False 

    except requests.exceptions.RequestException as e:
        # ❌ NETWORK FAILURE PATH
        print(f"SLACK NETWORK ERROR: Request failed: {e}")
        
    except Exception as e:
        # ⚠️ UNEXPECTED CODE FAILURE PATH
        print(f"SLACK UNEXPECTED ERROR: {type(e).__name__}: {e}")


def update_request_window(log_entry):
    """
    Parses a log entry, updates the request window, and checks for error rate alerts.
    """
    try:
        data = json.loads(log_entry)
        
        # We only care about Nginx's final status code
        status_code = int(data.get('status', 0))
        
        current_time = time.time()

        with state.lock:
            # Add new request and status
            state.request_window.append((current_time, status_code))
            
            # Clean up old requests outside the window
            # The 'time' field in Nginx log is not reliable for this, so we use
            # the current Python time when the log was read.
            cutoff_time = current_time - WINDOW_SIZE
            while state.request_window and state.request_window[0][0] < cutoff_time:
                state.request_window.popleft()

            # Check for Failover Alert
            # A failover event has two upstream statuses: one 5xx (failed), one 200 (retried)
            upstream_statuses_str = data.get('upstream_status', '')
            if '50' in upstream_statuses_str and '200' in upstream_statuses_str:
                details = f"A request to the primary pool failed and successfully recovered using the secondary pool. Upstream Statuses: {upstream_statuses_str}"
                send_slack_alert("Failover Detected! 🔄", details, color="warning")

            # Check for Error Rate Alert
            total_requests = len(state.request_window)
            error_requests = sum(1 for _, code in state.request_window if 500 <= code <= 599)
            
            if total_requests > 0:
                error_rate = error_requests / total_requests
                
                if error_rate >= ERROR_RATE_THRESHOLD and total_requests > 5:
                    details = (
                        f"Current error rate ({error_rate:.2%}) exceeds the threshold ({ERROR_RATE_THRESHOLD:.2%}). "
                        f"5xx errors detected: {error_requests} out of {total_requests} requests in the last {WINDOW_SIZE}s."
                    )
                    send_slack_alert("Error Rate High 🚨", details, color="danger")
                elif state.error_alert_active and error_rate < (ERROR_RATE_THRESHOLD / 2):
                    # Auto-resolve alert
                    state.error_alert_active = False
                    details = f"The error rate has dropped below the recovery threshold ({error_rate:.2%})."
                    send_slack_alert("Error Rate Resolved ✅", details, color="good")
            

    except json.JSONDecodeError:
        # This can happen if the log line isn't a complete JSON object yet
        pass
    except Exception as e:
        print(f"Error processing log line: {e}")
        

def tail_logs():
    """Tails the Nginx log file continuously."""
    if not os.path.exists(LOG_FILE):
        print(f"CRITICAL ERROR: Log file not found at {LOG_FILE}.", flush=True)
        return

    print(f"Watcher started and monitoring {LOG_FILE}", flush=True)

    with open(LOG_FILE, 'r') as f:
        f.seek(0, os.SEEK_END)
        print("Watcher started, now tailing new log lines...", flush=True)

        while True:
            line = f.readline()
            if not line:
                time.sleep(1)
                continue
            
            print(f"DEBUG: New line detected: {line.strip()}", flush=True)
            try:
                update_request_window(line)
            except Exception as e:
                print(f"ERROR processing line: {e}", flush=True)


# --- Main Execution ---

if __name__ == "__main__":
    # 🚨 CRITICAL STARTUP CHECK 🚨
    if not SLACK_WEBHOOK_URL:
        print("----------------------------------------------------------------------")
        print("CRITICAL ERROR: SLACK_WEBHOOK_URL environment variable is NOT set!")
        print("ALERT WATCHER SHUTTING DOWN.")
        print("----------------------------------------------------------------------")
        exit(1) # Exit immediately if the most crucial config is missing
    
    # If the URL is set, we proceed to start the tailing process
    tail_logs()









# def send_slack_alert(active_pool, error_rate, total_requests, error_requests):
#     """Send an alert message to Slack."""
#     if not SLACK_WEBHOOK_URL:
#         print("❌ No Slack webhook URL configured.")
#         return

#     message = {
#         "text": f":rotating_light: *High error rate detected in {active_pool.upper()} pool!*",
#         "blocks": [
#             {
#                 "type": "section",
#                 "text": {
#                     "type": "mrkdwn",
#                     "text": (
#                         f"🚨 *High error rate detected!*\n\n"
#                         f"*Active pool:* `{active_pool}`\n"
#                         f"*Error rate:* `{error_rate:.2f}%`\n"
#                         f"*Total requests:* `{total_requests}`\n"
#                         f"*Failed requests:* `{error_requests}`"
#                     ),
#                 },
#             }
#         ],
#     }

#     try:
#         resp = requests.post(SLACK_WEBHOOK_URL, json=message)
#         if resp.status_code != 200:
#             print(f"⚠️ Slack webhook returned {resp.status_code}: {resp.text}", flush=True)
#         else:
#             print("✅ Slack alert sent successfully.", flush=True)
#     except Exception as e:
#         print(f"❌ Error sending Slack alert: {e}", flush=True)



# def tail_logs():
#     """Continuously tails the Nginx log file, even after rotation or truncation."""
#     print(f"Log watcher started. Monitoring {LOG_FILE}...")

#     # Ensure file exists
#     while not os.path.exists(LOG_FILE):
#         print(f"Waiting for log file {LOG_FILE} to appear...")
#         time.sleep(2)

#     # Track the last file size
#     file_inode = None
#     file_position = 0

#     while True:
#         try:
#             with open(LOG_FILE, 'r') as f:
#                 # Move to end only if starting fresh
#                 if file_inode != os.fstat(f.fileno()).st_ino:
#                     f.seek(0, os.SEEK_END)
#                     file_inode = os.fstat(f.fileno()).st_ino
#                     print("Watcher started, now tailing new log lines...", flush=True)

#                 while True:
#                     line = f.readline()
#                     if not line:
#                         # Check if file was truncated or replaced
#                         if os.stat(LOG_FILE).st_ino != file_inode:
#                             print("Detected log rotation/truncation — reopening file...", flush=True)
#                             break  # Break inner loop to reopen file
#                         time.sleep(1)
#                         continue

#                     # Process the new line
#                     update_request_window(line)

#         except FileNotFoundError:
#             print(f"Log file {LOG_FILE} not found, retrying in 2s...", flush=True)
#             time.sleep(2)
#         except Exception as e:
#             print(f"Unexpected error while tailing logs: {e}", flush=True)
#             time.sleep(2)

# def tail_logs():
#     """Tails the Nginx log file continuously."""
    
#     # 🚨 CRITICAL: Check the log file exists before starting
#     if not os.path.exists(LOG_FILE):
#         print(f"CRITICAL ERROR: Log file not found at {LOG_FILE}. Nginx volume mount failed.")
#         return

#     print("Log watcher started. Monitoring Nginx logs...")
    

#     with open(LOG_FILE, 'r') as f:

#         f.seek(0, os.SEEK_END)
#         print("Watcher started, now tailing new log lines...", flush=True)

#         while True:
#             line = f.readline()
#             if not line:
#                 time.sleep(1)
#                 continue
#             update_request_window(line)


# SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
