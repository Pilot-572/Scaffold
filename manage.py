#!/usr/bin/env python3
# ── License key CLI ──
#   python manage.py gen [count]     generate key(s)
#   python manage.py revoke KEY      revoke a key
#   python manage.py list            show all keys
import argparse
import secrets

from shared.db import License, SessionLocal, init_db


def make_key() -> str:
    raw = secrets.token_hex(6).upper()
    return f"SF-{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def main():
    ap = argparse.ArgumentParser(description="ServerForge license keys")
    sub = ap.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("gen")
    gen.add_argument("count", nargs="?", type=int, default=1)
    rev = sub.add_parser("revoke")
    rev.add_argument("key")
    sub.add_parser("list")
    args = ap.parse_args()

    init_db()
    with SessionLocal() as db:
        if args.cmd == "gen":
            for _ in range(args.count):
                key = make_key()
                db.add(License(key=key))
                print(key)
            db.commit()
        elif args.cmd == "revoke":
            lic = db.get(License, args.key.strip().upper())
            if not lic:
                raise SystemExit("No such key.")
            lic.revoked = True
            db.commit()
            print(f"Revoked {lic.key}" + (f" (was user {lic.user_id})" if lic.user_id else ""))
        else:
            for lic in db.query(License).order_by(License.created_at).all():
                state = "REVOKED" if lic.revoked else ("redeemed by " + lic.user_id if lic.user_id else "unredeemed")
                print(f"{lic.key}  {state}  created {lic.created_at:%Y-%m-%d}")


if __name__ == "__main__":
    main()
