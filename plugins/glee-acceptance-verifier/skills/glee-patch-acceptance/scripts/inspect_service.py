"""Fetch a public GLEE contract or a fixed synthetic preview. No paid requests."""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = 'https://platform.gleephoenix.com/agents/services.json'
MAX_BYTES = 262144
VERDICTS = {'PASS', 'FAIL', 'INSUFFICIENT_EVIDENCE'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_document(document, command, case):
    if not isinstance(document, dict):
        raise ValueError('Response must be a JSON object')
    if command == 'contract':
        invocation = document.get('example_invocation')
        if (document.get('id') != 'patch_verification' or
                document.get('method') != 'POST' or
                not isinstance(document.get('input'), dict) or
                not document['input'].get('patch') or
                not isinstance(invocation, dict) or
                not isinstance(invocation.get('body'), dict) or
                not isinstance(invocation['body'].get('patch'), str) or
                not invocation['body']['patch'] or
                document.get('endpoint') != 'https://platform.gleephoenix.com/api/x402/verify/patch' or
                not isinstance(document.get('price_atomic'), str) or
                not document['price_atomic'].isascii() or
                not document['price_atomic'].isdecimal() or
                not isinstance(document.get('network'), str) or
                not document['network'] or
                not isinstance(document.get('verdicts'), list) or
                not all(isinstance(value, str) for value in document['verdicts']) or
                set(document['verdicts']) != VERDICTS):
            raise ValueError('Response lacks a usable patch verification contract')
    else:
        result = document.get('result')
        preview_input = document.get('input')
        if (document.get('schema') != 'glee.patch_preview.v1' or
                document.get('service') != 'patch_verification' or
                document.get('case') != case or
                document.get('payment_execution') is not False or
                document.get('signed_receipt') is not False or
                document.get('price_atomic') != '0' or
                not isinstance(preview_input, dict) or
                not isinstance(preview_input.get('patch'), str) or
                not preview_input['patch'] or
                not isinstance(result, dict) or
                not isinstance(result.get('verdict'), str) or
                result['verdict'] not in VERDICTS or
                not isinstance(result.get('findings'), list) or
                not isinstance(document.get('scope'), str) or
                not document['scope']):
            raise ValueError('Response lacks the requested free fixed preview result')


def fetch(command, case=None, internal=False):
    params = {'service': 'patch_verification',
              'ref': 'glee_int_cursor_20261018' if internal else 'cursor_patch_20261018'}
    if command == 'preview':
        params['evaluate'] = case
    url = BASE + '?' + urlencode(params)
    agent = 'glee-internal-cursor-test/0.1.0' if internal else 'cursor-glee-acceptance/0.1.0'
    request = Request(url, headers={'Accept': 'application/json', 'User-Agent': agent}, method='GET')
    with build_opener(NoRedirect).open(request, timeout=20) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Response exceeds 256 KiB')
        document = json.loads(raw)
    validate_document(document, command, case)
    return {'url': url, 'internal_test': internal, 'document': document}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--internal-test', action='store_true', help='Separate maintainer traffic from the public campaign')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('contract')
    preview = sub.add_parser('preview')
    preview.add_argument('case', choices=['pass', 'fail', 'insufficient'])
    args = parser.parse_args(argv)
    try:
        result = fetch(args.command, getattr(args, 'case', None), args.internal_test)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        print(json.dumps({'error': str(error), 'paid_request_sent': False}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
