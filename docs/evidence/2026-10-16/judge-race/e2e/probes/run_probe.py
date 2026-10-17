# SPDX-License-Identifier: MIT
import sys
sys.path.insert(0, "/home/lcam/mutis/tests/e2e")
sys.path.insert(0, "/home/lcam/.cache/mutis-tmp/probe")
import probe_jr  # noqa: F401
import probe_jr2  # noqa: F401
import probe_jr3  # noqa: F401
import probe_jr4  # noqa: F401
import run
sys.exit(run.main())
