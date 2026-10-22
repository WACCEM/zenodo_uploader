# Zenodo uploader

A small command-line tool for putting a folder of (large) files into a **Zenodo draft**, for example a new version of an existing dataset. It works on Linux, macOS, Windows and HPC systems, needs no extra Python packages, and is built to survive the flaky connections that make browser uploads of multi-GB files fail.

What it does for every file in your folder, smallest first: compute the MD5, check what the draft already has, upload if needed, and verify size and MD5 against Zenodo. Files that are already correct are skipped, failed uploads are retried, and **rerunning the same command is always safe**.

What it never does: it **never publishes** the draft and never edits its metadata. It deletes a file in the draft only if you pass `--replace-mismatched`, and then only a file with the same name as one of your local files but a different size or MD5.

## Requirements

- Python 3.9 or newer (standard library only).
- `curl` (the upload itself is done by curl).

| System | Notes |
|---|---|
| Linux, macOS | Python 3 and curl are normally installed. Check with `python3 --version` and `curl --version`. |
| Windows 10/11 | `curl.exe` is included. Install Python from <https://www.python.org/downloads/> and use PowerShell (type `python` instead of `python3`) or Git Bash. |
| HPC / cluster | Load a Python module if `python3` is older than 3.9 (for example `module load python`). Run long uploads on a data-transfer node if your site has one. |

## Step 1: create a Zenodo personal access token

The token is a password that lets the script act on your Zenodo account. Create one with the minimum permission:

1. Log in to <https://zenodo.org>.
2. Open your account menu (top right) > **Applications** (direct link: <https://zenodo.org/account/settings/applications/>).
3. Under **Personal access tokens** click **New token**.
4. Give it a recognizable name, such as `Dataset upload`.
5. Tick only the scope **`deposit:write`**. It allows uploading files to your drafts but **not publishing** them (publishing needs `deposit:actions`; leave that unticked).
6. Click **Create** and copy the token right away. Zenodo shows it only once.

Keep the token private:

- Paste it only into the hidden prompt of a terminal (steps below). Do not paste it into chats, e-mails, scripts, notebooks or git repositories, and do not put it on a command line.
- When the upload is finished (or if the token leaks), delete it on the same Applications page. A new one takes a minute to create.
- Tokens belong to one account on one server: <https://sandbox.zenodo.org> (the test server) needs its own token, and the script talks to the real <https://zenodo.org> only.

## Step 2: create the draft on Zenodo

The script uploads into an existing, unpublished draft; it does not create one.

- **New version of a published dataset:** open the published record, click **New version**, remove the files you are replacing, fill in or keep the metadata, and press **Save draft**.
- **New dataset:** go to **Upload** > **New upload**, enter at least a title, and press **Save draft**.

The **draft ID** is the number at the end of the draft's address, for example `https://zenodo.org/uploads/12345678` -> `12345678`. Do not use the DOI of an older version.

## Step 3: run the upload

Replace the parts in `<angle brackets>`:

| Placeholder | What to put there | Example |
|---|---|---|
| `<uploader_folder>` | Folder that contains `zenodo_upload.py` | `~/zenodo_uploader` |
| `<path_to_data>` | Folder with the files to upload. All regular, non-hidden files **directly** inside are uploaded; sub-folders are ignored | `/scratch/me/my_dataset_zenodo` |
| `<draft_id>` | The draft ID from step 2 (the full draft URL also works) | `12345678` |

Limits per Zenodo record: 50 GB and 100 files by default (more on request to Zenodo support). A record cannot be split across several records, so check the size of `<path_to_data>` first.

### 3a. Get the script

```bash
git clone https://github.com/WACCEM/zenodo_uploader.git <uploader_folder>
```

(or download the repository as a zip from GitHub and unpack it). Then go there:

```bash
cd <uploader_folder>
```

### 3b. Short upload (a few files, about an hour or less)

Run the script. It asks for the token (hidden; paste it and press Enter), shows the draft title and version, and asks you to type the draft ID to confirm:

```bash
python3 zenodo_upload.py <path_to_data> --draft-id <draft_id>
```

On macOS you can keep the Mac awake with `caffeinate -dims python3 zenodo_upload.py ...`. On Windows PowerShell use `python` instead of `python3`, and set the power plan so the computer does not sleep. A wired connection is more reliable than Wi-Fi.

### 3c. Long upload that survives a disconnect (Linux, macOS, HPC)

Use `tmux` so the upload keeps running when your terminal or ssh session closes. Run these lines one at a time:

```bash
tmux new -s zenodo
```

Starts a persistent terminal session named `zenodo`.

```bash
read -rs ZENODO_TOKEN && export ZENODO_TOKEN && echo
```

Asks for the token without showing it: paste the token, press Enter. It lives only in this session's memory (the script hands it to curl through stdin, never on a command line).

```bash
cd <uploader_folder>
```

Goes to the folder with the script.

```bash
python3 zenodo_upload.py \
    <path_to_data> \
    --draft-id <draft_id> --replace-mismatched \
    2>&1 | tee -a $HOME/zenodo_upload_$(date +%Y%m%d).log
```

Starts the upload and writes everything to a log file in your home directory (`zenodo_upload_YYYYMMDD.log`) while still showing it on screen. Check the draft title and version it prints, then type the draft ID at the prompt.

Then **detach** with `Ctrl-b`, release both keys, press `d`. You can now close the terminal or log out; the upload continues.

To come back later (on the same machine; ssh to the same node if you used one):

```bash
tmux attach -t zenodo
```

To follow the log from anywhere, without attaching (curl's progress bar uses carriage returns, hence the `tr`):

```bash
tr '\r' '\n' < $HOME/zenodo_upload_*.log | tail -n 15
```

To see only the important lines:

```bash
grep -E "Verified on Zenodo|Upload verified|Upload failed|ERROR|All [0-9]+ files" $HOME/zenodo_upload_*.log
```

`--replace-mismatched` is included here so that a file you fixed locally is replaced in the draft on a rerun; drop it if you prefer the script to stop and tell you instead.

**Optional, HPC data-transfer nodes.** Many HPC centers ask that long transfers run on a dedicated transfer node instead of a login node. At NERSC, log in first with `ssh dtn01.nersc.gov`, run `hostname` and note the node name (a tmux session exists only on the node where it was started), then continue with `tmux new -s zenodo` above. Check your site's documentation for the equivalent.

**Without tmux (Windows, or a one-shot background run).** On Linux/macOS you can start the script fully detached; `--yes` skips the confirmation prompt, so check the first lines of the log (draft ID, title, version) right after starting:

```bash
read -rs ZENODO_TOKEN && export ZENODO_TOKEN && echo
nohup setsid python3 zenodo_upload.py <path_to_data> \
    --draft-id <draft_id> --replace-mismatched --yes \
    > $HOME/zenodo_upload_$(date +%Y%m%d_%H%M).log 2>&1 < /dev/null &
unset ZENODO_TOKEN
```

On Windows there is no tmux: run option 3b in PowerShell or Git Bash, leave the window open, and keep the computer awake.

### 3d. What you should see

For every file, in order of increasing size:

```text
Computing local MD5: <file>
Uploading <file>; attempt 1/8
Upload verified: <file>
```

A file that is already in the draft shows `Verified on Zenodo: <file>` and is skipped. At the end:

```text
All N files verified by size and MD5. Review and publish the draft in the Zenodo web UI.
```

If the run stops for any reason (network drop, `Ctrl-C`, a reboot), start the **same command again** (add `--yes` to skip the confirmation). Finished files are verified and skipped; only the unfinished one is repeated.

### 3e. After the upload

1. Open the draft on Zenodo and check the file list. Files listed by the script as "Additional files already in this draft" (for example files inherited from the previous version, or leftovers of failed attempts) are left alone; delete them in the web UI if you do not want them.
2. Complete the description and metadata, optionally use **Reserve DOI**, and **publish it yourself**. The script cannot publish.
3. If you edit a local file afterwards (a README with the final DOI, a checksum list), rerun the command with `--replace-mismatched --yes`. Only the files whose size or MD5 changed are deleted and uploaded again. To skip re-reading the large files, restrict the run with `--include 'README*'`.
4. Delete the token on the Applications page when you are done.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--include GLOB`, `--exclude GLOB` | all files | Filter file names; repeatable (quote the pattern, e.g. `--include '*.tar.gz'`). |
| `--retries N` | 8 | Upload attempts per file. Before each retry the script checks whether the file actually made it to Zenodo. |
| `--retry-wait SEC` | 60 | Base wait between attempts; it grows with each attempt (60 s, 120 s, ...) up to 600 s. |
| `--low-speed-time SEC` | 1800 | Abort an upload only if it stays below `--low-speed-limit` for this long. `0` turns the stall check off. There is no overall time limit, so a slow but moving upload is never killed. |
| `--low-speed-limit B/S` | 1 | The stall threshold in bytes per second. |
| `--limit-rate RATE` | none | Cap the upload speed (curl syntax, e.g. `5M`), useful if the upload saturates your link. |
| `--replace-mismatched` | off | Delete a same-named draft file whose size or MD5 differ from your local file, then upload it again. |
| `--yes` | off | Skip the "type the draft ID" confirmation (for reruns and background runs). |

## Large files: split the data before uploading

Zenodo's file API takes each file in one HTTP request. There is no resumable or chunked upload, so a failure at 90 % of a 7 GB file means starting that file over. In practice:

- `curl: (28) Operation too slow`: the connection stalled. The relaxed `--low-speed-time` default avoids most of these.
- `HTTP 502 Bad Gateway` partway through: Zenodo's proxy dropped the connection. This is outside your control and becomes more likely the longer a single request runs.

The most reliable remedy is **smaller, self-contained files**: each upload is short, a retry costs little, and users can download only the part they need. Aim for roughly 1-2 GB per file. Group files by a natural unit (a year range, a region, a variable) and pack each group into its own archive, for example:

```bash
tar -czf my_dataset_1998-2004.tar.gz my_dataset/1998 my_dataset/1999 ...    # or: zip -r archive.zip folder
md5sum *.tar.gz > MD5SUMS.txt                                               # macOS: md5 -r; Windows: certutil -hashfile
```

Do not cut a file into byte-level pieces; that confuses users. Put a short `README` and a checksum list next to the archives in the same folder; they are uploaded like any other file. If a dataset has hundreds of small files, bundle them: Zenodo allows only 100 files per record by default.

## Troubleshooting

- **`HTTP 401` / `403`**: the token is wrong, expired, deleted, or was created without `deposit:write`. Create a new one (step 1). A sandbox token does not work on zenodo.org.
- **`HTTP 502` / `503` / `504`**: temporary on Zenodo's side. The script waits and retries. If a file keeps failing, split it into smaller files (above), try at a quieter time (nights or weekends), add `--limit-rate`, or upload from a machine with a faster, more stable uplink (for example a data-transfer node on an HPC system, inside `tmux`).
- **`curl: (28)`**: a stall longer than `--low-speed-time`. Raise it or check the network.
- **`HTTP 429`**: Zenodo rate limit (about 100 requests per minute); the script waits and retries.
- **`Existing remote file differs or is incomplete`**: a file with that name is in the draft but does not match your local file (for example an interrupted earlier upload). Fix it with `--replace-mismatched`, or delete that single file in the draft's web UI.
- **`Additional files already in this draft`**: files in the draft that are not in your folder. They are left alone; remove them in the web UI if they are unwanted.
- **`This is not an unsubmitted draft`**: you passed the ID of a published record. Use the draft's ID (step 2).
- **`curl` or `python3` not found** (Windows): check `curl --version` and `python --version` in PowerShell; install Python from python.org and tick "Add python.exe to PATH".
- **Still stuck**: upload the stubborn file through the Zenodo web UI, or contact support@zenodo.org.
