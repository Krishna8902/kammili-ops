"""Write realistic sample dumps into raw/ so you can see the page before
any API is connected. Delete raw/*.json once the real fetchers run."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAW = Path(__file__).resolve().parent / "raw"
RAW.mkdir(exist_ok=True)
today = date.today()
now = datetime.now(timezone.utc)

props = [
    {"id": 1, "name": "Crosshall Street"},
    {"id": 2, "name": "Duke Street 2B"},
    {"id": 3, "name": "Ancoats Loft"},
    {"id": 4, "name": "Deansgate Studio"},
    {"id": 5, "name": "Baltic Triangle"},
    {"id": 6, "name": "Northern Quarter 4"},
    {"id": 7, "name": "Salford Quays 11"},
    {"id": 8, "name": "Ropewalks 3A"},
    {"id": 9, "name": "Castlefield 6"},
]

def bk(i, pid, start, nights, guest, status="active", cleaner=None):
    return {
        "tags": [{"name": f"cleaner:{cleaner}"}] if cleaner else [],
        "id": 1000 + i,
        "property_id": pid,
        "guest_name": guest,
        "arrival": (today + timedelta(days=start)).isoformat(),
        "departure": (today + timedelta(days=start + nights)).isoformat(),
        "status": status,
        "check_in": "15:00",
        "check_out": "10:00",
    }

bookings = [
    bk(1, 1, -2, 2, "M. Adeyemi"),
    bk(2, 1, 0, 3, "R. Okonkwo", cleaner="Aneta"),
    bk(3, 3, -4, 4, "J. Whitfield"),
    bk(4, 3, 0, 2, "S. Patel"),
    bk(5, 2, 0, 5, "L. Brennan", cleaner="Marek"),
    bk(6, 4, -1, 6, "T. Nowak"),
    bk(7, 5, 2, 4, "C. Mensah"),
    bk(8, 6, -3, 9, "D. Ferreira"),
    bk(9, 7, 1, 3, "A. Hussain"),
    bk(10, 2, 8, 4, "K. Lindqvist"),
    bk(11, 4, 9, 5, "P. Sorensen"),
    bk(12, 6, 12, 7, "Contractor crew"),
    bk(13, 5, 14, 6, "N. Castellano"),
    bk(14, 7, 10, 4, "B. Osei"),
    bk(15, 1, 6, 3, "E. Vasquez"),
    bk(16, 3, 11, 5, "G. Bianchi"),
]

# Cleaning comes from booking tags above. Ancoats Loft has none on
# purpose. That is the point of the page.

messages = [
    {"property": "Salford Quays 11", "guest": "A. Hussain", "answered": False,
     "received_utc": (now - timedelta(hours=14)).isoformat()},
    {"property": "Baltic Triangle", "guest": "C. Mensah", "answered": False,
     "received_utc": (now - timedelta(hours=5)).isoformat()},
    {"property": "Castlefield 6", "guest": "Enquiry", "answered": True,
     "received_utc": (now - timedelta(hours=20)).isoformat()},
]

maintenance = [
    {"summary": "Boiler pressure dropping", "property": "Ropewalks 3A",
     "opened": (today - timedelta(days=5)).isoformat(), "status": "open",
     "urgent": True, "assigned_to": "Qasim"},
    {"summary": "Bathroom extractor noisy", "property": "Deansgate Studio",
     "opened": (today - timedelta(days=4)).isoformat(), "status": "open",
     "urgent": False, "assigned_to": None},
]

pipeline = {
    "new_this_week": 4,
    "stale": [
        {"name": "Hayan Butt", "days": 11, "stage": "Viewing booked"},
        {"name": "Whitmore Lettings", "days": 8, "stage": "Proposal sent"},
    ],
}

for name, data in [("ownerrez_properties", props), ("ownerrez_bookings", bookings),
                   ("messages", messages),
                   ("maintenance", maintenance), ("ghl_pipeline", pipeline)]:
    (RAW / f"{name}.json").write_text(json.dumps(data, indent=1))
print(f"sample data written to {RAW}")
