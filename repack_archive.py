#!/usr/bin/env python3
"""Repack a tar archive of yearly/monthly files into several smaller archives by year range."""
import argparse
import hashlib
from pathlib import Path
import re
import sys
import tarfile
import tempfile

YEAR = re.compile(r'(?<!\d)((?:19|20)\d{2})')


def md5(path):
    digest = hashlib.md5()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def year_of(path):
    found = YEAR.search(path.name)
    if not found:
        raise RuntimeError('No 4-digit year in file name: ' + path.name)
    return int(found.group(1))


def strip_owner(info):
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    if info.isdir():
        info.mode = 0o755
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='input .tar.gz / .tar (left untouched)')
    parser.add_argument('outdir', type=Path, help='folder for the new archives (created if needed)')
    parser.add_argument('--years-per-chunk', type=int, default=7,
                        help='years per output archive (default: %(default)s)')
    parser.add_argument('--start-year', type=int,
                        help='first year of the first chunk (default: earliest year found)')
    parser.add_argument('--no-compress', action='store_true',
                        help='write plain .tar (useful for already-compressed NetCDF)')
    args = parser.parse_args()
    if args.years_per_chunk < 1:
        raise RuntimeError('--years-per-chunk must be at least 1')
    if not args.source.is_file():
        raise RuntimeError('Missing file: ' + str(args.source))
    stem = re.sub(r'\.(tar\.gz|tgz|tar)$', '', args.source.name)
    args.outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.repack-', dir=args.outdir) as scratch:
        print('Extracting', args.source, flush=True)
        with tarfile.open(args.source) as archive:
            if hasattr(tarfile, 'data_filter'):
                archive.extractall(scratch, filter='data')
            else:
                archive.extractall(scratch)
        files = sorted(p for p in Path(scratch).rglob('*') if p.is_file())
        if not files:
            raise RuntimeError('Archive contains no files.')
        first = args.start_year if args.start_year is not None else min(year_of(p) for p in files)
        chunks = {}
        for path in files:
            year = year_of(path)
            if year < first:
                raise RuntimeError(f'{path.name}: year {year} is before --start-year {first}')
            chunks.setdefault((year - first) // args.years_per_chunk, []).append(path)
        root = Path(scratch)
        ext = '.tar' if args.no_compress else '.tar.gz'
        plan = []
        for index in sorted(chunks):
            years = [year_of(p) for p in chunks[index]]
            name = f'{stem}_{min(years)}-{max(years)}'
            target = args.outdir / (name + ext)
            if target.exists():
                raise RuntimeError('Refusing to overwrite: ' + str(target))
            plan.append((name, target, chunks[index]))
        for name, target, members in plan:
            print(f'Writing {target.name} ({len(members)} files)', flush=True)
            with tarfile.open(target, 'w' if args.no_compress else 'w:gz') as out:
                out.add(root, arcname=name, recursive=False, filter=strip_owner)
                for path in members:
                    # Drop the original top-level folder; nest under the new archive name.
                    relative = path.relative_to(root).parts[1:] or (path.name,)
                    out.add(path, arcname=str(Path(name, *relative)), filter=strip_owner)
    print('\nMD5 checksums (for MD5SUMS.txt):')
    for name, target, _ in plan:
        print(f'{md5(target)}  {target.name}')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.', file=sys.stderr)
        sys.exit(130)
    except (RuntimeError, OSError, tarfile.TarError) as exc:
        print('\nERROR:', exc, file=sys.stderr)
        sys.exit(1)
