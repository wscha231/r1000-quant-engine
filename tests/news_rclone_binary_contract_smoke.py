"""Pinned real-rclone contract against a loopback-only synthetic Drive API.

No real account, OAuth refresh, SEC request, remote write or external forwarding.
The binary is NOT mocked. The API/data/token/certificate are synthetic fixtures.
Use --harness-only without rclone; CI requires --rclone-bin and runs both suites.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
HOST = 'www.googleapis.com'
TOKEN = 'SYNTHETIC_TEST_TOKEN_NOT_AN_ACCOUNT'
BODY = b'{"scope":"synthetic-rclone-contract-only"}\n'
RCLONE = None


def fixture_metadata(oid='FixtureFile'):
    return {'id': oid, 'name': 'metadata.json', 'size': str(len(BODY)),
            'mimeType': 'application/json', 'modifiedTime': '2026-01-01T00:00:00Z',
            'md5Checksum': hashlib.md5(BODY).hexdigest(),
            'parents': ['FixtureRoot'], 'capabilities': {'canDownload': True}}


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *_):
        pass  # never log headers or credential-shaped values

    def reply(self, status, data):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.server.operations.append(('GET', self.path))
        if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
            self.server.violations.append('UNEXPECTED_AUTHORIZATION')
            self.reply(401, {'error': {'code': 401, 'message': 'synthetic-only'}})
            return
        u = urlsplit(self.path)
        query = parse_qs(u.query)
        if u.path == '/drive/v3/files/FixtureRoot':
            self.reply(200, {'id': 'FixtureRoot', 'name': 'fixture-root',
                             'mimeType': 'application/vnd.google-apps.folder'})
        elif u.path == '/drive/v3/files/FixtureFile':
            self.reply(200, BODY if query.get('alt') == ['media'] else fixture_metadata())
        elif u.path == '/drive/v3/files':
            self.reply(200, {'files': [fixture_metadata()], 'incompleteSearch': False})
        elif u.path == '/drive/v3/files/DeniedFile':
            self.reply(403, {'error': {'code': 403, 'message': 'synthetic-denied',
                                      'errors': [{'reason': 'forbidden'}]}})
        else:
            self.reply(404, {'error': {'code': 404, 'message': 'synthetic-missing',
                                      'errors': [{'reason': 'notFound'}]}})

    def reject_write(self):
        self.server.operations.append((self.command, self.path))
        self.server.violations.append('REMOTE_WRITE_ATTEMPT')
        self.reply(405, {'error': {'code': 405, 'message': 'read-only fixture'}})

    do_POST = do_PUT = do_PATCH = do_DELETE = reject_write


class ConnectHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(10)
        header = bytearray()
        while not header.endswith(b'\r\n\r\n') and len(header) < 8192:
            part = self.request.recv(1)
            if not part:
                return
            header.extend(part)
        first = bytes(header).split(b'\r\n', 1)[0]
        if first != ('CONNECT ' + HOST + ':443 HTTP/1.1').encode():
            self.server.violations.append('UNEXPECTED_CONNECT_TARGET')
            self.request.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
            return
        # No forwarding/DNS: the accepted tunnel terminates in this fixture.
        self.request.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
        try:
            with self.server.tls.wrap_socket(self.request, server_side=True) as tls_sock:
                ApiHandler(tls_sock, self.client_address, self.server)
        except (ssl.SSLError, TimeoutError, OSError):
            self.server.violations.append('TLS_OR_CONNECTION_FAILURE')


class FixtureServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        self.violations.append('FIXTURE_HANDLER_FAILURE')


@contextmanager
def fixture_server(work: Path):
    cert, key = work/'fixture.crt', work/'fixture.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                    '-keyout', str(key), '-out', str(cert), '-days', '2',
                    '-subj', '/CN=' + HOST, '-addext', 'subjectAltName=DNS:' + HOST],
                   check=True, capture_output=True, timeout=30)
    key.chmod(0o600)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    tls.set_alpn_protocols(['http/1.1'])
    with FixtureServer(('127.0.0.1', 0), ConnectHandler) as server:
        server.tls, server.operations, server.violations = tls, [], []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server, cert
        finally:
            server.shutdown()
            thread.join(timeout=5)


def isolated_env(work: Path, port: int) -> dict[str, str]:
    # Do not inherit credentials, proxy settings, rclone overrides or CI tokens.
    proxy = 'http://127.0.0.1:' + str(port)
    return {'PATH': os.defpath, 'HOME': str(work), 'TMPDIR': str(work),
            'LANG': 'C.UTF-8', 'HTTP_PROXY': proxy, 'HTTPS_PROXY': proxy,
            'NO_PROXY': 'localhost,127.0.0.1'}


def write_config(work: Path) -> Path:
    token = {'access_token': TOKEN, 'token_type': 'Bearer',
             'expiry': '2099-01-01T00:00:00Z'}
    path = work/'rclone.conf'
    path.write_text('[gdrive]\ntype = drive\nscope = drive.readonly\n'
                    'root_folder_id = FixtureRoot\ntoken = ' + json.dumps(token) + '\n')
    path.chmod(0o600)
    return path


class HarnessTests(unittest.TestCase):
    def request(self, method, path):
        with tempfile.TemporaryDirectory() as tmp:
            with fixture_server(Path(tmp)) as (server, cert):
                conn = HTTPSConnection('127.0.0.1', server.server_address[1],
                    context=ssl.create_default_context(cafile=str(cert)), timeout=10)
                conn.set_tunnel(HOST, 443)
                conn.request(method, path, headers={'Authorization': 'Bearer ' + TOKEN})
                response = conn.getresponse()
                result = (response.status, response.read())
                conn.close()
                return result, list(server.violations)

    def test_tls_fixture_download(self):
        result, violations = self.request('GET', '/drive/v3/files/FixtureFile?alt=media')
        self.assertEqual(result, (200, BODY)); self.assertEqual(violations, [])

    def test_remote_write_rejected(self):
        result, violations = self.request('POST', '/drive/v3/files/FixtureFile/copy')
        self.assertEqual(result[0], 405)
        self.assertEqual(violations, ['REMOTE_WRITE_ATTEMPT'])

    def test_unrelated_connect_never_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with fixture_server(Path(tmp)) as (server, _):
                with socket.create_connection(server.server_address, timeout=5) as sock:
                    sock.sendall(b'CONNECT unrelated.invalid:443 HTTP/1.1\r\n\r\n')
                    self.assertIn(b'403', sock.recv(256))
                self.assertEqual(server.operations, [])
                self.assertIn('UNEXPECTED_CONNECT_TARGET', server.violations)

    def test_environment_does_not_inherit_keys(self):
        env = isolated_env(Path('/tmp/synthetic-only'), 12345)
        self.assertEqual(set(env), {'PATH','HOME','TMPDIR','LANG','HTTP_PROXY','HTTPS_PROXY','NO_PROXY'})
        self.assertFalse(any(k.startswith(('GITHUB_', 'RCLONE_', 'OPENAI_', 'GOOGLE_')) for k in env))


class BinaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.cm = fixture_server(self.work)
        self.server, self.cert = self.cm.__enter__()
        self.config = write_config(self.work)
        self.env = isolated_env(self.work, self.server.server_address[1])

    def tearDown(self):
        self.cm.__exit__(None, None, None)
        self.temp.cleanup()

    def command(self, *args):
        return subprocess.run([str(RCLONE), '--config', str(self.config),
            '--retries', '1', '--low-level-retries', '1', '--contimeout', '5s',
            '--timeout', '10s', '--ca-cert', str(self.cert), *args],
            env=self.env, cwd=self.work, capture_output=True, timeout=45)

    def assert_read_only(self):
        self.assertEqual(self.server.violations, [])
        self.assertTrue(self.server.operations, 'Expected actual binary HTTP requests')
        self.assertTrue(all(method == 'GET' for method, _ in self.server.operations))

    def test_pinned_binary_version(self):
        result = self.command('version')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode().splitlines()[0], 'rclone v1.75.0')
        self.assertEqual(self.server.operations, [])

    def test_copyid_downloads_to_absolute_local_file(self):
        target = self.work/'download.json'
        result = self.command('backend', 'copyid', 'gdrive,root_folder_id=FixtureRoot:',
            'FixtureFile', str(target), '--immutable', '--max-transfer', '16M')
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertEqual(target.read_bytes(), BODY)
        self.assert_read_only()
        self.assertTrue(any('alt=media' in path for _, path in self.server.operations))

    def test_actual_reference_reader_by_id(self):
        sys.path.insert(0, str(ROOT))
        from research.news_event_alpha_v1.review_guards import DriveReferences
        def call(*args):
            result = self.command(*args)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            return result.stdout
        view = DriveReferences(call, 'FixtureRoot').read_path(
            'gdrive:metadata.json', expected_id='FixtureFile')
        self.assertEqual(view, BODY)
        self.assert_read_only()

    def test_missing_id_fails_without_local_success(self):
        target = self.work/'missing.json'
        result = self.command('backend', 'copyid', 'gdrive,root_folder_id=FixtureRoot:',
            'MissingFile', str(target), '--immutable', '--max-transfer', '16M')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())
        self.assert_read_only()

    def test_forbidden_id_fails_without_write_fallback(self):
        target = self.work/'denied.json'
        result = self.command('backend', 'copyid', 'gdrive,root_folder_id=FixtureRoot:',
            'DeniedFile', str(target), '--immutable', '--max-transfer', '16M')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())
        self.assert_read_only()


def main():
    global RCLONE
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--rclone-bin', type=Path)
    mode.add_argument('--harness-only', action='store_true')
    args = p.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HarnessTests)
    if args.rclone_bin is not None:
        RCLONE = args.rclone_bin.resolve(strict=True)
        if not RCLONE.is_file():
            p.error('An actual rclone executable is required')
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(BinaryTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'contract': 'rclone-1.75.0-copyid-local-destination',
        'mode': 'HARNESS_ONLY' if args.harness_only else 'REAL_BINARY_SYNTHETIC_API',
        'test_methods': result.testsRun, 'passed': result.wasSuccessful(),
        'real_account_access': False, 'real_news_collected': False,
        'production_authorized': False}, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
