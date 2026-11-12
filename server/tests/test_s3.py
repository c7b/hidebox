# SPDX-License-Identifier: MIT
"""The S3-compatible store client (server/mutis/s3.py, docs/storage.md): Signature Version 4 against AWS's published
vectors, then every call against the local stand-in (fake_s3.py), which checks signatures and payload hashes."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mutis import s3  # noqa: E402
from mutis.fake_s3 import FakeS3  # noqa: E402

ITEM = "AbCdEfGhIjKlMnOpQrStUv"


class SignatureVectors(unittest.TestCase):
    """The AWS Signature Version 4 test suite (get-vanilla, get-vanilla-query-order-key-case, as shipped with
    botocore's tests/unit/auth/aws4_testsuite) and the S3 API reference's "GET Object" example."""

    def test_get_vanilla(self):
        auth = s3.authorization("GET", "/", {}, {"Host": "example.amazonaws.com", "X-Amz-Date": "20150830T123600Z"},
                                s3.EMPTY_SHA256, "20150830T123600Z", "us-east-1", "AKIDEXAMPLE",
                                "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "service")
        self.assertEqual(auth, "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
                               "SignedHeaders=host;x-amz-date, "
                               "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31")

    def test_query_order(self):
        auth = s3.authorization("GET", "/", {"Param2": "value2", "Param1": "value1"},
                                {"Host": "example.amazonaws.com", "X-Amz-Date": "20150830T123600Z"}, s3.EMPTY_SHA256,
                                "20150830T123600Z", "us-east-1", "AKIDEXAMPLE",
                                "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "service")
        self.assertTrue(auth.endswith("Signature=b97d918cfa904a5beff61c982a1b6f458b799221646efd99d3219ec94cdf2500"))

    def test_s3_get_object_with_range(self):
        auth = s3.authorization("GET", "/test.txt", {}, {
            "Host": "examplebucket.s3.amazonaws.com", "Range": "bytes=0-9", "x-amz-content-sha256": s3.EMPTY_SHA256,
            "x-amz-date": "20130524T000000Z"}, s3.EMPTY_SHA256, "20130524T000000Z", "us-east-1", "AKIAIOSFODNN7EXAMPLE",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
        self.assertEqual(auth, "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
                               "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
                               "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")

    def test_uri_encoding(self):
        self.assertEqual(s3.uri_encode("a b/c~d*", keep_slash=True), "a%20b/c~d%2A")
        self.assertEqual(s3.uri_encode("a/b", keep_slash=False), "a%2Fb")


class SettingsCheck(unittest.TestCase):
    def ok(self, **kw):
        base = dict(endpoint="https://s3.eu-central-003.backblazeb2.com", region="eu-central-003", bucket="hidebox-blobs",
                    prefix="blobs/", access_key="0031234567890ab0000000001", secret_key="K003" + "x" * 27)
        base.update(kw)
        return s3.Settings(**base)

    def test_accepts_a_provider_endpoint(self):
        self.ok().check()
        self.ok(endpoint="https://abc123.r2.cloudflarestorage.com", region="auto", addressing="virtual").check()

    def test_refuses_what_could_leak_or_misroute(self):
        for kw in (dict(endpoint="http://s3.example.com"), dict(endpoint="https://user:pw@s3.example.com"),
                   dict(endpoint="https://s3.example.com/path"), dict(endpoint="https://s3.example.com?x=1"),
                   dict(bucket="Bad_Bucket"), dict(prefix="../x"), dict(prefix="a b"), dict(addressing="dns"),
                   dict(region="EU WEST"), dict(secret_key="short"), dict(access_key="key with spaces")):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.ok(**kw).check()

    def test_plain_http_only_to_this_machine(self):
        self.ok(endpoint="http://127.0.0.1:9000").check()
        with self.assertRaises(ValueError):
            self.ok(endpoint="http://localhost:9000").check()

    def test_key_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("# hidebox store\nKEYID12345\nsecret-secret-secret-1\n")
        try:
            self.assertEqual(s3.load_keys(f.name), ("KEYID12345", "secret-secret-secret-1"))
        finally:
            os.unlink(f.name)


class StoreAgainstStandIn(unittest.TestCase):
    def setUp(self):
        self.fake = FakeS3(min_part=1024)
        self.store = s3.Store(self.fake.settings())
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.fake.close()
        self.tmp.cleanup()

    def file(self, data: bytes) -> int:
        path = Path(self.tmp.name) / "blob"
        path.write_bytes(data)
        fd = os.open(path, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        return fd

    def test_put_get_head_delete(self):
        data = os.urandom(300_000)
        self.store.put(ITEM, self.file(data), len(data))
        self.assertEqual(self.fake.objects["blobs/" + ITEM], data)
        self.assertEqual(self.store.head(ITEM), len(data))
        self.assertEqual(b"".join(self.store.get_range(ITEM, 1000, 70_000)), data[1000:71_000])
        self.assertEqual(self.store.read_all(ITEM, len(data)), data)
        self.store.delete(ITEM)
        self.assertIsNone(self.store.head(ITEM))
        self.store.delete(ITEM)                       # already gone: still fine

    def test_virtual_host_addressing(self):
        store = s3.Store(self.fake.settings(addressing="virtual"))
        self.assertEqual((store.host, store._path(ITEM)), (f"{self.fake.bucket}.127.0.0.1", "/blobs/" + ITEM))
        self.assertEqual((self.store.host, self.store._path(ITEM)), ("127.0.0.1", f"/{self.fake.bucket}/blobs/{ITEM}"))

    def test_multipart_above_the_part_size(self):
        data = os.urandom(10_000)
        with mock.patch.object(s3, "PART_BYTES", 4096), mock.patch.object(s3, "READ_SLICE", 1000):
            self.store.put(ITEM, self.file(data), len(data))
        self.assertEqual(self.fake.objects["blobs/" + ITEM], data)
        self.assertEqual(self.fake.requests["POST"], 2)            # initiate, complete
        self.assertEqual(self.fake.requests["PUT"], 3)             # three parts
        self.assertEqual(self.fake.uploads, {})

    def test_a_failed_multipart_is_aborted(self):
        data = os.urandom(10_000)
        with mock.patch.object(s3, "PART_BYTES", 4096):
            original = self.store._simple
            calls = []

            def flaky(method, item_id, ok, **kw):
                calls.append((method, kw.get("query", {})))
                if method == "PUT" and kw.get("query", {}).get("partNumber") == "2":
                    raise s3.S3Error(500, "InternalError")
                return original(method, item_id, ok, **kw)

            with mock.patch.object(self.store, "_simple", flaky), self.assertRaises(s3.S3Error):
                self.store.put(ITEM, self.file(data), len(data))
        self.assertEqual(calls[-1][0], "DELETE")
        self.assertIn("uploadId", calls[-1][1])
        self.assertEqual(self.fake.uploads, {})
        self.assertNotIn("blobs/" + ITEM, self.fake.objects)

    def test_a_wrong_secret_is_refused(self):
        bad = s3.Store(s3.Settings(self.fake.url, self.fake.region, self.fake.bucket, "blobs/", self.fake.access_key,
                                   "not-the-secret-at-all", "path"))
        with self.assertRaises(s3.S3Error) as e:
            bad.head(ITEM)
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(s3.S3Error) as e:
            bad.put(ITEM, self.file(b"x" * 100), 100)
        self.assertEqual((e.exception.status, e.exception.code), (403, "SignatureDoesNotMatch"))

    def test_a_body_that_changed_after_hashing_is_refused(self):
        data = bytearray(os.urandom(2000))
        path = Path(self.tmp.name) / "changing"
        path.write_bytes(data)
        fd = os.open(path, os.O_RDWR)
        self.addCleanup(os.close, fd)
        real = self.store._sha256

        def hash_then_change(fd_, offset, length):
            digest = real(fd_, offset, length)
            os.pwrite(fd_, b"tampered", 0)
            return digest

        with mock.patch.object(self.store, "_sha256", hash_then_change), self.assertRaises(s3.S3Error) as e:
            self.store.put(ITEM, fd, len(data))
        self.assertEqual(e.exception.code, "XAmzContentSHA256Mismatch")

    def test_errors_carry_the_status_and_code_only(self):
        self.fake.fail_next(1, 503)
        with self.assertRaises(s3.S3Error) as e:
            self.store.delete(ITEM)
        self.assertEqual((e.exception.status, e.exception.code), (503, "SlowDown"))
        with self.assertRaises(s3.S3Error) as e:
            list(self.store.get_range(ITEM, 0, 10))
        self.assertEqual((e.exception.status, e.exception.code), (404, "NoSuchKey"))
        self.assertNotIn(self.fake.secret_key, str(e.exception))

    def test_a_store_that_is_down(self):
        self.fake.close()
        with self.assertRaises(s3.S3Error) as e:
            self.store.head(ITEM)
        self.assertEqual((e.exception.status, e.exception.code), (0, "network"))

    def test_a_short_body_is_an_error(self):
        data = os.urandom(5000)
        self.store.put(ITEM, self.file(data), len(data))
        with self.assertRaises(s3.S3Error):
            list(self.store.get_range(ITEM, 4000, 2000))      # 1000 bytes exist past 4000


if __name__ == "__main__":
    unittest.main()
