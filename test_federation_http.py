#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest import mock

from federation_http import (
    A2A_PROTOCOL_VERSION,
    BoundedHttpClient,
    HttpResult,
    NetworkDenied,
    NetworkGrant,
    NetworkProtocolError,
    build_a2a_readonly_query,
    build_agent_card_request,
    _pinned_https_transport,
    _resolve_global_addresses,
)

NOW = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
def z(value): return value.isoformat().replace("+00:00", "Z")


class FederationHttpTests(unittest.TestCase):
    def grant(self, request, **kw):
        values = dict(
            grant_id="grant-1",
            expires_at=z(NOW + timedelta(minutes=5)),
            allowed_hosts=("peer.example",),
            allowed_methods=(request.method,),
            allowed_request_hashes=(request.request_hash,),
            max_requests=1,
            max_response_bytes=1024,
            timeout_seconds=3,
        )
        values.update(kw)
        return NetworkGrant(**values)

    def ok_transport(self, request, timeout, maximum):
        return HttpResult(200, {"content-type": "application/json"}, b'{"ok":true}')

    def test_01_agent_card_request_is_get_only_versioned_and_hashable(self):
        request = build_agent_card_request("https://peer.example/.well-known/agent-card.json")
        self.assertEqual(request.method, "GET")
        self.assertEqual(dict(request.headers)["A2A-Version"], A2A_PROTOCOL_VERSION)
        self.assertEqual(len(request.request_hash), 64)
        self.assertFalse(request.body)

    def test_02_a2a_builder_uses_v1_sendmessage_and_no_auth_header(self):
        request = build_a2a_readonly_query(
            "https://peer.example/a2a", "List public capabilities only.",
            message_id="m1", request_id="r1",
        )
        payload = json.loads(request.body)
        self.assertEqual(payload["method"], "SendMessage")
        self.assertEqual(payload["params"]["message"]["role"], "ROLE_USER")
        self.assertEqual(dict(request.headers)["A2A-Version"], A2A_PROTOCOL_VERSION)
        self.assertNotIn("Authorization", dict(request.headers))
        self.assertEqual(
            payload["params"]["message"]["metadata"]["glee_authority"]["forbidden"],
            ["credential", "spend", "publication", "write"],
        )

    def test_03_http_is_denied(self):
        request = build_agent_card_request("http://peer.example/.well-known/agent-card.json")
        client = BoundedHttpClient(self.grant(request), transport=self.ok_transport)
        with self.assertRaisesRegex(NetworkDenied, "HTTPS"):
            client.execute(request, now=z(NOW))

    def test_04_ungranted_host_is_denied(self):
        request = build_agent_card_request("https://evil.example/.well-known/agent-card.json")
        grant = self.grant(request, allowed_hosts=("peer.example",))
        with self.assertRaisesRegex(NetworkDenied, "not granted"):
            BoundedHttpClient(grant, transport=self.ok_transport).execute(request, now=z(NOW))

    def test_05_private_ip_literal_is_denied(self):
        request = build_agent_card_request("https://127.0.0.1/.well-known/agent-card.json")
        grant = self.grant(request, allowed_hosts=("127.0.0.1",))
        with self.assertRaisesRegex(NetworkDenied, "private"):
            BoundedHttpClient(grant, transport=self.ok_transport).execute(request, now=z(NOW))

    def test_06_expired_grant_is_denied(self):
        request = build_agent_card_request("https://peer.example/.well-known/agent-card.json")
        grant = self.grant(request, expires_at=z(NOW))
        with self.assertRaisesRegex(NetworkDenied, "expired"):
            BoundedHttpClient(grant, transport=self.ok_transport).execute(request, now=z(NOW))

    def test_07_exact_request_hash_prevents_body_mutation(self):
        request = build_a2a_readonly_query(
            "https://peer.example/a2a", "read only", message_id="m1", request_id="r1"
        )
        client = BoundedHttpClient(self.grant(request), transport=self.ok_transport)
        tampered = replace(request, body=request.body + b" ")
        with self.assertRaisesRegex(NetworkDenied, "request hash"):
            client.execute(tampered, now=z(NOW))

    def test_08_single_use_grant_is_consumed_before_io(self):
        request = build_agent_card_request("https://peer.example/.well-known/agent-card.json")
        def fail_transport(request, timeout, maximum):
            raise NetworkProtocolError("timeout")
        client = BoundedHttpClient(self.grant(request), transport=fail_transport)
        with self.assertRaises(NetworkProtocolError):
            client.execute(request, now=z(NOW))
        self.assertEqual(client.uses, 1)
        with self.assertRaisesRegex(NetworkDenied, "use budget"):
            client.execute(request, now=z(NOW))

    def test_09_successful_exact_request_executes_once(self):
        request = build_agent_card_request("https://peer.example/.well-known/agent-card.json")
        seen = []
        def transport(r, timeout, maximum):
            seen.append((r.request_hash, timeout, maximum))
            return HttpResult(200, {}, b'{"name":"peer"}')
        client = BoundedHttpClient(self.grant(request), transport=transport)
        result = client.execute_json(request, now=z(NOW))
        self.assertEqual(result["name"], "peer")
        self.assertEqual(seen, [(request.request_hash, 3, 1024)])

    def test_10_redirect_or_other_non_2xx_is_not_accepted(self):
        request = build_agent_card_request("https://peer.example/.well-known/agent-card.json")
        client = BoundedHttpClient(
            self.grant(request),
            transport=lambda r, t, m: HttpResult(302, {"location": "https://evil.example"}, b""),
        )
        with self.assertRaisesRegex(NetworkProtocolError, "302"):
            client.execute(request, now=z(NOW))

    def test_11_response_size_is_bounded_even_for_fake_transport(self):
        request = build_agent_card_request("https://peer.example/.well-known/agent-card.json")
        client = BoundedHttpClient(
            self.grant(request, max_response_bytes=4),
            transport=lambda r, t, m: HttpResult(200, {}, b"12345"),
        )
        with self.assertRaisesRegex(NetworkProtocolError, "max_response_bytes"):
            client.execute(request, now=z(NOW))

    def test_12_network_only_grant_rejects_credential_headers(self):
        base = build_agent_card_request("https://peer.example/.well-known/agent-card.json")
        request = replace(base, headers=base.headers + (("Authorization", "Bearer secret"),))
        grant = self.grant(request)
        with self.assertRaisesRegex(NetworkDenied, "cannot carry headers"):
            BoundedHttpClient(grant, transport=self.ok_transport).execute(request, now=z(NOW))

    def test_13_invalid_json_is_rejected(self):
        request = build_agent_card_request("https://peer.example/.well-known/agent-card.json")
        client = BoundedHttpClient(
            self.grant(request),
            transport=lambda r, t, m: HttpResult(200, {}, b"not-json"),
        )
        with self.assertRaisesRegex(NetworkProtocolError, "valid UTF-8 JSON"):
            client.execute_json(request, now=z(NOW))

    def test_14_nonstandard_https_port_is_denied(self):
        request = build_agent_card_request("https://peer.example:8443/.well-known/agent-card.json")
        client = BoundedHttpClient(self.grant(request), transport=self.ok_transport)
        with self.assertRaisesRegex(NetworkDenied, "port 443"):
            client.execute(request, now=z(NOW))

    def test_15_dns_private_answer_is_denied(self):
        answer = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with mock.patch("federation_http.socket.getaddrinfo", return_value=answer):
            with self.assertRaisesRegex(NetworkDenied, "not globally routable"):
                _resolve_global_addresses("peer.example", 443)

    def test_16_mixed_public_private_dns_answers_fail_closed(self):
        answers = [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.8", 443)),
        ]
        with mock.patch("federation_http.socket.getaddrinfo", return_value=answers):
            with self.assertRaisesRegex(NetworkDenied, "not globally routable"):
                _resolve_global_addresses("peer.example", 443)

    def test_17_default_transport_pins_the_verified_dns_answer(self):
        request = build_agent_card_request("https://peer.example/.well-known/agent-card.json?x=1")
        answers = [(2, 1, 6, "", ("93.184.216.34", 443))]
        response = mock.Mock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = b'{"ok":true}'
        connection = mock.Mock()
        connection.getresponse.return_value = response
        with mock.patch("federation_http.socket.getaddrinfo", return_value=answers) as resolver:
            with mock.patch("federation_http._PinnedHTTPSConnection", return_value=connection) as ctor:
                result = _pinned_https_transport(request, 3, 1024)
        self.assertEqual(result.status, 200)
        resolver.assert_called_once_with("peer.example", 443, type=mock.ANY)
        ctor.assert_called_once_with("peer.example", "93.184.216.34", port=443, timeout=3)
        connection.request.assert_called_once_with(
            "GET",
            "/.well-known/agent-card.json?x=1",
            body=None,
            headers={
                "A2A-Version": "1.0",
                "Accept": "application/json",
                "User-Agent": "GLEE-Intelligence-Federation/0",
            },
        )
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
