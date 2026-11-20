"""Object storage (RD-5): request signing, integrity, tenant-scoped keys and the code archive."""

import hashlib
import io
import re
import uuid
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.organizations.models import Organization
from app.storage import service as storage
from app.storage.models import StoredObject
from app.storage.s3 import S3Client, StorageError, sign
from tests.test_portal import box, env  # noqa: F401  (fixtures)
from tests.test_sandbox_flow import CODE, _reach_code

ACCESS, SECRET = "test-access-key", "test-secret-key-0123456789"


def test_signing_matches_the_published_aws_example():
    """AWS Signature Version 4 documentation, 'Example: GET Object' (Amazon S3 API reference)."""
    header = sign(method="GET", host="examplebucket.s3.amazonaws.com", path="/test.txt", query={},
                  headers={"range": "bytes=0-9", "x-amz-content-sha256": hashlib.sha256(b"").hexdigest(),
                           "x-amz-date": "20130524T000000Z"},
                  payload_hash=hashlib.sha256(b"").hexdigest(), access_key="AKIAIOSFODNN7EXAMPLE",
                  secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", region="us-east-1",
                  amz_date="20130524T000000Z")
    assert header == ("AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
                      "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
                      "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")


class FakeS3:
    """An in-memory S3 that checks every request is signed with the right key and carries its payload hash."""

    def __init__(self):
        self.buckets: dict[str, dict[str, bytes]] = {}
        self.seen: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        if not re.match(rf"^AWS4-HMAC-SHA256 Credential={ACCESS}/\d{{8}}/us-east-1/s3/aws4_request, ", auth):
            return httpx.Response(403)
        if request.headers["x-amz-content-sha256"] != hashlib.sha256(request.content).hexdigest():
            return httpx.Response(400)
        self.seen.append(f"{request.method} {request.url.path}")
        parts = request.url.path.lstrip("/").split("/", 1)
        bucket, key = parts[0], (parts[1] if len(parts) > 1 else "")
        objects = self.buckets.get(bucket)
        if not key:
            if request.method == "PUT":
                self.buckets.setdefault(bucket, {})
                return httpx.Response(200)
            return httpx.Response(200 if objects is not None else 404)
        if objects is None:
            return httpx.Response(404)
        if request.method == "PUT":
            objects[key] = request.content
            return httpx.Response(200)
        if key not in objects:
            return httpx.Response(404)
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(objects[key]))})
        if request.method == "DELETE":
            del objects[key]
            return httpx.Response(204)
        return httpx.Response(200, content=objects[key])

    def transport(self):
        return httpx.MockTransport(self.handler)


@pytest.fixture
def s3():
    return FakeS3()


@pytest.fixture
def stored(settings):
    return settings.model_copy(update={"storage_endpoint": "http://minio:9000", "storage_access_key": ACCESS,
                                       "storage_secret_key": SECRET, "storage_bucket": "aidlc-test"})


def test_the_client_creates_the_bucket_once_and_round_trips_objects(s3):
    client = S3Client("http://minio:9000", ACCESS, SECRET, transport=s3.transport())
    assert client.ensure_bucket("b") is True
    assert client.ensure_bucket("b") is False
    client.put("b", "orgs/1/a b.txt", b"hello", "text/plain")  # spaces are encoded and still signed correctly
    assert client.get("b", "orgs/1/a b.txt") == b"hello"
    assert client.head("b", "orgs/1/a b.txt")["size"] == 5
    client.delete("b", "orgs/1/a b.txt")
    assert client.head("b", "orgs/1/a b.txt") is None
    with pytest.raises(StorageError):
        client.get("b", "missing")
    wrong = S3Client("http://minio:9000", "someone-else", SECRET, transport=s3.transport())
    with pytest.raises(StorageError) as refused:
        wrong.put("b", "x", b"x", "text/plain")
    assert refused.value.status == 403


def test_keys_are_scoped_and_unsafe_names_are_refused():
    org, project = uuid.uuid4(), uuid.uuid4()
    assert storage.object_key(org, project, "code-archive", "v1.zip") == f"orgs/{org}/projects/{project}/code-archive/v1.zip"
    assert storage.object_key(org, None, "uploads", "a.txt") == f"orgs/{org}/shared/uploads/a.txt"
    for name in ("../x", "a/b", "", ".hidden"):
        with pytest.raises(ValueError):
            storage.object_key(org, project, "uploads", name)
    with pytest.raises(ValueError):
        storage.object_key(org, project, "../etc", "a.txt")


def test_reads_are_refused_when_the_stored_bytes_changed(app, stored, s3):
    storage.ensure_bucket(stored, s3.transport())
    with app.state.session_factory() as db:
        org = Organization(id=uuid.uuid4(), name="Storage org", slug=f"s-{uuid.uuid4().hex[:8]}")
        db.add(org)
        db.flush()
        row = storage.save(db, stored, organization_id=org.id, project_id=None, purpose="evidence", name="log.txt",
                           data=b"build passed", content_type="text/plain", transport=s3.transport())
        again = storage.save(db, stored, organization_id=org.id, project_id=None, purpose="evidence", name="log.txt",
                             data=b"different", content_type="text/plain", transport=s3.transport())
        assert again.id == row.id  # written once; a key is never silently replaced
        db.commit()
        assert storage.load(stored, row, s3.transport()) == b"build passed"
        s3.buckets["aidlc-test"][row.key] = b"build FAILED"  # tampered with in the bucket
        with pytest.raises(storage.IntegrityError):
            storage.load(stored, row, s3.transport())


def test_readiness_reports_storage(app, stored, s3):
    fresh = create_app(stored, app.state.engine)
    fresh.state.storage_transport = s3.transport()
    with TestClient(fresh) as c:
        missing = c.get("/readyz")
        assert missing.status_code == 503 and missing.json()["checks"] == {"database": "ok", "storage": "unavailable"}
        storage.ensure_bucket(stored, s3.transport())
        ok = c.get("/readyz")
        assert ok.status_code == 200 and ok.json()["checks"]["storage"] == "ok"
        assert re.fullmatch(r"[0-9a-f]{32}", ok.headers["x-request-id"])
        kept = c.get("/healthz", headers={"X-Request-ID": "trace-from-proxy-01"})
        assert kept.headers["x-request-id"] == "trace-from-proxy-01"
        replaced = c.get("/healthz", headers={"X-Request-ID": "<script>alert(1)</script> and spaces"})
        assert re.fullmatch(r"[0-9a-f]{32}", replaced.headers["x-request-id"])  # unsafe IDs are never echoed


def test_code_archives_are_kept_in_storage_and_served_from_it(env, stored, s3):  # noqa: F811
    env.client.app.state.settings = stored.model_copy(update={"jobs_inline": True})
    env.client.app.state.storage_transport = s3.transport()
    storage.ensure_bucket(stored, s3.transport())
    person, _ = _reach_code(env)
    version = env.item(CODE, person)["current_version_id"]
    first = person.get(f"{env.base}/versions/{version}/code.zip")
    assert first.status_code == 200
    with env.client.app.state.session_factory() as db:
        (row,) = db.execute(select(StoredObject)).scalars().all()
    assert row.purpose == "code-archive" and str(row.project_id) == env.project
    assert row.key == f"orgs/{env.org}/projects/{env.project}/code-archive/code-{version}.zip"
    assert row.sha256 == hashlib.sha256(first.content).hexdigest()
    puts = [s for s in s3.seen if s.startswith("PUT /aidlc-test/orgs")]
    second = person.get(f"{env.base}/versions/{version}/code.zip")
    assert second.content == first.content  # the same bytes, read back from storage
    assert [s for s in s3.seen if s.startswith("PUT /aidlc-test/orgs")] == puts  # not written twice
    with zipfile.ZipFile(io.BytesIO(second.content)) as archive:
        assert sorted(archive.namelist()) == ["calc.py", "test_calc.py"]
