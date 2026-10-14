"""growth-os CLI. Usage: python -m growth_os <command> ..."""

import argparse
import json

from growth_os import brands, db, vault
from growth_os.connectors import podcast, youtube


def main(argv=None):
    p = argparse.ArgumentParser(prog="growth-os")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create the RYJ Media brand (first tenant)")
    s.add_argument("--owner", default="owner")
    s = sub.add_parser("brand", help="create another brand")
    s.add_argument("name")
    s.add_argument("--owner", default="owner")
    sub.add_parser("status", help="brands, account states, freshness")
    s = sub.add_parser("serve", help="Manage Accounts UI on 127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
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
        return serve(a.port)

    conn = db.connect()
    if a.cmd == "init":
        try:
            t = brands.create_brand(conn, "RYJ Media", a.owner, tenant_id="ryj-media",
                                    contact="", theme_json=json.dumps({"accent": "#CFB53B", "base": "black"}))
            print(f"created brand {t}")
        except brands.BrandError as e:
            print(e)
    elif a.cmd == "brand":
        print(brands.create_brand(conn, a.name, a.owner))
    elif a.cmd == "status":
        print(f"YouTube OAuth client configured: {bool(vault.load_client('youtube'))}")
        for b in brands.list_brands(conn):
            print(f"\n{b['display_name']} ({b['tenant_id']})")
            rows = brands.accounts(conn, b["tenant_id"])
            seen = {r["platform"] for r in rows}
            for r in rows:
                print(f"  {r['platform']:<15} {r['state']:<22} {r['platform_account_id']}  {r['account_name']}"
                      f"  row={r['id']} as_of={r['data_as_of'] or '-'}")
            for pl in brands.PLATFORMS:
                if pl not in seen:
                    print(f"  {pl:<15} NOT_CONNECTED")
    elif a.cmd == "sync":
        rep = youtube.sync_sample(conn, a.brand, a.account_row, client=vault.load_client("youtube"))
        print(json.dumps(rep, indent=1))
    elif a.cmd == "import":
        print(json.dumps(podcast.import_csv(conn, a.brand, a.account_row, a.csv, owner="owner"), indent=1))


if __name__ == "__main__":
    main()
