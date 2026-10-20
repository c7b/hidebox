<!-- SPDX-License-Identifier: MIT -->
# Upload safety 1: can an uploaded file run on the server? (2026-10-19)

The owner's question: *can someone upload a package or virus that the server's Linux interprets in some way and
starts modifying the kernel? If every file on the planet may be uploaded, how do we make sure none of it is
executable on the machine?*

## The answer

No. An upload reaches the server as bytes in an HTTP request body, and the server does exactly three things with
them: writes them to a file whose name it picked itself, hashes them, and later sends them back as a download. No
code path decodes, unpacks, sniffs, previews, scans or runs them, or hands them to another program, and a test now
keeps it that way. Linux never "interprets" a file on its own: something has to execute it, load it as code or
parse it, and here nothing does. On top of that, the files can't run even if something tried: they are `0600`
under `0700` directories on a mount with `noexec`, `nosuid` and `nodev` (the kernel refuses to execute them or map
them as code, even for root, even through the dynamic loader). Nothing a service can write is executable in its own
view either, and every service sees the system read-only, holds no capabilities (Caddy only the one to bind ports 80
and 443), can't gain privileges, sits behind a system-call filter and can't load kernel modules or change kernel
settings. A browser gets stored bytes only as an `application/octet-stream` attachment with
`nosniff` and a sandboxed policy, so they never become a page on hidebox.app. What remains is the ordinary risk of
any web server: a bug in the kernel, Caddy, Python or SQLite reachable through the request itself (not through
what is stored), which these sandboxes and the kernel settings make much harder to turn into control of the machine.

## Controls

| Control | What it stops | Where it is enforced | How it was verified |
|---|---|---|---|
| Stored bytes are opaque | parser and decompression exploits, "image library" bugs, anything that runs because it was opened | `server/mutis/storage.py` (pwrite, SHA-256, rename; nothing else), `handlers/uploads.py` | `server/tests/test_uploads_inert.py` (no decoder, launcher or `eval` in the API; the three readers pinned; an ELF, a script, a page, an SVG and archive headers stored and served byte for byte); §1 |
| The server names every file | path traversal, overwriting another file, a chosen extension | `Blobs._dir` (22-character id check), the router's parameter check | `test_input_safety`, `test_uploads_inert.test_the_client_names_nothing_on_disk` |
| `0600` files under `0700` directories, opened without following symlinks | other users reading, adding or swapping files; symlink tricks; an execute bit | `storage.py` (each level made `0700` whatever the umask; `O_NOFOLLOW`), `provision.sh`, `privilege-check.sh` | tests under umask 0; on the server 4,096 first-level directories `2700`, 0 stored files other than `0600` (`03-mount-after.txt`) |
| `noexec,nosuid,nodev` on `/srv/mutis/data` | the kernel running, mapping as code, honouring set-id or opening as a device anything stored there (database backups included) | `deploy/systemd/srv-mutis-data.mount`, enabled by `provision.sh`; every unit that uses the data has `RequiresMountsFor=` | a script, a program and the loader trick all refused as `mutis` and as root, a set-uid root copy too (`03-mount-after.txt`); the privilege check |
| Nothing a service can write is executable (`NoExecPaths=` its private `/tmp`, `/var/tmp`, `/dev/shm` and every path it may write) | a compromised service running a file it dropped | every mutis unit, walletd, Caddy | each unit's exact sandbox probed in a throwaway unit: copies of `/usr/bin/true` refused in all three places (`02-sandbox-probes.txt`); the running API and Caddy checked by the privilege check (F4) |
| The systemd sandbox | privilege escalation, kernel modules and settings, raw devices, new namespaces, writable code | `deploy/systemd/*.service`, `caddy.service.d/mutis.conf` | `systemd-analyze security`: Caddy 8.8 "exposed" to 1.5, every mutis unit 0.5–1.4 (§2) |
| Downloads only | a stored file rendered as a page on this origin, MIME sniffing, framing | `handlers/blobs.py` (`application/octet-stream`, `attachment`), `api.py` (`nosniff`), the Caddyfile's API policy (`sandbox`), `X-Frame-Options`, Caddy can't read the data | D-01 (`test_headers.py`), `test_stored_bytes.py` in Chromium: opening stored bytes downloads them unchanged and commits no document |
| Size and body limits, a disk that never fills | filling the disk, huge bodies, slow-body holds | Caddy (5 MB body, the declared length checked first, buffered in memory), the API (64 KiB JSON, exact chunk length, per-class file sizes, lanes, quotas, daily brakes), freezes at a 10 GiB reserve, `posix_fallocate` before any byte | `test_uploads_inert.FullDisk`, `test_quota.test_freeze_thresholds`, D-01's 6 MB → 413, E-16 (§6) |
| Process separation | one service reaching another's data or wallet | users and modes, the loopback guards on 5100/8787/18143, walletd blind to `/srv/mutis` and mutis's secrets, `data/` itself `2750` | `test_privileges.py` 97/97 (was 46) |
| SSH keys only | password guessing, root logins | `sshd_config.d`, ufw `limit 22` | `sshd -T`; a password and a root attempt both "Permission denied (publickey)" (`04-ssh-after.txt`); the privilege check |
| Kernel settings | kernel address leaks, unprivileged BPF, ptrace of other processes, kexec, io_uring, line-discipline autoload, redirects and spoofed sources | `deploy/sysctl/90-mutis.conf`, applied by `provision.sh` with `systemd-sysctl` | the privilege check compares every setting with the kernel |
| Backups | a stored file living on in a copy | the backups hold the database only (never a blob), `0600`, on the `noexec` mount | restore drill PASS as `mutis` and as `drive`; 0 files with an execute bit, 0 blobs in any backup (`07-backups.txt`) |

## 1. The data path of an upload

1. **Caddy** terminates TLS, refuses a body declared over 5 MB with a 413 in the API's error shape, buffers the
   request body in memory (`buffer_requests`, 6 MB at most; the docs: "this uses more memory") and proxies to
   `127.0.0.1:8787`. Its roots are the release's `dist/` and `/srv/mutis/status`; it has no permission on
   `/srv/mutis/data`, and its own unit now sees that path read-only anyway.
2. **mutis-api** parses only its own small fields: JSON bodies up to 64 KiB (`json.loads`), base64url fields, the
   32-byte file header (`struct.unpack` of the `MTS1` signature, version, chunk size and count). `POST /uploads` checks
   size, layout, lane, quota and freeze, then reserves the whole size with `posix_fallocate` under a name made from
   `codec.new_id()` (16 random bytes). `PUT …/chunks/{index}` takes exactly the expected length, writes it with
   `pwrite` in 64 KiB slices and compares its SHA-256 with the client's. `…/complete` fsyncs and renames `.part` to
   `.bin`. No byte of a chunk is looked at.
3. **Every place that opens a stored object** (`test_uploads_inert` pins the readers):

   | Where | Opens | What it does with the bytes |
   |---|---|---|
   | `Blobs.create_part` | `<id>.part`, `O_CREAT\|O_EXCL\|O_NOFOLLOW`, `0600` | reserves the size; writes nothing |
   | `Blobs.write_at` | `<id>.part`, `O_WRONLY\|O_NOFOLLOW` | `pwrite`s the request body; SHA-256 of what it wrote |
   | `Blobs.finalize` | `<id>.part`, read-only | `fsync`, rename to `<id>.bin`, `fsync` of the directory |
   | `Blobs.read_range` ← `handlers/blobs.py` `ranged()` | `<id>.bin` | 64 KiB slices to the socket for `GET /blobs/{ticket}`, `/canary/raw` and `/s/{id}/stored`: `application/octet-stream`, `Content-Disposition: attachment` (`sealed.bin`, or `mutis-canary-<n>.bin`), `nosniff` |
   | `Blobs.read_all` ← `shares.py` open, `me.py` open | `<id>.bin` of at most 256 KiB | base64url into the JSON answer (`inline_ct`), decrypted in the browser |
   | `Blobs.exists`, `Blobs.unlink` ← cleanup, delete, takedown, abort | — | `stat`; `unlink` of `.bin` and `.part` |

   Nothing else opens them: the chain worker's unit can't write `blobs/` and its code never reads it; the backups
   copy the database only; health and evidence don't look; Caddy can't. `mutis-admin takedown` unlinks.
4. **Paths.** An item id matches `[A-Za-z0-9_-]{22}` and comes from the server's random bytes; `Blobs._dir` refuses
   anything else, and the router refuses a malformed id in a URL before the database is touched. The ids a client
   sends (upload, share, drop) only select database rows.
5. **Modes.** Files `0600` and directories `0700`, set explicitly, so the umask can't widen them (the API's is
   `0007` because the database is shared with `drive`). **Finding F1:** `mkdir(parents=True)` made the middle level
   `0777` minus the umask: 770 directories under `blobs/` were `2770`. Not reachable (`blobs/` itself is `0700`, so
   no other user could get to them: `drive` tried and got "Permission denied", `03-mounts-before.txt`), but wrong.
   Fixed in `storage.py` (live with the next deploy), on the server (those 770 set to `2700`, and all 4,096 possible
   first-level directories made `0700` beforehand, so the running release never makes one), and in `provision.sh`,
   which now normalises the tree; the privilege check fails on any group- or world-accessible entry.
6. **Serving.** Before: `application/octet-stream`, `attachment`, `nosniff` and the site's policy (`script-src 'self'`).
   After: every API answer carries `default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none';
   sandbox`, so even a stored file that a browser were tricked into opening as a document would get an opaque
   origin and run nothing. `test_stored_bytes.py`: in Chromium, opening `/api/v1/canary/raw` in a tab downloads it
   (`net::ERR_ABORTED`, the tab stays on `about:blank`), the copy has the same SHA-256 as the bytes fetched
   directly, `/made`'s "Download the stored bytes" link still downloads, and a page of the origin can't frame it.
7. **The only client bytes another program sees** are not stored files: a seller's sealed view key (a short field)
   and delivery memos from the chain go to the Node verifier sidecar, which opens them with the pinned
   `ootle-wasm` under Node's permission model, inside mutis-chain's sandbox.

## 2. The systemd sandbox

`systemd-analyze security` on the server (`02-systemd-analyze-before.txt`, `-after.txt`; `--offline` on the repo's
units gives the same numbers):

| Unit | Before | After | Added |
|---|---|---|---|
| caddy | 8.8 exposed | 1.5 | everything below, with `CapabilityBoundingSet=CAP_NET_BIND_SERVICE`, `ReadWritePaths=/var/lib/caddy`, `MemoryDenyWriteExecute`, `UMask=0027` |
| mutis-api | 1.5 | 1.2 | `ReadWritePaths` narrowed to `db/` and `blobs/`, `NoExecPaths` (below), `~@privileged @resources`, `RemoveIPC`, `RequiresMountsFor` |
| mutis-chain | 1.6 | 1.4 | `NoExecPaths`, `~@privileged @resources`, `RemoveIPC`, `RequiresMountsFor` |
| mutis-cleanup | 0.8 | 0.5 | as the API |
| mutis-backup | 1.1 | 0.5 | the clock, hostname, realtime and set-id rules it lacked; `ReadWritePaths` narrowed to `db/` and `backup/`; `NoExecPaths`; syscalls; `MemoryMax` |
| mutis-backup-wallet | 1.2 | 0.6 | the same four rules, `NoExecPaths`, syscalls, `MemoryMax` |
| mutis-evidence | 2.0 | 1.4 | the same four rules, `NoExecPaths`, syscalls, `MemoryMax` |
| mutis-health | 1.8 | 1.2 | the same four rules, `NoExecPaths`, syscalls, `MemoryMax` |
| walletd | 1.5 | 1.4 | `InaccessiblePaths=/srv/mutis` and mutis's secret, config and Caddy env (drive is in group `mutis`), `NoExecPaths` (its wallet directories too), `~@privileged`, `RemoveIPC` |

`NoExecPaths` names, in every unit, its private `/tmp`, `/var/tmp` and `/dev/shm` and each path it may write
(`ReadWritePaths`, `BindPaths`). **Finding F4** (from the independent review of this pass): the first version used
`NoExecPaths=/` with `ExecPaths=/usr`, meant as "programs only from `/usr`". On systemd 257 that left the private
`/tmp`, `/var/tmp` and `/dev/shm` executable (only the root mount got the flag) and lifted `ProtectSystem`'s
read-only flag from `/usr` (root in such a unit could write there); reproduced in throwaway units
(`02-sandbox-probes.txt`). Every place a service can write is now `noexec`, `/usr` stays read-only, and the deploy
tests check each unit line by line. Each unit's final sandbox ran as a throwaway unit with exactly its settings:
nothing writable without `noexec`, a program copied to `/tmp`, `/var/tmp` or `/dev/shm` refused, the chain worker's
sidecar answering `hello` with the pinned wasm, walletd's binary starting and seeing neither `/srv/mutis` nor the
secret.

Before Caddy's real restart, the same sandbox ran as a throwaway unit with a test config (`02-caddy-sandbox-test.txt`):
it served the release and proxied the API, with seccomp on, no new privileges, `CAP_NET_BIND_SERVICE` its only
capability and `/` `noexec`. Every oneshot unit was started by hand under each new definition and succeeded.

**Applied live, and how.** mutis-api, mutis-chain and walletd were restarted once each at 22:44 UTC with the first
version of the units, and Caddy at 22:46 UTC (by `provision.sh`). The owner's instruction not to restart mutis-chain
(it holds the last day's canary keys in memory) and to restart walletd only if unavoidable reached this pass after
those restarts. The restart lost the key of one canary (n = 197, sealed 22:21 UTC, after the 22:15 deploy had already
restarted the worker), which will show as missed when it is a day old. After F4, the API and Caddy were restarted
again (23:24 UTC) with the final units; **mutis-chain and walletd keep the first version until their next start**
(the next deploy for the chain worker, the next restart or the reboot for walletd): seccomp, no capabilities, no new
privileges and a read-only, `noexec` root, but an executable private `/tmp`, `/var/tmp` and `/dev/shm` (no visitor
byte reaches either process's temporary space). Their final sandboxes were proven in throwaway units instead
(`02-sandbox-probes.txt`), and the privilege check names them as pending until they restart.
walletd's one restart was checked the way provision checks a move: balances before and after identical. For the next
four minutes walletd refused the chain worker's cached token (16 warnings, one every 15 s, until the worker renewed it
at its 240 s lifetime); no job failed. **Observation for the chain worker's owner:** `server/mutis/walletd.py` could
drop its token and ask again when walletd refuses it, so a walletd restart costs nothing. Nothing
was restarted after that instruction, and nothing in this pass will restart them again: no deploy was made (an
activation restarts mutis-chain).

**Not applied, and why:**

- `MemoryDenyWriteExecute` for mutis-chain (Node's JIT and WebAssembly) and walletd (it runs templates as
  WebAssembly): both need writable code. Caddy, every Python unit and the API have it.
- `PrivateUsers`: the database is shared through group `mutis` and the loopback guards match real uids; with no
  capabilities and no new privileges the user namespace would add little.
- `PrivateNetwork` and `IPAddressDeny` for the API, the chain worker, health, evidence, walletd and Caddy: each
  talks to the internet (the indexers, the public site, clients). The backups and cleanup have `PrivateNetwork`.
- `ProcSubset=pid` for Caddy: Go sizes its listen backlog from `/proc/sys/net/core/somaxconn`.
- `@resources` in walletd's filter: Tari's binary, whose allocator and runtime we don't control; a refusal would
  surface in the middle of a send. `~@privileged` is applied.
- `ProtectHome=tmpfs` for the chain worker, evidence and wallet backups (they keep `read-only` plus the paths they
  need): every home is `0700`, so it would add nothing.

## 3. Mounts

Before: `/srv/mutis/data` was part of `/` (`rw,relatime`); as `mutis`, a script and a copy of `/usr/bin/id` placed
there ran (`03-mounts-before.txt`). After: `srv-mutis-data.mount` binds the directory onto itself with `noexec`,
`nosuid` and `nodev` (`findmnt`: `rw,nosuid,nodev,noexec`); the same script, the program, the program through
`/lib64/ld-linux-x86-64.so.2`, the program as root and a set-uid root copy are all refused (`03-mount-after.txt`).
The units' `ReadWritePaths` still resolve (they bind inside the mount and keep its flags), and the database
backups live inside it (`data/backup`). The wallet's backups (`/home/drive/wallet/backup`) and root's copies
(`/var/backups/mutis`) never hold uploaded bytes; every file there is `0600` without an execute bit.

`/tmp` and `/dev/shm` are `tmpfs` with `nosuid,nodev` and `/var/tmp` is on `/`. None of them is on the upload path
(Caddy buffers in memory; the API writes straight into `blobs/`), and every service gets private ones, `noexec`
(F4). They stay executable for the host on purpose: dpkg's debconf step runs scripts from `/tmp`, and
the `build` user's headless Chromium (the end-to-end tests) uses `/dev/shm`. `build` works in `/home/build` and
`/var/tmp/mutis-ui-run-*` (`0700`) and can read no data, key or wallet.

## 4. Users, sudo, SSH, firewall

- **Users** (`04-users-ssh-firewall.txt`): `mutis` (995, no login, no password) owns the data; `drive` (walletd, the
  chain worker, evidence, wallet backups; in group `mutis`); `build` (tests and compiling; no sudo, no data);
  `caddy`; the operator. Only `mutis` reaches `blobs/` and `backup/`; `build` and `caddy` reach nothing in `data/`.
  **Finding F2:** `data/` itself was group-writable, so `drive` could add or replace files beside the database
  (`health.json`, for one). Now `2750`; `drive` keeps `db/` (`2770`), which the chain worker needs.
- **sudo:** the operator has passwordless sudo (the autonomous builders use it); `mutis`, `drive`, `build` and
  `caddy` have none. The operator's SSH key is therefore the key to root; that is a choice for the owner (below).
- **SSH:** keys only, no root, `AllowUsers` the operator, no agent or X11 forwarding, local TCP forwarding only,
  three tries, ufw `limit 22/tcp`. **Finding F3:** cloud-init's `50-cloud-init.conf` said `PasswordAuthentication
  yes`; an earlier file won, so passwords were already refused, but deleting that file would have turned them on.
  It now says `no` (backup kept), and the privilege check fails if any SSH configuration file asks for passwords.
  A password attempt and a root attempt from outside: "Permission denied (publickey)" (`04-ssh-after.txt`).
- **Firewall:** ufw active, default deny in, 22 (limited), 80 and 443 open, logging off; the owner-match guards on
  loopback 5100 (walletd), 8787 (the API) and 18143 (the L1 wallet). From outside, 5100, 8787, 18143, 2019, 9000
  and 9100 are closed on IPv4 and IPv6. No fail2ban: SSH takes keys only and is rate-limited, and fail2ban would keep
  a list of visitors' addresses, which the logging rules (spec §14.3) don't allow.

## 5. Kernel and packages

- Kernel `6.12.111+deb13-amd64` runs; `6.12.113` is installed and `/var/run/reboot-required` exists. Not rebooted:
  a reboot restarts mutis-chain. **Owner:** reboot once the canary keys survive a restart (README "Reboot drill").
- `unattended-upgrades` is on for Debian and Debian-Security (last run today: nothing pending). `needrestart` isn't
  installed (provision installs no packages without the owner's approval); the same question asked of `/proc`
  found three processes on a replaced `libexpat`: polkit and unattended-upgrades were restarted, `dbus-daemon`
  waits for the reboot (`05-kernel-after.txt`).
- AppArmor is enabled with Debian's profiles; none confines Caddy, the API or walletd. **No profile was added.**
  `apparmor-utils` isn't installed, and complain mode logs every access a profile doesn't cover to the journal,
  which for the API means paths named by item ids: the "nothing about visitors in the logs" rule (D-02) forbids
  exactly that experiment on production. What a profile would add over this pass is limits on what the API may
  read; execution, writes, privileges and kernel interfaces are already closed by the sandbox and the mount. A
  later pass can build one against `mutis-api --dev` on the throwaway stack (`tests/e2e/localstack.py`).
- **Kernel settings** (`deploy/sysctl/90-mutis.conf`; the full previous `sysctl -a` is in
  `/var/backups/mutis/sysctl-all-before.20261019T224243Z.txt`): `kptr_restrict` 0 → 2, `unprivileged_bpf_disabled`
  2 → 1 (until reboot), `bpf_jit_harden` 0 → 2, `yama.ptrace_scope` 0 → 1, `kexec_load_disabled` 0 → 1,
  `dev.tty.ldisc_autoload` 1 → 0, `io_uring_disabled` 0 → 2, `protected_fifos` 1 → 2, `rp_filter` loose → strict on
  every interface, `send_redirects` and `secure_redirects` off; the Debian defaults that were already right
  (`dmesg_restrict`, `protected_*`, `suid_dumpable`, ASLR, `perf_event_paranoid`, syncookies, no source routing,
  no redirects accepted) are written down so a package can't relax them unnoticed. Left: `log_martians` (it would
  log source addresses), `kernel.modules_disabled` (ufw loads netfilter modules on demand), unprivileged user
  namespaces (Chromium's sandbox for `build` needs them; every service has `RestrictNamespaces`), `sysrq`.

## 6. Limits for "every file on the planet"

Caddy: 5 MB per request body, refused before it is read when declared larger (D-01: a 6 MB chunk gets the API's
413); 10 s for headers, 120 s for a body. The API: 64 KiB of JSON, 16 KiB of headers, a chunk of exactly its
expected length (4 MiB + 16 bytes, or the last one's), 32 requests in flight per /64; files of at most 25 MiB
without a drive, 64 MiB on a drive's first day, 512 MiB later, 2 GiB with a pack; lanes (1 GiB for small files,
2 GiB for drops, at most 6 GiB for large files without a drive), the adaptive drive quota (at most 5 GiB), daily upload bytes
per network (2 GiB), and per-network rate limits (`06-limits.txt`; production uses these defaults). The disk: free
drives and large files without a drive stop when free space falls under the reserve (10 GiB or 10 % of the disk,
whichever is larger) plus 2 GiB, everything stops at the reserve plus 256 MiB, and each upload reserves its full
size with `posix_fallocate` before a byte arrives. A disk that is full
anyway refuses the upload with 503 `uploads_frozen` and leaves no file or row behind; a write that fails mid-chunk
is a 500, the chunk doesn't count, and the API keeps answering (`test_uploads_inert.FullDisk`). Cleanup runs every
minute: expired links, doomed files, abandoned uploads after two hours. Today: 24 % of the disk used, uploads not
frozen.

## 7. Backups

`mutis-backup` (as `mutis`, daily) copies the database with SQLite's backup API into `data/backup/`, `0600`, and
deletes copies at 7 days; its first step (as root) prunes the database copies under `/var/backups/mutis` at the same
age. `mutis-backup-wallet` (as `drive`) copies walletd's database and the receiver and robot keys into
`/home/drive/wallet/backup/`, `0600`. Blobs are never backed up. A restore (`backup.py restore-drill`) copies the
newest backup into a private temporary directory, opens it with SQLite and checks its integrity: PASS for both
(`07-backups.txt`). What a restore brings back is a database file, `0600`, holding the encrypted fields a database
holds; no stored file, and nothing that could be executed.

## What changed on the server

Every replaced file was copied first to `/var/backups/mutis/<name>.<UTC time>` (root, `0700`):

| Change | Backup |
|---|---|
| `/etc/sysctl.d/90-mutis.conf` (new), applied | the previous values: `sysctl-all-before.20261019T224243Z.txt` |
| `/etc/systemd/system/srv-mutis-data.mount` (new), enabled and mounted | — |
| the 770 first-level directories under `blobs/` `2770` → `2700`; the other 3,326 made at `0700`; `data/` `2770` → `2750` | the modes before: `blobs-dir-modes.20261019T224243Z.txt` |
| `/etc/systemd/system/mutis-{api,chain,cleanup,backup,backup-wallet,evidence,health}.service`, `walletd.service` | `<unit>.20261019T224243Z` (the originals), `<unit>.20261019T232357Z` (the first version, before F4) |
| `/etc/systemd/system/caddy.service.d/mutis.conf` | `caddy.service.d-mutis.conf.20261019T224243Z` (and `.20261019T224617Z`, `.20261019T232357Z` by provision) |
| `/etc/caddy/Caddyfile` (the API's policy) | `Caddyfile.20261019T224243Z` (and `.20261019T224617Z` by provision) |
| `/etc/ssh/sshd_config.d/50-cloud-init.conf`: `PasswordAuthentication no` | `50-cloud-init.conf.20261019T224243Z` |
| restarts: mutis-api (twice), mutis-chain (once, before the owner's instruction), walletd (once, the same; balances identical), Caddy (twice), polkit, unattended-upgrades; `ssh` reloaded | balances: `balances-20261019T224419Z-{before,after}-hardening.json` |

`provision.sh` from this branch then ran three times: the first installed the drop-in and the Caddyfile and restarted
Caddy; the second changed nothing and its privilege check passed; the third installed the units after F4 (keeping
each previous file as `<unit>.20261019T232357Z`) and restarted Caddy for its drop-in (`08-provision-run1.txt` to
`-run3.txt`). After every
step: `systemctl is-active` for Caddy, the API, the chain worker and walletd, no failed timer unit, and
`tests/e2e/smoke.py --api --chain` PASS. Nothing needed a rollback.

**Pending the next deploy** (an activation restarts mutis-chain, so none was made): `storage.py`'s directory modes,
`O_NOFOLLOW` and descriptor handling; `activate-release.sh` keeping a copy of the Caddyfile it replaces and noticing a
changed mount unit or Caddy drop-in; mutis-chain's final sandbox. **Pending walletd's next start:** its final sandbox.
Live now: the mount, the blob tree's modes, the kernel settings, the Caddyfile, the SSH fix, and the final units of
Caddy, the API and every timer unit.

## What changed in the repository

- `server/mutis/storage.py`, `server/tests/test_uploads_inert.py` (§1, F1).
- `deploy/caddy/Caddyfile` (`api_csp`), `tests/e2e/headers_spec.py` (`API_CSP`), `tests/e2e/test_headers.py` (the
  stored bytes, the sandbox), `tests/e2e/test_stored_bytes.py` (new).
- `deploy/systemd/*` (§2), `deploy/systemd/srv-mutis-data.mount` (§3), `deploy/sysctl/90-mutis.conf` (§5).
- `deploy/scripts/provision.sh` (the mount, the kernel settings, `data/` `2750`, the blob tree's modes, a copy of
  every replaced file, Caddy restarted when its sandbox changes), `activate-release.sh`, `privilege-check.sh` (51
  new checks: the mount and the probes, the modes, each service's view, every kernel setting, SSH).
- `deploy/tests/test_config.py` (the units' hardening list, the mount, write access, Caddy's sandbox, the kernel
  settings, the API's policy).
- `docs/threat-model.md` ("Uploads are inert", one more adversary), `deploy/README.md`, `docs/self-host.md`,
  `CHANGELOG.md`, this review and its evidence.

## Deliberately left

- **Antivirus.** The server holds ciphertext: a scanner would see random bytes and find nothing, by design. To scan,
  the server would need the plaintext, which is the one thing it must never have. And a scanner is a large parser of
  hostile files running with broad access; its own bugs have been the way in. The person who opens a file is the
  one who can judge it; the app warns before programs.
- The operator's passwordless sudo, root's and the operator's account passwords (for the provider's console; SSH
  refuses them) and the one key in root's `authorized_keys` (unusable while root logins are off): the owner's.
- AppArmor, host-wide `noexec` on `/tmp` and `/dev/shm`, `kernel.modules_disabled`, fail2ban, needrestart: §3–§5.

## Residual risks, ranked

1. **The running kernel is two point releases behind** until the reboot (§5). Every other layer still applies.
2. **A bug in Caddy, the kernel's TCP/TLS stack, Python's HTTP server or SQLite reached through a request.** That is
   the attack surface of any web server; the sandboxes (nothing writable is executable, no privileges, seccomp, read-only
   system) limit what such a bug could then do.
3. **The operator's key is root** (passwordless sudo). A stolen workstation key is the shortest way in; a hardware
   key or a passphrase-protected agent would narrow it.
4. **walletd and the chain worker keep JIT** (writable code) because WebAssembly needs it; both run as `drive`,
   with no capabilities, and walletd can't see the visitors' data.
5. **A visitor's own device.** A file is as safe as its sender for the person who opens it.

## Suites

On the workstation: the server's suite (340 tests, 5 skipped) and the deploy suite (96), lint and the copy check;
on the server as `build` (Python 3.13) the same from a `git archive` of this branch; against the live site:
`test_headers.py` (D-01) PASS, `test_privileges.py` (D-03) 97/97, `test_stored_bytes.py` PASS, `smoke.py --api
--chain` PASS after every step, and the end-to-end suite once at the end. The results are in
`docs/evidence/2026-10-19/upload-safety-1/10-suites.txt`.

## Evidence

`docs/evidence/2026-10-19/upload-safety-1/`, each file the command and its output (names of the operator's
machines, login and addresses redacted):

| File | What |
|---|---|
| `01-data-path.txt` | the code: every caller of the blob store, the absence of decoders and launchers, the headers, the Caddyfile |
| `01-serving-before.txt`, `01-serving-after.txt` | the stored bytes' headers live, before and after; `test_stored_bytes.py` |
| `02-systemd-analyze-before.txt`, `-after.txt`, `02-units-after.txt`, `02-caddy-sandbox-test.txt` | §2 |
| `02-sandbox-probes.txt` | F4 reproduced, and each unit's final sandbox in a throwaway unit |
| `03-mounts-before.txt`, `03-mount-after.txt` | §3, F1 |
| `04-users-ssh-firewall.txt`, `04-ssh-after.txt` | §4 |
| `05-kernel-before.txt`, `05-kernel-after.txt` | §5 |
| `06-limits.txt` | §6 |
| `07-backups.txt` | §7 |
| `08-provision-run1.txt`, `-run2.txt`, `-run3.txt` | provision on the server |
| `09-test_privileges.txt`, `09-test_headers.txt` | D-03, D-01 |
| `10-e2e-full.txt`, `10-e2e-E-26-new-drive-limit.png`, `10-e2e-rerun.txt` | the end-to-end suite, the limit that stopped four scenarios, their rerun |
| `10-suites.txt` | every other suite, and the smoke test |
