from zoneinfo import ZoneInfo
from datetime import datetime
import os
import sys

# Manual (workflow_dispatch) runs always bypass the window, so a test run
# gives a real signal instead of a silent skip. Scheduled/cron runs, and
# local runs (no GITHUB_EVENT_NAME set), keep the window gate as-is.
if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
    print("Manual run: bypassing operating-window check.")
else:
    _now = datetime.now(ZoneInfo("Europe/London"))
    if not (6 <= _now.hour < 22):
        print(f"Outside operating window ({_now.strftime('%H:%M %Z')}), skipping.")
        sys.exit(1)
