# Zenodo uploader

Two small, dependency-free tools (Python 3.9+ standard library, plus `curl`) for putting a folder of large data files into a **Zenodo draft** (for example a new version of an existing dataset).

| Script | Purpose |
|---|---|
| `zenodo_upload.py` | Upload every file in a folder to an existing draft, verify size + MD5 against Zenodo, skip files that are already there, retry on failures. |
| `repack_archive.py` | Split one big `.tar.gz` of yearly/monthly files into several smaller archives by year range, before uploading. |

`zenodo_upload.py` **never publishes** the draft and never edits its metadata. It deletes a file in the draft only if you pass `--replace-mismatched`, and then only a same-named file whose size/MD5 differ from your local copy.

## Prerequisites

1. A Zenodo personal access token with the `deposit:write` scope (Zenodo > Account > Applications > Personal access tokens).
2. A saved **new-version draft**. On the published record click *New version*, fill in or keep the metadata, and press *Save draft*. The draft ID is the number at the end of its URL (`https://zenodo.org/uploads/23523604` -> `23523604`). Do not use the DOI of the old version.

## Quick start

```bash
caffeinate -dims python3 zenodo_upload.py /path/to/folder --draft-id 23523604
```

- `directory` (required) is the folder holding the files. All regular, non-hidden files directly inside it are uploaded; sub-folders are ignored. Use `--include '*.tar.gz'` / `--exclude 'notes*'` (repeatable) to narrow the list.
- `--draft-id` accepts the ID or the full draft URL.
- The token is read from a hidden prompt, or from the `ZENODO_TOKEN` environment variable (handy on a server; it is passed to `curl` through stdin, never on the command line).
- The script shows the draft title and version and asks you to type the draft ID to confirm (skip with `--yes` on reruns).
- Files are uploaded smallest first. For each file the script computes the local MD5, checks the draft, uploads if needed, and verifies the result against Zenodo's size and MD5.
- **Rerunning is safe.** Files that are already in the draft with a matching size and MD5 are skipped, so after any failure just run the same command again.
- When it finishes, check the draft in the Zenodo web UI and publish it yourself.

`caffeinate -dims` (macOS) keeps the Mac, its disk and the network awake during long uploads. Use a wired connection if you can.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--include GLOB`, `--exclude GLOB` | all files | Filter file names; repeatable. |
| `--retries N` | 8 | Upload attempts per file. Before each retry the script checks whether the file actually made it to Zenodo. |
| `--retry-wait SEC` | 60 | Base wait between attempts; it grows with each attempt (60 s, 120 s, ...) up to 600 s. |
| `--low-speed-time SEC` | 1800 | Abort an upload only if it stays below `--low-speed-limit` for this long. `0` turns the stall check off. There is no overall time limit, so a slow but moving upload is never killed. |
| `--low-speed-limit B/S` | 1 | The stall threshold in bytes per second. |
| `--limit-rate RATE` | none | Cap the upload speed (curl syntax, e.g. `5M`), useful if the upload saturates your link. |
| `--replace-mismatched` | off | Delete a same-named draft file whose size/MD5 do not match your local file, then upload it again. Use it after you change `01_README.md` or `MD5SUMS.txt` locally. |
| `--yes` | off | Skip the "type the draft ID" confirmation. |

## Large files: split the data *before* uploading

Zenodo's file API takes each file in one HTTP request. There is no resumable or chunked upload, so a failure at 90 % of a 7 GB file means starting that file over. Two kinds of failure showed up in practice:

- `curl: (28) Operation too slow`: the connection stalled. Fixed by the relaxed defaults above.
- `HTTP 502 Bad Gateway` partway through: Zenodo's proxy dropped the connection. This is outside your control and gets more likely the longer a single request runs.

The most reliable remedy is **smaller, self-contained archives**: each upload is short, a retry costs little, and users can download only the years they need. Do not cut a file into byte-level pieces; that makes the data confusing.

Zenodo allows 100 files and 50 GB per record, so loose per-month files (hundreds) are not an option, but blocks of years are. For a dataset with 28 yearly track files and 333 monthly files (1998-2025), 7-year blocks (1998-2004, 2005-2011, 2012-2018, 2019-2025) give about 1.8 GB per archive:

```bash
python3 repack_archive.py /path/to/global_mcs_pyflextrkr_tracks_v3_feng21.tar.gz /path/to/upload_folder --years-per-chunk 7
```

This writes `global_mcs_pyflextrkr_tracks_v3_feng21_1998-2004.tar.gz` and so on. Each archive holds a folder of the same name, and the script prints the MD5 line for each one. Notes:

- The year is the first 4-digit year (1900-2099) in each file name; the script stops with an error if a file has none.
- Use `--start-year` to fix the first block boundary and `--no-compress` for a plain `.tar` (NetCDF is usually already compressed, so gzip gains almost nothing for the monthly maps).
- It extracts the original into a temporary folder inside the output folder (so you need free space for the unpacked data) and never modifies the source archive. It refuses to overwrite existing outputs.
- After repacking, update your dataset's `README` (archive names, sizes, file counts) and `MD5SUMS.txt`, collect all the files to upload in one folder, and rerun `zenodo_upload.py` on it with `--replace-mismatched` (if the old README/MD5SUMS are already in the draft). Files that are already correct are skipped.

## Troubleshooting

- **`HTTP 502` / `503` / `504`**: temporary on Zenodo's side. The script waits and retries. If a file keeps failing, split it further (above), try at a quieter time (nights or weekends), add `--limit-rate`, or upload from a machine with a faster, more stable uplink (for example a data-transfer node on an HPC system, inside `tmux`, with the token in `ZENODO_TOKEN`).
- **`curl: (28)`**: a stall longer than `--low-speed-time`. Raise it or check the network.
- **`HTTP 429`**: Zenodo rate limit (about 100 requests per minute); the script waits and retries.
- **`Existing remote file differs or is incomplete`**: a file with that name is in the draft but does not match your local file. Fix it with `--replace-mismatched`, or delete that single file in the draft's web UI.
- **`Additional files already in this draft`**: files in the draft that are not in your folder (for example ones inherited from the previous version). They are left alone; remove them in the web UI if they are unwanted.
- **`This is not an unsubmitted draft`**: you passed the ID of a published record. Use the draft's ID.
- **Still stuck**: upload the stubborn file through the Zenodo web UI, or contact support@zenodo.org.
