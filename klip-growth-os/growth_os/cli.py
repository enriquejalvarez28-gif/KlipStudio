"""Klip Growth OS CLI. Usage: python -m growth_os <command> ..."""

import argparse
import json

from growth_os import brands, db, scheduler, seed, vault
from growth_os.connectors import podcast, youtube


def main(argv=None):
    p = argparse.ArgumentParser(prog="growth_os")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the owner app + background scheduler on 127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    s.add_argument("--no-scheduler", action="store_true")
    sub.add_parser("init", help="create RYJ Media (+ topics) and the synthetic demo brand")
    sub.add_parser("seed-demo", help="create the synthetic demo brand only")
    s = sub.add_parser("brand", help="create another brand")
    s.add_argument("name")
    sub.add_parser("status", help="brands, account states, schedules")
    s = sub.add_parser("run", help="run one job now in the foreground")
    s.add_argument("kind", choices=sorted(__import__("growth_os.jobs", fromlist=["x"]).REGISTRY))
    s.add_argument("--brand")
    s = sub.add_parser("sync", help="small verification sync for an assigned YouTube account")
    s.add_argument("brand")
    s.add_argument("account_row")
    s = sub.add_parser("import", help="import a Spotify/Apple export CSV into a verified show")
    s.add_argument("brand")
    s.add_argument("account_row")
    s.add_argument("csv")
    a = p.parse_args(argv)

    if a.cmd == "serve":
        from growth_os.server import serve
        return serve(a.port, open_browser=a.open, with_scheduler=not a.no_scheduler)

    conn = db.connect()
    if a.cmd == "init":
        seed.ensure_ryj(conn)
        print(json.dumps(seed.seed_demo(conn)))
        scheduler.ensure_defaults(conn)
        print("ready: RYJ Media + synthetic demo brand")
    elif a.cmd == "seed-demo":
        print(json.dumps(seed.seed_demo(conn)))
    elif a.cmd == "brand":
        print(brands.create_brand(conn, a.name, "owner"))
    elif a.cmd == "status":
        print(f"data folder: {db.DATA_DIR}")
        print(f"YouTube OAuth client configured: {bool(vault.load_client('youtube'))}")
        for b in brands.list_brands(conn):
            print(f"\n{b['display_name']} ({b['tenant_id']}, {b['kind']})")
            rows = brands.accounts(conn, b["tenant_id"])
            seen = {r["platform"] for r in rows}
            for r in rows:
                print(f"  {r['platform']:<15} {r['state']:<22} {r['platform_account_id']}  {r['account_name']}"
                      f"  row={r['id']} as_of={r['data_as_of'] or '-'}")
            for pl in brands.PLATFORMS:
                if pl not in seen:
                    print(f"  {pl:<15} NOT_CONNECTED")
        print()
        for s in conn.execute("SELECT * FROM schedules ORDER BY name"):
            print(f"  {s['name']:<16} next {s['next_run_at']}  last {s['last_status'] or '-'}")
    elif a.cmd == "run":
        from growth_os.jobs import REGISTRY
        print(json.dumps(REGISTRY[a.kind](conn, a.brand, lambda p, m="": print(f"  {p}% {m}")), indent=1, default=str)[:4000])
    elif a.cmd == "sync":
        print(json.dumps(youtube.sync_sample(conn, a.brand, a.account_row, client=vault.load_client("youtube")), indent=1))
    elif a.cmd == "import":
        print(json.dumps(podcast.import_csv(conn, a.brand, a.account_row, a.csv, owner="owner"), indent=1))


if __name__ == "__main__":
    main()
