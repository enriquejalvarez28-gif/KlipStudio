#!/usr/bin/env python3
"""Klip Media lead CRM.

The database is a single CSV (leads.csv) so it can be opened in Excel /
Google Sheets or imported into Notion. This script never contacts anyone;
it only organizes leads for manual Instagram outreach.

Usage:
  python3 crm.py import research.json [--source-label TEXT]
  python3 crm.py queue [--size 10] [--out daily_queue.csv]
  python3 crm.py mark LEAD_ID STATUS [--date YYYY-MM-DD] [--note TEXT]
  python3 crm.py dashboard
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "leads.csv")

FIELDS = [
    "Lead ID", "Business Name", "Industry", "City", "Address", "Website", "Phone",
    "Instagram Username", "Instagram URL", "Instagram Status", "Decision Maker",
    "Public Business Email", "Firm Type",
    "Score Geo", "Score Industry", "Score Content", "Score Fit", "Score Contact",
    "Lead Score", "Priority", "Score Note",
    "Content Opportunity", "Recommended Service", "Personalized DM",
    "Date Discovered", "Date Contacted", "Outreach Status", "Follow-Up Date",
    "Notes", "Source URLs",
]

STATUSES = [
    "New Lead", "Ready to Contact", "Contacted", "Responded", "Interested",
    "Meeting Scheduled", "Not Interested", "Client", "Do Not Contact",
]
CONTACTED = {"Contacted", "Responded", "Interested", "Meeting Scheduled", "Not Interested", "Client"}
RESPONDED = {"Responded", "Interested", "Meeting Scheduled", "Not Interested", "Client"}
INTERESTED = {"Interested", "Meeting Scheduled", "Client"}
MEETINGS = {"Meeting Scheduled", "Client"}

# Geographic fit (max 20): distance from Klip Studio, Pembroke Pines.
GEO_POINTS = {
    "pembroke pines": 20,
    "miramar": 18, "weston": 18, "davie": 18, "cooper city": 18,
    "plantation": 16, "hollywood": 16, "sunrise": 16,
    "fort lauderdale": 14, "coral springs": 13, "parkland": 12,
}
MIAMI_DADE = {"miami", "doral", "coral gables", "aventura", "miami beach",
              "north miami", "kendall", "hialeah", "pinecrest"}
PALM_BEACH = {"boca raton", "delray beach", "west palm beach", "boynton beach",
              "wellington", "palm beach gardens"}


def geo_points(city):
    c = (city or "").strip().lower()
    if c in GEO_POINTS:
        return GEO_POINTS[c]
    if c in MIAMI_DADE:
        return 10
    if c in PALM_BEACH:
        return 6
    return 0


def priority(score):
    if score >= 80:
        return "High Priority"
    if score >= 60:
        return "Medium Priority"
    return "Low Priority"


def dedupe_key(row):
    """Normalized website domain, falling back to normalized business name."""
    site = (row.get("Website") or "").strip().lower()
    if site:
        host = urlparse(site if "://" in site else "http://" + site).netloc
        host = host.removeprefix("www.")
        if host:
            return "d:" + host
    name = re.sub(r"[^a-z0-9]", "", (row.get("Business Name") or "").lower())
    name = re.sub(r"(pa|pllc|llc|lawfirm|lawgroup|law|thelaw)$", "", name)
    return "n:" + name


def ig_username(url):
    if not url:
        return ""
    path = urlparse(url).path.strip("/").split("/")
    return "@" + path[0] if path and path[0] else ""


def load():
    if not os.path.exists(DB):
        return []
    with open(DB, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rows):
    with open(DB, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def next_id(rows):
    nums = [int(r["Lead ID"].split("-")[1]) for r in rows if r.get("Lead ID", "").startswith("KM-")]
    return max(nums, default=0) + 1


def score_row(r):
    parts = [int(r.get(k) or 0) for k in
             ("Score Geo", "Score Industry", "Score Content", "Score Fit", "Score Contact")]
    r["Lead Score"] = str(sum(parts))
    r["Priority"] = priority(sum(parts))


def cmd_import(args):
    """Merge a research JSON file (list of lead dicts using CRM field names)."""
    rows = load()
    seen = {dedupe_key(r): r for r in rows}
    with open(args.file, encoding="utf-8") as f:
        incoming = json.load(f)
    added = skipped = 0
    n = next_id(rows)
    today = dt.date.today().isoformat()
    for lead in incoming:
        key = dedupe_key(lead)
        if key in seen:
            skipped += 1
            continue
        row = {k: "" for k in FIELDS}
        row.update({k: str(v) for k, v in lead.items() if k in FIELDS})
        row["Lead ID"] = f"KM-{n:04d}"
        n += 1
        row["Date Discovered"] = row["Date Discovered"] or today
        row["Outreach Status"] = row["Outreach Status"] or "New Lead"
        row["Instagram Username"] = row["Instagram Username"] or ig_username(row["Instagram URL"])
        if not row["Score Geo"]:
            row["Score Geo"] = str(geo_points(row["City"]))
        score_row(row)
        rows.append(row)
        seen[key] = row
        added += 1
    save(rows)
    print(f"Imported {added} new leads, skipped {skipped} duplicates. Database: {len(rows)} leads.")


def queue_candidates(rows):
    return sorted(
        (r for r in rows if r["Outreach Status"] == "Ready to Contact"),
        key=lambda r: (-int(r["Lead Score"] or 0), r["Lead ID"]),
    )


def cmd_queue(args):
    """Top uncontacted leads. Never changes status: only the user marks a message sent."""
    q = queue_candidates(load())[: args.size]
    cols = ["Lead ID", "Business Name", "Industry", "City", "Instagram URL", "Content Opportunity",
            "Recommended Service", "Personalized DM", "Lead Score", "Priority", "Outreach Status"]
    out = args.out or os.path.join(HERE, f"daily_queue_{dt.date.today().isoformat()}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(q)
    for r in q:
        print(f'{r["Lead ID"]}  {r["Lead Score"]:>3}  {r["Business Name"]} ({r["City"]})  {r["Instagram URL"]}')
    print(f"\n{len(q)} leads written to {out}")


def cmd_mark(args):
    if args.status not in STATUSES:
        sys.exit(f"Unknown status. Choose one of: {', '.join(STATUSES)}")
    rows = load()
    for r in rows:
        if r["Lead ID"] == args.lead_id:
            day = args.date or dt.date.today().isoformat()
            r["Outreach Status"] = args.status
            if args.status == "Contacted" and not r["Date Contacted"]:
                r["Date Contacted"] = day
                r["Follow-Up Date"] = (dt.date.fromisoformat(day) + dt.timedelta(days=5)).isoformat()
            if args.status in {"Do Not Contact", "Not Interested", "Client"}:
                r["Follow-Up Date"] = ""
            if args.note:
                r["Notes"] = (r["Notes"] + " | " if r["Notes"] else "") + f"{day}: {args.note}"
            save(rows)
            print(f'{r["Lead ID"]} {r["Business Name"]} -> {args.status}')
            return
    sys.exit(f"No lead with ID {args.lead_id}")


def pct(num, den):
    return f"{num / den:.0%}" if den else "n/a (no data yet)"


def cmd_dashboard(_args):
    rows = load()
    st = [r["Outreach Status"] for r in rows]
    contacted = sum(s in CONTACTED or (s == "Do Not Contact" and r["Date Contacted"])
                    for s, r in zip(st, rows))
    responded = sum(s in RESPONDED or (s == "Do Not Contact" and r["Date Contacted"])
                    for s, r in zip(st, rows))
    meetings = sum(s in MEETINGS for s in st)
    qualified = sum(int(r["Lead Score"] or 0) >= 60 for r in rows)
    print(f"Total Leads Discovered   {len(rows)}")
    print(f"Qualified Leads (60+)    {qualified}")
    print(f"High-Priority Leads      {sum(int(r['Lead Score'] or 0) >= 80 for r in rows)}")
    print(f"Leads Contacted          {contacted}")
    print(f"Responses Received       {responded}")
    print(f"Interested Prospects     {sum(s in INTERESTED for s in st)}")
    print(f"Meetings Scheduled       {meetings}")
    print(f"Clients Acquired         {sum(s == 'Client' for s in st)}")
    print(f"Response Rate            {pct(responded, contacted)}   (responses / contacted)")
    print(f"Meeting Conversion Rate  {pct(meetings, responded)}   (meetings / responses)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("import"); s.add_argument("file"); s.set_defaults(fn=cmd_import)
    s = sub.add_parser("queue"); s.add_argument("--size", type=int, default=10)
    s.add_argument("--out"); s.set_defaults(fn=cmd_queue)
    s = sub.add_parser("mark"); s.add_argument("lead_id"); s.add_argument("status")
    s.add_argument("--date"); s.add_argument("--note"); s.set_defaults(fn=cmd_mark)
    s = sub.add_parser("dashboard"); s.set_defaults(fn=cmd_dashboard)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
