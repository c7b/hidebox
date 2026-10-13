# SPDX-License-Identifier: MIT
"""Folders as a key tree (research 16-drive-architecture §2.1).

A folder is an `items` row with `kind = 'folder'` and no ciphertext. Every item inside one carries
`parent_id` and `parent_wrap` (its own file key wrapped under the folder's key), so one folder key opens
the whole subtree by walking down and nothing opens upward. The server sees the tree's shape (which
items share a folder, how deep, how many), never a name, a type or a real size.
"""
from . import quota

MAX_DEPTH = 16                    # folders inside folders, counting the drive's root as depth 0
MAX_CHILDREN = 1000               # items directly inside one folder
MAX_TREE = 1000                   # items one folder link returns (413 `too_many` beyond)
MAX_ITEMS = 10_000                # items (files and folders) in one drive
MAX_UPLOAD_FILES = 500            # files in one folder upload (checked by the browser)
ZIP_MAX_BYTES = 2 * quota.GiB     # "Download all" in the browser: store-only zip, no ZIP64
ZIP_MAX_BYTES_PHONE = 500 * quota.MiB
PARENT_WRAP_LEN = 60              # iv ‖ AES-GCM(childWrapKey, fk) with its tag
FOLDER_FLAGS = 0x0001             # header flags of a folder (chunk_count 0)


def config_block() -> dict:
    return {"max_depth": MAX_DEPTH, "max_children": MAX_CHILDREN, "max_tree": MAX_TREE, "max_items": MAX_ITEMS,
            "max_upload_files": MAX_UPLOAD_FILES, "zip_max_bytes": ZIP_MAX_BYTES,
            "zip_max_bytes_phone": ZIP_MAX_BYTES_PHONE}
