"""A small S3 client (path-style, AWS Signature Version 4) for MinIO and S3-compatible stores.

Written against the published SigV4 specification so no new dependency is needed. Only what the platform uses:
create a bucket, and put, get, head and delete an object. Credentials come from settings;
they are never logged and never sent anywhere but the configured endpoint.
"""

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class StorageError(Exception):
    def __init__(self, status: int, operation: str, detail: str = "") -> None:
        super().__init__(f"object storage {operation} failed with HTTP {status}")
        self.status = status
        self.operation = operation
        self.detail = detail[:300]


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def signing_key(secret: str, date: str, region: str, service: str = "s3") -> bytes:
    k = _hmac(("AWS4" + secret).encode(), date)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def _uri_encode(value: str, keep_slash: bool) -> str:
    return quote(value, safe="/-_.~" if keep_slash else "-_.~")


def canonical_query(params: dict[str, str]) -> str:
    return "&".join(f"{_uri_encode(k, False)}={_uri_encode(v, False)}" for k, v in sorted(params.items()))


def sign(*, method: str, host: str, path: str, query: dict[str, str], headers: dict[str, str], payload_hash: str,
         access_key: str, secret_key: str, region: str, amz_date: str) -> str:
    """Returns the Authorization header value for a request whose headers include host and x-amz-* already."""
    lower = {k.lower(): " ".join(v.strip().split()) for k, v in headers.items()}
    lower["host"] = host
    names = sorted(lower)
    canonical_request = "\n".join([
        method, _uri_encode(path, True), canonical_query(query),
        "".join(f"{n}:{lower[n]}\n" for n in names), ";".join(names), payload_hash,
    ])
    date = amz_date[:8]
    scope = f"{date}/{region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
    signature = hmac.new(signing_key(secret_key, date, region), to_sign.encode(), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"


class S3Client:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, region: str = "us-east-1", *,
                 transport: httpx.BaseTransport | None = None, timeout: float = 30.0) -> None:
        parts = urlsplit(endpoint)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("storage endpoint must be an http(s) URL")
        self.base = f"{parts.scheme}://{parts.netloc}"
        self.host = parts.netloc
        self.access_key, self.secret_key, self.region = access_key, secret_key, region
        self.client = httpx.Client(transport=transport, timeout=timeout)

    def _request(self, method: str, bucket: str, key: str = "", *, body: bytes = b"",
                 extra: dict[str, str] | None = None, query: dict[str, str] | None = None) -> httpx.Response:
        path = f"/{bucket}" + (f"/{key}" if key else "")
        amz_date = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        payload_hash = hashlib.sha256(body).hexdigest()
        headers = {"x-amz-date": amz_date, "x-amz-content-sha256": payload_hash, **(extra or {})}
        headers["Authorization"] = sign(method=method, host=self.host, path=path, query=query or {}, headers=headers,
                                        payload_hash=payload_hash, access_key=self.access_key,
                                        secret_key=self.secret_key, region=self.region, amz_date=amz_date)
        url = self.base + _uri_encode(path, True)
        if query:
            url += "?" + canonical_query(query)
        return self.client.request(method, url, content=body, headers=headers)

    def bucket_exists(self, bucket: str) -> bool:
        status = self._request("HEAD", bucket).status_code
        if status not in (200, 404):
            raise StorageError(status, "check bucket")
        return status == 200

    def ensure_bucket(self, bucket: str) -> bool:
        """Creates the bucket if it is missing. Returns True when it was created."""
        if self.bucket_exists(bucket):
            return False
        response = self._request("PUT", bucket)
        if response.status_code not in (200, 409):  # 409: created at the same moment by another process
            raise StorageError(response.status_code, "create bucket", response.text)
        return response.status_code == 200

    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        response = self._request("PUT", bucket, key, body=data, extra={"content-type": content_type})
        if response.status_code != 200:
            raise StorageError(response.status_code, "put", response.text)

    def get(self, bucket: str, key: str) -> bytes:
        response = self._request("GET", bucket, key)
        if response.status_code != 200:
            raise StorageError(response.status_code, "get", response.text)
        return response.content

    def head(self, bucket: str, key: str) -> dict[str, Any] | None:
        response = self._request("HEAD", bucket, key)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise StorageError(response.status_code, "head")
        return {"size": int(response.headers.get("content-length", "0")),
                "content_type": response.headers.get("content-type")}

    def delete(self, bucket: str, key: str) -> None:
        response = self._request("DELETE", bucket, key)
        if response.status_code not in (200, 204, 404):
            raise StorageError(response.status_code, "delete", response.text)
