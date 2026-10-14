"""Spec 15.6 account-management acceptance tests, against a fake Google.

These prove the logic; the live proof (real RYJ channel) needs the owner's
OAuth consent and is recorded in docs/PROJECT_STATE.md when done.
"""

import base64
import json
import os
import tempfile
import unittest
import urllib.parse
from datetime import date

from cryptography.fernet import Fernet

os.environ.setdefault("GROWTH_OS_SECRET_KEY", Fernet.generate_key().decode())

from growth_os import brands, db  # noqa: E402
from growth_os.brands import BrandError  # noqa: E402
from growth_os.connectors import podcast, youtube  # noqa: E402

CLIENT = {"client_id": "cid", "client_secret": "csecret"}
RYJ_CH = "UCryjRYJryjRYJryjRYJryjR"
OTHER_CH = "UCotherOTHERotherOTHERoth"


def id_token(email):
    body = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


class FakeGoogle:
    def __init__(self, channels):
        self.channels = channels
        self.calls = []
        self.refresh_fails = False
        self.revoked = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url.split("?")[0]))
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        form = dict(urllib.parse.parse_qsl(body.decode())) if body else {}
        if url.startswith(youtube.TOKEN_URL):
            if form.get("grant_type") == "refresh_token" and self.refresh_fails:
                return 400, json.dumps({"error": "invalid_grant"}).encode()
            return 200, json.dumps({
                "access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                "scope": youtube.READ_SCOPES, "id_token": id_token("owner@ryj.example"),
            }).encode()
        if url.startswith(youtube.REVOKE_URL):
            self.revoked.append(form.get("token"))
            return 200, b""
        if "/channels" in url:
            return 200, json.dumps({"items": [{
                "id": c, "snippet": {"title": t, "customUrl": "@" + t.lower().replace(" ", "")},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU" + c[2:]}},
                "statistics": {"subscriberCount": "1200", "viewCount": "50000", "videoCount": "40"},
            } for c, t in self.channels]}).encode()
        if "/playlistItems" in url:
            return 200, json.dumps({"items": [{"contentDetails": {"videoId": v}} for v in ("vLong", "vShort")]}).encode()
        if "/videos" in url:
            return 200, json.dumps({"items": [
                {"id": "vLong", "etag": "e1", "snippet": {"title": "Ep 12", "publishedAt": "2026-10-01T00:00:00Z"},
                 "contentDetails": {"duration": "PT48M10S"}, "statistics": {"viewCount": "900"}},
                {"id": "vShort", "etag": "e2", "snippet": {"title": "Clip", "publishedAt": "2026-10-02T00:00:00Z"},
                 "contentDetails": {"duration": "PT45S"}, "statistics": {"viewCount": "4000"}},
            ]}).encode()
        if url.startswith(youtube.ANALYTICS_API):
            if q.get("dimensions") == "day":
                return 200, json.dumps({
                    "columnHeaders": [{"name": n} for n in ("day", "views", "estimatedMinutesWatched",
                                                             "averageViewDuration", "subscribersGained",
                                                             "subscribersLost")],
                    "rows": [["2026-10-10", 100, 300, 180, 3, 1], ["2026-10-11", 120, 330, 165, 2, 0]],
                }).encode()
            assert q["filters"] == "video==vLong"
            return 200, json.dumps({
                "columnHeaders": [{"name": n} for n in ("elapsedVideoTimeRatio", "audienceWatchRatio",
                                                         "relativeRetentionPerformance")],
                "rows": [[0.01, 1.0, 0.5], [0.02, 0.8, 0.45]],
            }).encode()
        return 404, b"{}"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(os.path.join(self.tmp.name, "t.db"))
        self.ryj = brands.create_brand(self.conn, "RYJ Media", "owner", tenant_id="ryj-media")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def connect_youtube(self, tenant, google):
        url = youtube.begin_auth(self.conn, tenant, "http://127.0.0.1:8765/oauth/callback", CLIENT)
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
        return youtube.finish_auth(self.conn, state=state, code="c", client=CLIENT, transport=google)[1]

    def activate(self, tenant, google, channel=RYJ_CH):
        rows = self.connect_youtube(tenant, google)
        row = next(r for r in rows if brands.get_account(self.conn, tenant, r)["platform_account_id"] == channel)
        brands.verify_identity(self.conn, tenant, row, confirmed_platform_account_id=channel, owner="owner")
        brands.assign(self.conn, tenant, row, owner="owner")
        return row


class TestYouTubeConnect(Base):
    def test_real_channel_flow_first_sync_and_attribution(self):
        g = FakeGoogle([(OTHER_CH, "Klip Studio"), (RYJ_CH, "Respect Your Journey")])
        rows = self.connect_youtube(self.ryj, g)
        # Both channels discovered, neither assumed to be RYJ.
        states = {brands.get_account(self.conn, self.ryj, r)["state"] for r in rows}
        self.assertEqual(states, {brands.AUTHORIZED_UNASSIGNED})
        acct = brands.get_account(self.conn, self.ryj, rows[1])
        self.assertEqual(acct["connected_identity"], "owner@ryj.example")
        with self.assertRaises(BrandError) as e:  # cannot sync before verify+assign
            brands.assign(self.conn, self.ryj, rows[1], owner="owner")
        self.assertEqual(e.exception.code, "not_verified")
        brands.verify_identity(self.conn, self.ryj, rows[1], confirmed_platform_account_id=RYJ_CH, owner="owner")
        brands.assign(self.conn, self.ryj, rows[1], owner="owner")
        rep = youtube.sync_sample(self.conn, self.ryj, rows[1], client=CLIENT, transport=g, today=date(2026, 10, 14))
        self.assertEqual(rep["channel_title"], "Respect Your Journey")
        self.assertEqual(rep["available_through"], "2026-10-11")
        self.assertEqual(rep["retention"], {"video_id": "vLong", "buckets": 2})
        self.assertEqual({v["id"]: v["format"] for v in rep["videos"]},
                         {"vLong": "long_form", "vShort": "short_heuristic"})
        acct = brands.get_account(self.conn, self.ryj, rows[1])
        self.assertEqual(acct["state"], brands.ACTIVE)
        owners = {r[0] for r in self.conn.execute("SELECT DISTINCT tenant_id FROM metrics")}
        self.assertEqual(owners, {"ryj-media"})
        accts = {r[0] for r in self.conn.execute("SELECT DISTINCT platform_account_id FROM metrics")}
        self.assertEqual(accts, {RYJ_CH})

    def test_wrong_channel_rejected_without_import(self):
        g = FakeGoogle([(OTHER_CH, "Klip Studio")])
        [row] = self.connect_youtube(self.ryj, g)
        with self.assertRaises(BrandError) as e:
            brands.verify_identity(self.conn, self.ryj, row, confirmed_platform_account_id=RYJ_CH, owner="owner")
        self.assertEqual(e.exception.code, "id_mismatch")
        brands.reject(self.conn, self.ryj, row, owner="owner")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0], 0)
        with self.assertRaises(youtube.ConnectorError):
            youtube.sync_sample(self.conn, self.ryj, row, client=CLIENT, transport=g)

    def test_disconnect_reconnect_and_revoke_stop_jobs(self):
        g = FakeGoogle([(RYJ_CH, "Respect Your Journey")])
        row = self.activate(self.ryj, g)
        self.conn.execute(
            "INSERT INTO jobs VALUES ('j1','ryj-media','operator','update_title','youtube',?, '{}','awaiting_approval','k1',NULL,NULL,NULL,'t','t')",
            (RYJ_CH,))
        brands.disconnect(self.conn, self.ryj, row, owner="owner")
        self.assertEqual(brands.get_account(self.conn, self.ryj, row)["state"], brands.DISCONNECTED)
        self.assertEqual(self.conn.execute("SELECT state FROM jobs").fetchone()[0], "blocked")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0], 0)
        # Reconnect: back to unassigned, owner must re-verify.
        self.connect_youtube(self.ryj, g)
        self.assertEqual(brands.get_account(self.conn, self.ryj, row)["state"], brands.AUTHORIZED_UNASSIGNED)
        brands.verify_identity(self.conn, self.ryj, row, confirmed_platform_account_id=RYJ_CH, owner="owner")
        brands.assign(self.conn, self.ryj, row, owner="owner")
        youtube.revoke(self.conn, self.ryj, row, owner="owner", transport=g)
        self.assertEqual(g.revoked, ["rt"])
        self.assertEqual(brands.get_account(self.conn, self.ryj, row)["state"], brands.REVOKED)

    def test_expired_refresh_token_needs_reauth(self):
        g = FakeGoogle([(RYJ_CH, "Respect Your Journey")])
        row = self.activate(self.ryj, g)
        self.conn.execute("UPDATE credentials SET ciphertext=?",
                          (youtube.vault.seal({"access_token": "old", "refresh_token": "rt", "expires_at": 0}),))
        g.refresh_fails = True
        with self.assertRaises(youtube.ConnectorError) as e:
            youtube.sync_sample(self.conn, self.ryj, row, client=CLIENT, transport=g)
        self.assertEqual(e.exception.code, "needs_reauth")
        self.assertEqual(brands.get_account(self.conn, self.ryj, row)["state"], brands.NEEDS_REAUTH)

    def test_identity_drift_pauses(self):
        g = FakeGoogle([(RYJ_CH, "Respect Your Journey")])
        row = self.activate(self.ryj, g)
        g.channels = [(OTHER_CH, "Someone else")]
        with self.assertRaises(youtube.ConnectorError) as e:
            youtube.sync_sample(self.conn, self.ryj, row, client=CLIENT, transport=g)
        self.assertEqual(e.exception.code, "identity_mismatch")
        self.assertEqual(brands.get_account(self.conn, self.ryj, row)["state"], brands.NEEDS_REAUTH)

    def test_tokens_encrypted_at_rest(self):
        self.activate(self.ryj, FakeGoogle([(RYJ_CH, "RYJ")]))
        blob = self.conn.execute("SELECT ciphertext FROM credentials").fetchone()[0]
        self.assertNotIn(b'"refresh_token"', blob)
        self.assertEqual(youtube.vault.unseal(blob)["refresh_token"], "rt")


class TestIsolation(Base):
    def setUp(self):
        super().setUp()
        self.klip = brands.create_brand(self.conn, "Klip Test", "owner", tenant_id="klip-test")

    def test_second_brand_cannot_read_ryj_records(self):
        g = FakeGoogle([(RYJ_CH, "RYJ")])
        row = self.activate(self.ryj, g)
        with self.assertRaises(BrandError):
            brands.get_account(self.conn, self.klip, row)
        self.assertEqual(brands.accounts(self.conn, self.klip), [])

    def test_duplicate_connection_blocks_silent_reassignment(self):
        g = FakeGoogle([(RYJ_CH, "RYJ")])
        self.activate(self.ryj, g)
        [row] = self.connect_youtube(self.klip, g)
        brands.verify_identity(self.conn, self.klip, row, confirmed_platform_account_id=RYJ_CH, owner="owner")
        with self.assertRaises(BrandError) as e:
            brands.assign(self.conn, self.klip, row, owner="owner")
        self.assertEqual(e.exception.code, "assigned_elsewhere")
        blocked = self.conn.execute("SELECT COUNT(*) FROM audit_log WHERE event='account.assign_blocked'").fetchone()[0]
        self.assertEqual(blocked, 1)
        # Each brand's token is its own; the Klip credential is not RYJ's.
        creds = self.conn.execute("SELECT tenant_id FROM credentials ORDER BY tenant_id").fetchall()
        self.assertEqual([c[0] for c in creds], ["klip-test", "ryj-media"])

    def test_operator_refuses_mismatched_destination(self):
        g = FakeGoogle([(RYJ_CH, "RYJ")])
        row = self.activate(self.ryj, g)
        self.conn.execute("UPDATE platform_accounts SET access_level='WRITE_METADATA' WHERE id=?", (row,))
        ok = {"approved_by": "owner", "approval_timestamp": "t", "tenant_id": self.ryj, "platform_account_id": RYJ_CH}
        brands.preflight_public_action(self.conn, tenant_id=self.ryj, platform="youtube", platform_account_id=RYJ_CH,
                                       required_permission="WRITE_METADATA", approval=ok)
        for bad, code in (
            ({**ok, "platform_account_id": OTHER_CH}, "destination_mismatch"),
            ({**ok, "tenant_id": self.klip}, "destination_mismatch"),
            (None, "no_approval"),
        ):
            with self.assertRaises(BrandError) as e:
                brands.preflight_public_action(self.conn, tenant_id=self.ryj, platform="youtube",
                                               platform_account_id=RYJ_CH, required_permission="WRITE_METADATA",
                                               approval=bad)
            self.assertEqual(e.exception.code, code)
        with self.assertRaises(BrandError) as e:
            brands.preflight_public_action(self.conn, tenant_id=self.klip, platform="youtube",
                                           platform_account_id=RYJ_CH, required_permission="WRITE_METADATA", approval=ok)
        self.assertEqual(e.exception.code, "destination_not_bound")
        with self.assertRaises(BrandError) as e:
            brands.preflight_public_action(self.conn, tenant_id=self.ryj, platform="youtube",
                                           platform_account_id=RYJ_CH, required_permission="PUBLISH", approval=ok)
        self.assertEqual(e.exception.code, "insufficient_scope")


class TestPodcastImport(Base):
    def test_public_match_is_not_ownership_and_import_maps_to_verified_show(self):
        row = podcast.discover_spotify(self.conn, self.ryj, "https://open.spotify.com/show/4rOoJ6Egrf8K2IrywzwOMk")
        self.assertEqual(brands.get_account(self.conn, self.ryj, row)["state"], brands.AUTHORIZED_UNASSIGNED)
        csv_path = os.path.join(self.tmp.name, "spotify.csv")
        with open(csv_path, "w") as f:
            f.write("Date,Plays,Listeners\n2026-10-10,\"1,200\",800\n2026-10-11,1300,850\n")
        with self.assertRaises(BrandError):
            podcast.import_csv(self.conn, self.ryj, row, csv_path, owner="owner")
        brands.verify_identity(self.conn, self.ryj, row, confirmed_platform_account_id="4rOoJ6Egrf8K2IrywzwOMk",
                               owner="owner")
        brands.assign(self.conn, self.ryj, row, owner="owner")
        podcast.enable_import(self.conn, self.ryj, row, owner="owner")
        res = podcast.import_csv(self.conn, self.ryj, row, csv_path, owner="owner")
        self.assertEqual(res["values"], 4)
        self.assertEqual(res["available_through"], "2026-10-11")
        names = {r[0] for r in self.conn.execute("SELECT DISTINCT metric_name FROM metrics WHERE platform='spotify'")}
        self.assertEqual(names, {"plays", "listeners"})
        self.assertIn("skipped", podcast.import_csv(self.conn, self.ryj, row, csv_path, owner="owner"))


if __name__ == "__main__":
    unittest.main()
