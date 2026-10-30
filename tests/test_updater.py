import base64
import hashlib
import io
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

from ed25519_signer import public_key, sign
from subtitle_app import updater
from subtitle_app.updater import UpdateError, Updater, envelope, installer_name, make_payload, read_manifest
from subtitle_app.web_controller import WebController

SECRET = bytes(range(32))
KEY = public_key(SECRET)
INSTALLER = b"MZ" + b"installer bytes " * 4096
SHA = hashlib.sha256(INSTALLER).hexdigest()


def signed(version="0.3.0", size=len(INSTALLER), sha256=SHA, notes="修复了一些问题", secret=SECRET, **override):
    payload = json.loads(make_payload(version, size, sha256, notes))
    payload.update(override)
    text = json.dumps(payload, ensure_ascii=False)
    return envelope(text, sign(secret, text.encode("utf-8")))


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeNetwork:
    """Serves fixed bytes per URL and records what was asked for."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def __call__(self, url, timeout=None):
        self.requests.append(url)
        body = self.routes.get(url)
        if isinstance(body, Exception):
            raise body
        if body is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return Response(body)


def wait(up, *states):
    deadline = time.monotonic() + 5
    while up.snapshot()["state"] not in states:
        if time.monotonic() > deadline:
            raise AssertionError(f"state stayed {up.snapshot()}")
        time.sleep(0.01)
    return up.snapshot()


class ManifestTest(unittest.TestCase):
    def test_accepts_signed_manifest(self):
        release = read_manifest(signed(), KEY)
        self.assertEqual(release, {"version": "0.3.0", "file": "JianSubtitle-0.3.0-win-x64-setup.exe", "size": len(INSTALLER), "sha256": SHA, "notes": "修复了一些问题"})

    def test_rejects_tampered_or_foreign_signature(self):
        raw = json.loads(signed())
        raw["payload"] = raw["payload"].replace("0.3.0", "0.3.1")
        with self.assertRaisesRegex(UpdateError, "签名"):
            read_manifest(json.dumps(raw).encode(), KEY)
        with self.assertRaisesRegex(UpdateError, "签名"):
            read_manifest(signed(secret=bytes(32)), KEY)

    def test_rejects_unexpected_fields(self):
        for override in ({"app": "other"}, {"version": "1.0"}, {"version": "01.2.3"}, {"file": "..\\evil.exe"},
                         {"file": "JianSubtitle-9.9.9-win-x64-setup.exe"}, {"size": 0}, {"size": 2**40},
                         {"size": "12"}, {"sha256": "ABC"}, {"notes": "x" * 5000}):
            with self.subTest(override=override), self.assertRaises(UpdateError):
                read_manifest(signed(**override), KEY)

    def test_rejects_garbage(self):
        for raw in (b"", b"[]", b"{\"payload\": 1}", b"{\"payload\": \"{}\", \"signature\": \"!!\"}"):
            with self.subTest(raw=raw), self.assertRaises(UpdateError):
                read_manifest(raw, KEY)


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.launched = []
        self.download_url = f"{updater.RELEASES_URL}/download/v0.3.0/{installer_name('0.3.0')}"

    def tearDown(self):
        self.temp.cleanup()

    def make(self, routes, current="0.2.0", **options):
        options.setdefault("supported", True)
        return Updater(self.data, current=current, public_key=base64.b64encode(KEY).decode(), urlopen=FakeNetwork(routes), launch=self.launched.append, **options)

    def test_finds_newer_version(self):
        up = self.make({updater.MANIFEST_URL: signed()})
        up.check()
        snapshot = wait(up, "available")
        self.assertEqual((snapshot["version"], snapshot["notes"], snapshot["total"]), ("0.3.0", "修复了一些问题", len(INSTALLER)))

    def test_same_or_older_version_is_latest(self):
        for current in ("0.3.0", "0.10.0"):
            up = self.make({updater.MANIFEST_URL: signed()}, current=current)
            up.check()
            self.assertIsNone(wait(up, "latest")["version"])

    def test_missing_manifest_means_no_update(self):
        up = self.make({})
        up.check()
        wait(up, "latest")

    def test_failures_only_show_for_manual_checks(self):
        up = self.make({updater.MANIFEST_URL: urllib.error.URLError("offline")})
        up.check()
        self.assertIn("offline", wait(up, "failed")["error"])
        up = self.make({updater.MANIFEST_URL: signed(secret=bytes(32))})
        up.check(manual=False)
        time.sleep(0.05)
        self.assertEqual(wait(up, "idle")["error"], None)

    def test_downloads_verifies_and_installs(self):
        up = self.make({updater.MANIFEST_URL: signed(), self.download_url: INSTALLER})
        up.check()
        wait(up, "available")
        up.download()
        wait(up, "ready")
        target = self.data / "updates" / installer_name("0.3.0")
        self.assertEqual(target.read_bytes(), INSTALLER)
        up.install()
        self.assertEqual(self.launched, [target])
        self.assertEqual(up.snapshot()["state"], "installing")

    def test_bad_download_is_deleted(self):
        for body in (INSTALLER[:-1] + b"!", INSTALLER + b"extra", INSTALLER[:100]):
            up = self.make({updater.MANIFEST_URL: signed(), self.download_url: body})
            up.check()
            wait(up, "available")
            up.download()
            self.assertIn("校验", wait(up, "failed")["error"])
            self.assertEqual(list((self.data / "updates").iterdir()), [])

    def test_install_rechecks_the_file(self):
        up = self.make({updater.MANIFEST_URL: signed(), self.download_url: INSTALLER})
        up.check(); wait(up, "available")
        up.download(); wait(up, "ready")
        (self.data / "updates" / installer_name("0.3.0")).write_bytes(b"MZ swapped")
        with self.assertRaisesRegex(UpdateError, "校验"):
            up.install()
        self.assertEqual(self.launched, [])
        self.assertEqual(up.snapshot()["state"], "failed")

    def test_reuses_verified_download_and_cleans_leftovers(self):
        folder = self.data / "updates"
        folder.mkdir()
        (folder / installer_name("0.3.0")).write_bytes(INSTALLER)
        (folder / installer_name("0.2.0")).write_bytes(b"old")
        (folder / (installer_name("0.3.0") + ".part")).write_bytes(b"partial")
        network = {updater.MANIFEST_URL: signed()}
        up = self.make(network)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), [installer_name("0.3.0")])
        up.check(); wait(up, "available")
        up.download(); wait(up, "ready")
        self.assertNotIn(self.download_url, up.urlopen.requests)

    def test_unsupported_build_does_nothing(self):
        up = self.make({updater.MANIFEST_URL: signed()}, supported=False)
        up.start()
        self.assertEqual(up.snapshot()["state"], "idle")
        self.assertFalse(up.snapshot()["supported"])
        self.assertEqual(up.urlopen.requests, [])
        with self.assertRaises(UpdateError):
            up.check()

    def test_auto_check_setting_persists(self):
        up = self.make({updater.MANIFEST_URL: signed()})
        self.assertTrue(up.snapshot()["auto"])
        up.set_auto(False)
        again = self.make({updater.MANIFEST_URL: signed()})
        self.assertFalse(again.snapshot()["auto"])
        again.start()
        self.assertEqual(again.urlopen.requests, [])

    def test_unsigned_builds_are_unsupported(self):
        up = Updater(self.data, current="0.2.0", public_key="", urlopen=FakeNetwork({}), launch=self.launched.append)
        self.assertFalse(up.snapshot()["supported"])


class SecureOpenTest(unittest.TestCase):
    def test_refuses_plain_http(self):
        with self.assertRaises(UpdateError):
            updater.secure_urlopen("http://github.com/")

    def test_redirect_must_stay_on_https(self):
        handler = updater._HttpsOnly()
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(None, None, 302, "Found", {}, "http://example.com/x")


class ControllerUpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.closed = []
        data = Path(self.temp.name)
        self.up = Updater(data, current="0.2.0", public_key=base64.b64encode(KEY).decode(), supported=True,
                          urlopen=FakeNetwork({updater.MANIFEST_URL: signed(), f"{updater.RELEASES_URL}/download/v0.3.0/{installer_name('0.3.0')}": INSTALLER}),
                          launch=lambda path: None)
        self.controller = WebController(data, native=lambda action, payload: self.closed.append(action), updater=self.up)

    def tearDown(self):
        self.temp.cleanup()

    def send(self, action, payload=None):
        state = self.controller.snapshot()
        project = state.get("project")
        return self.controller.dispatch({"action": action, "payload": payload or {}, "requestId": f"{action}-{time.monotonic_ns()}",
                                         "projectId": project and project["id"], "expectedRevision": project and project["revision"]})

    def test_update_actions_ignore_project_revision(self):
        self.assertTrue(self.send("new_project", {"name": "测试"})["ok"])
        reply = self.controller.dispatch({"action": "update_check", "payload": {}, "requestId": "stale", "projectId": "other", "expectedRevision": -1})
        self.assertTrue(reply["ok"], reply)
        wait(self.up, "available")
        self.assertEqual(self.controller.snapshot()["update"]["version"], "0.3.0")

    def test_install_closes_the_app_only_when_ready(self):
        reply = self.send("update_install")
        self.assertFalse(reply["ok"])
        self.assertEqual(self.closed, [])
        self.send("update_check"); wait(self.up, "available")
        self.send("update_download"); wait(self.up, "ready")
        self.assertTrue(self.send("update_install")["ok"])
        self.assertEqual(self.closed, ["close_app"])

    def test_auto_toggle(self):
        self.assertTrue(self.send("update_auto", {"enabled": False})["ok"])
        self.assertFalse(self.controller.snapshot()["update"]["auto"])
