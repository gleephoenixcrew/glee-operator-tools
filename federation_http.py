"""Authority-bound outbound HTTP edge for GLEE Intelligence Federation v0.

The public federation kernel is pure. This module is the deliberately narrow edge
that may perform network I/O when — and only when — a local grant binds the exact
request bytes, host, method, expiry, and use budget.

Credentials, spending, publication, and workspace mutation are intentionally not
represented here. They require separate authority surfaces.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional, Tuple
from urllib.parse import urlsplit

A2A_PROTOCOL_VERSION = "1.0"
USER_AGENT = "GLEE-Intelligence-Federation/0"


class NetworkDenied(RuntimeError):
    pass


class NetworkProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutboundRequest:
    method: str
    url: str
    headers: Tuple[Tuple[str, str], ...]
    body: bytes = b""

    @property
    def request_hash(self) -> str:
        canonical = {
            "method": self.method.upper(),
            "url": self.url,
            "headers": tuple(sorted((k.lower(), v) for k, v in self.headers)),
            "body_sha256": hashlib.sha256(self.body).hexdigest(),
        }
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class NetworkGrant:
    grant_id: str
    expires_at: str
    allowed_hosts: Tuple[str, ...]
    allowed_methods: Tuple[str, ...]
    allowed_request_hashes: Tuple[str, ...]
    max_requests: int = 1
    max_response_bytes: int = 1_000_000
    timeout_seconds: int = 10

    def validate(self) -> None:
        if not self.grant_id:
            raise ValueError("grant_id must be non-empty")
        _parse_time(self.expires_at)
        if not self.allowed_hosts or any(not host for host in self.allowed_hosts):
            raise ValueError("allowed_hosts must contain non-empty hosts")
        normalized_methods = tuple(method.upper() for method in self.allowed_methods)
        if not normalized_methods or any(method not in {"GET", "POST"} for method in normalized_methods):
            raise ValueError("allowed_methods must be GET and/or POST")
        if not self.allowed_request_hashes or any(not _is_sha256_hex(value) for value in self.allowed_request_hashes):
            raise ValueError("allowed_request_hashes must contain SHA-256 hex digests")
        if isinstance(self.max_requests, bool) or self.max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if isinstance(self.max_response_bytes, bool) or self.max_response_bytes < 1:
            raise ValueError("max_response_bytes must be >= 1")
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be >= 1")


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[OutboundRequest, int, int], HttpResult]


class BoundedHttpClient:
    """Stateful single-grant client. The use counter makes replay fail closed."""

    def __init__(self, grant: NetworkGrant, *, transport: Optional[Transport] = None):
        grant.validate()
        self.grant = grant
        self._transport = transport or _pinned_https_transport
        self._uses = 0

    @property
    def uses(self) -> int:
        return self._uses

    def execute(self, request: OutboundRequest, *, now: str) -> HttpResult:
        self._authorize(request, now=now)
        self._uses += 1
        result = self._transport(request, self.grant.timeout_seconds, self.grant.max_response_bytes)
        if not 200 <= result.status < 300:
            raise NetworkProtocolError(f"unexpected HTTP status {result.status}")
        if len(result.body) > self.grant.max_response_bytes:
            raise NetworkProtocolError("response exceeds max_response_bytes")
        return result

    def execute_json(self, request: OutboundRequest, *, now: str) -> Mapping[str, object]:
        result = self.execute(request, now=now)
        try:
            decoded = json.loads(result.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NetworkProtocolError("response is not valid UTF-8 JSON") from exc
        if not isinstance(decoded, Mapping):
            raise NetworkProtocolError("JSON response must be an object")
        return decoded

    def _authorize(self, request: OutboundRequest, *, now: str) -> None:
        current = _parse_time(now)
        if current >= _parse_time(self.grant.expires_at):
            raise NetworkDenied("network grant expired")
        if self._uses >= self.grant.max_requests:
            raise NetworkDenied("network grant use budget exhausted")

        method = request.method.upper()
        if method not in tuple(value.upper() for value in self.grant.allowed_methods):
            raise NetworkDenied(f"method {method} is not granted")

        parts = urlsplit(request.url)
        if parts.scheme.lower() != "https":
            raise NetworkDenied("only HTTPS federation requests are allowed")
        if not parts.hostname:
            raise NetworkDenied("request URL must contain a hostname")
        if parts.port not in (None, 443):
            raise NetworkDenied("v0 federation network grants permit HTTPS port 443 only")
        if parts.username is not None or parts.password is not None:
            raise NetworkDenied("userinfo in request URLs is forbidden")
        if parts.fragment:
            raise NetworkDenied("URL fragments are forbidden")
        host = parts.hostname.lower().rstrip(".")
        allowed = tuple(value.lower().rstrip(".") for value in self.grant.allowed_hosts)
        if host not in allowed:
            raise NetworkDenied(f"host {host!r} is not granted")
        _reject_private_ip_literal(host)

        allowed_header_names = {"accept", "user-agent", "content-type", "a2a-version"}
        header_names = [key.lower() for key, _ in request.headers]
        if len(header_names) != len(set(header_names)):
            raise NetworkDenied("duplicate outbound headers are forbidden")
        unexpected = sorted(set(header_names).difference(allowed_header_names))
        if unexpected:
            raise NetworkDenied("network-only grant cannot carry headers: " + ", ".join(unexpected))

        if request.request_hash not in self.grant.allowed_request_hashes:
            raise NetworkDenied("exact outbound request hash is not granted")


def build_agent_card_request(manifest_url: str) -> OutboundRequest:
    return OutboundRequest(
        method="GET",
        url=manifest_url,
        headers=(
            ("A2A-Version", A2A_PROTOCOL_VERSION),
            ("Accept", "application/json"),
            ("User-Agent", USER_AGENT),
        ),
    )


def build_a2a_readonly_query(
    endpoint: str,
    text: str,
    *,
    message_id: str,
    request_id: str,
) -> OutboundRequest:
    """Build an A2A 1.0 JSON-RPC SendMessage request.

    `glee_authority` is an advisory statement for the remote peer. The real local
    safety property is the grant's exact request hash: a changed body is a different
    request and is refused locally.
    """

    if not message_id or not request_id:
        raise ValueError("message_id and request_id must be non-empty")
    if not isinstance(text, str) or not text:
        raise ValueError("text must be non-empty")
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "ROLE_USER",
                "parts": [{"text": text}],
                "metadata": {
                    "glee_authority": {
                        "mode": "read_only",
                        "forbidden": ["credential", "spend", "publication", "write"],
                    }
                },
            },
            "configuration": {
                "acceptedOutputModes": ["application/json", "text/plain"],
            },
        },
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return OutboundRequest(
        method="POST",
        url=endpoint,
        headers=(
            ("A2A-Version", A2A_PROTOCOL_VERSION),
            ("Accept", "application/json"),
            ("Content-Type", "application/json"),
            ("User-Agent", USER_AGENT),
        ),
        body=body,
    )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS connection whose socket target is the already-verified DNS answer.

    The HTTP Host header and TLS SNI/certificate validation still use `host`.
    Pinning the socket target closes the DNS-check/second-resolution race that a
    generic high-level HTTP client would otherwise introduce.
    """

    def __init__(self, host: str, pinned_ip: str, *, port: int, timeout: int):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _pinned_https_transport(request: OutboundRequest, timeout_seconds: int, max_response_bytes: int) -> HttpResult:
    parts = urlsplit(request.url)
    host = parts.hostname
    if not host:
        raise NetworkDenied("request URL must contain a hostname")
    port = parts.port or 443
    if port != 443:
        raise NetworkDenied("v0 federation network grants permit HTTPS port 443 only")

    addresses = _resolve_global_addresses(host, port)
    pinned_ip = addresses[0]
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query

    connection = _PinnedHTTPSConnection(host, pinned_ip, port=port, timeout=timeout_seconds)
    try:
        connection.request(
            request.method.upper(),
            path,
            body=request.body if request.method.upper() == "POST" else None,
            headers={key: value for key, value in request.headers},
        )
        response = connection.getresponse()
        body = response.read(max_response_bytes + 1)
        return HttpResult(
            status=int(response.status),
            headers={str(k): str(v) for k, v in response.headers.items()},
            body=body,
        )
    except (OSError, ssl.SSLError, socket.timeout, http.client.HTTPException) as exc:
        raise NetworkProtocolError(f"network transport failed: {exc}") from exc
    finally:
        connection.close()


def _resolve_global_addresses(host: str, port: int) -> Tuple[str, ...]:
    _reject_private_ip_literal(host)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise NetworkProtocolError(f"DNS resolution failed for {host}: {exc}") from exc

    addresses = []
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise NetworkDenied(f"DNS returned an invalid IP address for {host}") from exc
        if not ip.is_global:
            raise NetworkDenied(f"resolved address for {host} is not globally routable")
        addresses.append(str(ip))
    unique = tuple(sorted(set(addresses)))
    if not unique:
        raise NetworkProtocolError(f"DNS resolution returned no addresses for {host}")
    return unique


def _reject_private_ip_literal(host: str) -> None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if not ip.is_global:
        raise NetworkDenied("private, loopback, link-local, or reserved IP literals are forbidden")


def _is_sha256_hex(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)
