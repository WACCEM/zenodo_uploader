#!/usr/bin/env python3
"""Upload the files in a folder to an existing Zenodo draft; never publish."""
import argparse
from fnmatch import fnmatch
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlparse


def md5(path):
    digest = hashlib.md5()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def matches(remote, size, checksum):
    return (remote.get('filesize', remote.get('size')) == size and
            str(remote.get('checksum', '')).lower().removeprefix('md5:') == checksum)


def draft_id(text):
    """Accept a bare draft ID or a pasted draft URL such as .../uploads/23523604."""
    found = re.search(r'(\d+)/?$', text.split('?')[0].split('#')[0].strip())
    if not found:
        raise argparse.ArgumentTypeError('expected a draft ID or draft URL: ' + text)
    return int(found.group(1))


def find_files(directory, include, exclude):
    if not directory.is_dir():
        raise RuntimeError('Not a folder: ' + str(directory))
    paths = sorted(
        p for p in directory.iterdir()
        if p.is_file() and not p.name.startswith('.')
        and (not include or any(fnmatch(p.name, g) for g in include))
        and not any(fnmatch(p.name, g) for g in exclude))
    if not paths:
        raise RuntimeError('No files to upload in ' + str(directory))
    return paths


class Client:
    def __init__(self, token, low_speed_time=1800, low_speed_limit=1, limit_rate=None):
        # Pass the secret through stdin, never a command argument or a disk file.
        if not token or any(c in token for c in '\r\n'):
            raise RuntimeError('Empty or invalid token.')
        escaped = token.replace('\\', '\\\\').replace('"', '\\"')
        self.config = 'header = "Authorization: Bearer ' + escaped + '"\n'
        self.low_speed_time = low_speed_time
        self.low_speed_limit = low_speed_limit
        self.limit_rate = limit_rate

    def request(self, url, path=None, method=None):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'zenodo.org':
            raise RuntimeError('Refusing unexpected API host: ' + url)
        with tempfile.TemporaryDirectory(prefix='zenodo-') as folder:
            response = Path(folder) / 'response.json'
            cmd = ['curl', '--disable', '--config', '-', '--http1.1',
                   '--connect-timeout', '60', '--output', str(response),
                   '--write-out', '%{http_code}']
            if path is None:
                cmd += ['--silent', '--show-error', '--max-time', '120', '--retry', '3']
                if method:
                    cmd += ['--request', method]
            else:
                # No overall --max-time: a 7 GB upload legitimately takes hours. Only
                # abort if the transfer stalls for low_speed_time seconds.
                cmd += ['--progress-bar', '--keepalive-time', '30',
                        '--header', 'Content-Type: application/octet-stream',
                        '--upload-file', str(path)]
                if self.low_speed_time > 0:
                    cmd += ['--speed-limit', str(self.low_speed_limit),
                            '--speed-time', str(self.low_speed_time)]
                if self.limit_rate:
                    cmd += ['--limit-rate', self.limit_rate]
            result = subprocess.run(cmd + [url], input=self.config, text=True,
                                    stdout=subprocess.PIPE)
            raw = response.read_text(errors='replace') if response.exists() else ''
            status = int(result.stdout) if result.stdout.isdigit() else 0
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
            return result.returncode, status, data, raw[:1000]

    def get(self, url):
        code, status, data, raw = self.request(url)
        if code or status != 200 or data is None:
            raise RuntimeError(f'GET failed: curl={code}, HTTP={status}. {raw}')
        return data

    def delete(self, url):
        code, status, data, raw = self.request(url, method='DELETE')
        if code or status not in (200, 204):
            raise RuntimeError(f'DELETE failed: curl={code}, HTTP={status}. {raw}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path,
                        help='folder containing the files to upload (not searched recursively)')
    parser.add_argument('--draft-id', required=True, type=draft_id,
                        help='ID or URL of your saved NEW VERSION draft, not the old DOI')
    parser.add_argument('--include', action='append', default=[], metavar='GLOB',
                        help='only upload file names matching this pattern (repeatable)')
    parser.add_argument('--exclude', action='append', default=[], metavar='GLOB',
                        help='skip file names matching this pattern (repeatable)')
    parser.add_argument('--retries', type=int, default=8,
                        help='upload attempts per file (default: %(default)s)')
    parser.add_argument('--retry-wait', type=int, default=60, metavar='SEC',
                        help='base wait before a retry, grows per attempt up to 600 s '
                             '(default: %(default)s)')
    parser.add_argument('--low-speed-time', type=int, default=1800, metavar='SEC',
                        help='abort an upload that stays below --low-speed-limit this long; '
                             '0 disables the check (default: %(default)s)')
    parser.add_argument('--low-speed-limit', type=int, default=1, metavar='BYTES/SEC',
                        help='stall threshold (default: %(default)s)')
    parser.add_argument('--limit-rate', metavar='RATE',
                        help='cap the upload speed, curl syntax such as 5M')
    parser.add_argument('--replace-mismatched', action='store_true',
                        help='delete a same-named file in the draft whose size/MD5 differ, '
                             'then upload again')
    parser.add_argument('--yes', action='store_true',
                        help='skip the confirmation prompt (for reruns)')
    args = parser.parse_args()
    paths = find_files(args.directory, args.include, args.exclude)
    names = {p.name for p in paths}
    token = os.environ.get('ZENODO_TOKEN') or getpass.getpass(
        'Zenodo token (hidden; paste here, not in chat): ')
    client = Client(token, args.low_speed_time, args.low_speed_limit, args.limit_rate)
    base = f'https://zenodo.org/api/deposit/depositions/{args.draft_id}'
    draft = client.get(base)
    if draft.get('submitted') is not False or draft.get('state') != 'unsubmitted':
        raise RuntimeError('This is not an unsubmitted draft. Open your new-version draft and use its ID.')
    bucket = draft.get('links', {}).get('bucket')
    if not bucket:
        raise RuntimeError('Draft has no bucket link; cannot upload.')
    print('\nDraft ID:', draft.get('id'))
    print('Title:', draft.get('metadata', {}).get('title'))
    print('Version:', draft.get('metadata', {}).get('version', '(not specified)'))
    print('Draft link:', draft.get('links', {}).get('html', ''))
    print('Local total: %.2f GB in %d files' % (sum(p.stat().st_size for p in paths)/1e9, len(paths)))
    existing = client.get(base + '/files')
    extras = [f['filename'] for f in existing if f['filename'] not in names]
    if extras:
        print('Additional files already in this draft:', ', '.join(extras))
        print('Review these in the Zenodo web UI; this script will not remove them.')
    if not args.yes and input('Confirm this is your intended new-version draft by typing its ID: ').strip() != str(args.draft_id):
        raise RuntimeError('Draft not confirmed; nothing uploaded.')
    verified = {}
    for path in sorted(paths, key=lambda p: p.stat().st_size):
        stamp = (path.stat().st_size, path.stat().st_mtime_ns)
        print('\nComputing local MD5:', path.name, flush=True)
        checksum = md5(path)
        for attempt in range(1, args.retries + 1):
            files = client.get(base + '/files')
            remote = next((f for f in files if f['filename'] == path.name), None)
            if remote:
                if matches(remote, stamp[0], checksum):
                    print('Verified on Zenodo:', path.name, flush=True)
                    break
                if not args.replace_mismatched:
                    raise RuntimeError('Existing remote file differs or is incomplete: ' + path.name +
                                       '. Inspect/remove ONLY that file in the draft UI, or rerun with '
                                       '--replace-mismatched.')
                print('Deleting mismatched remote file:', path.name, flush=True)
                client.delete(f"{base}/files/{remote['id']}")
            if (path.stat().st_size, path.stat().st_mtime_ns) != stamp:
                raise RuntimeError('Local file changed: ' + path.name)
            print(f'Uploading {path.name}; attempt {attempt}/{args.retries}', flush=True)
            code, status, data, raw = client.request(bucket.rstrip('/') + '/' + quote(path.name, safe=''), path)
            if code == 0 and 200 <= status < 300:
                files = client.get(base + '/files')
                remote = next((f for f in files if f['filename'] == path.name), None)
                if remote and matches(remote, stamp[0], checksum):
                    print('Upload verified:', path.name, flush=True)
                    break
                raise RuntimeError('Upload returned success but size/MD5 verification failed: ' + path.name)
            print(f'Upload failed: curl={code}, HTTP={status}. {raw}', flush=True)
            transient = status in (408, 429, 500, 502, 503, 504) or (code != 0 and status < 400)
            if not transient or attempt == args.retries:
                raise RuntimeError('Upload stopped. Resolve the error and rerun; matching completed files will be skipped.')
            wait = min(args.retry_wait * attempt, 600)
            print(f'Waiting {wait} seconds; will check whether the file completed before retrying.', flush=True)
            time.sleep(wait)
        if (path.stat().st_size, path.stat().st_mtime_ns) != stamp:
            raise RuntimeError('Local file changed during transfer: ' + path.name)
        verified[path.name] = (stamp[0], checksum)
    final = {f['filename']: f for f in client.get(base + '/files')}
    for name, (size, checksum) in verified.items():
        if name not in final or not matches(final[name], size, checksum):
            raise RuntimeError('Final verification failed: ' + name)
    print(f'\nAll {len(verified)} files verified by size and MD5. Review and publish the draft in the Zenodo web UI.')
    print('No metadata was changed and nothing was published by this script.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. Rerun to skip verified completed files.', file=sys.stderr)
        sys.exit(130)
    except (RuntimeError, OSError, ValueError) as exc:
        print('\nERROR:', exc, file=sys.stderr)
        sys.exit(1)
