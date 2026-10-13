<!-- SPDX-License-Identifier: MIT -->
# The drive: notes for the other lanes (lane app1)

What lane app1 (16-drive-design §15 steps 3, 5, 7, 9) built, and what the other lanes plug into.

## The page and its object

- `/drive*` is `app/drive.html` (Caddy `@drive`, `server/mutis/dev.py`), not `app.html`: its own
  stylesheets (`/shared/ui/tokens.css`, `components.css`, `/app/css/drive.css`) and no ghost.
- `ui/drive.js` makes one `Drive` object that every view gets: `cfg` (`/config`), `identity`
  (opened **lazily**: `identity.locker`, `wallet` and `safetyCode` are `null` until
  `withOotle(identity)` from `lib/identity.js` resolves; call it before anything Tari), `me`,
  `headers()`, `index` (`lib/drive.js` `DriveIndex`: every kept item opened with the vault key:
  `{id, folder, fk, salt, header, headerHash, metaKey, meta, name, parentId, row}`), `folders`
  (`cfg.features.folders`), `route`, `go(path)`, `render()`, `reload()`, `refreshMe()`.
- Row and folder menus call `act(drive, value, items, trigger)` (`ui/drive-list.js`). **Share…** and
  **Copy a once link** import `./share-dialog.js` (lane A2) and call
  `openShare(drive, item, {trigger})` and `copyOnceLink(drive, item, {trigger})`. A folder's page
  head has a Share button that calls the same `openShare`. After a link is made, `drive.reload()`
  then `drive.render()` shows its badge.
- `/drive/received` renders `ui/drive-received.js` (`render(drive, page)`): an interim page (the
  Tari address and a link to today's `/inbox`). Lane A2's Received replaces this file's content.
- Parts to reuse: `ui/drive-parts.js` (`ruleBadge`, `leavesBadge`, `badges`, `dialogBox`,
  `sheetBox`, `button`, `alert`, `errorAlert`, `safetyGrid`, `formatTari`, `shortAddress`) and
  `ui/behaviors.js` (`openModal`, `closeModal`, `toast`, `init`). The share dialog and Received CSS
  from the prototype's `app.css` are already in `css/drive.css`.

## Test ids (16-drive-design §12)

`drive-root` (the shell), `locker-root` (the page's `<main>`), `file-row`, `folder-card`,
`row-kebab`, `row-menu` with `menu-<value>`, `activity-feed`, `activity-sheet`, `known-sheet`,
`storage-meter`, `storage-pack`, `delete-after`, `quota-bar` (the rail's meter, `data-used` and
`data-limit`), `locker-address` (the empty drive's Tari row; Settings), `locker-qr` and
`locker-safety` (Settings), `export-view-key` and `view-key-value` (Settings), `key-save-file`,
`key-passphrase`, `key-saved-check`, `key-later` (Save my key), `restore-open`, `restore-file`,
`restore-text`, `restore-passphrase`, `restore-submit` (Open my drive), `drive-make`, `drive-open`,
`invoice-address`, `invoice-status`, `pay-step`, `demo-pay`, `pay-browser`, `pack-<id>` (Storage).

## What the client expects from the server lane (step 4 and 6)

The UI flows run against `server --dev` with `ui/tests/drivefake.py` in front of it, which fakes
exactly these shapes; it switches itself off once `/config` reports `features.folders`.

- `/config`: `features.folders`, `folders.max_upload_files`, `retention.trash_days`,
  `items.max_delete_after_days`.
- `GET /me/items?view=all` lists every kept item flat with `kind`, `parent_id`, `parent_wrap`,
  `trashed_at`; items under a trashed folder may be listed or not (the client hides an item whose
  folder it doesn't hold). `view=trash` lists trashed items; `view=gone` lists items that left with
  `meta_ct`, `header`, `owner_wrap`, `exit_hour` and, please, `exit` in the shape of
  `/s/{id}/exit` (`checkpoint.tx_id` once committed, or `proof.pending`); without it the client asks
  `/s/{id}/exit` of the item's first link, which only items that had a link have.
- `POST /folders`, `PATCH /items/{id}` with `parent_id`/`parent_wrap`, `meta_ct`, `trashed`,
  `expires_at` (null clears it), `POST /uploads` with `parent_id`/`parent_wrap`.
- Shares in `/me/items`: `opens` as `[[hour, n], …]` (step 6) is shown per hour when present;
  `ended_at` or `ended_hour` dates a link's end in Activity; `paid.claims[].paid_hour` lists payments.
