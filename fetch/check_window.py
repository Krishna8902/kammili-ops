from zoneinfo import ZoneInfo
from datetime import datetime
import os
import sys

# Exit 0 to run the pipeline, 2 to skip quietly (outside 06:00–22:00 London).
# Any other non-zero exit is a real failure. Manual dispatches and pull
# requests always bypass the window, so a test run gives a real signal.
def main(now=None, event_name=None):
    event_name = os.environ.get("GITHUB_EVENT_NAME") if event_name is None else event_name
    if event_name in ("workflow_dispatch", "pull_request"):
        print(f"{event_name}: bypassing operating-window check.")
        return 0
    now = now or datetime.now(ZoneInfo("Europe/London"))
    if not (6 <= now.hour < 22):
        print(f"Outside operating window ({now.strftime('%H:%M %Z')}), skipping.")
        return 2
    print(f"Inside operating window ({now.strftime('%H:%M %Z')}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
