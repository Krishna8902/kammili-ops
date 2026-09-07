from zoneinfo import ZoneInfo
from datetime import datetime
import sys

_now = datetime.now(ZoneInfo("Europe/London"))
if not (6 <= _now.hour < 22):
    print(f"Outside operating window ({_now.strftime('%H:%M %Z')}), skipping.")
    sys.exit(1)
