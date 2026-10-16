# SPDX-License-Identifier: MIT
"""E-J exactly as tests/e2e/scenarios_chain.py has it, minus the judge pass: `mutis-admin judge-pass new`
answers nothing, so both devices go as a visitor without a pass (the task's one judge-pass drive is spent)."""
import harness

_admin = harness.Remote.admin


def admin(self, *args, **kw):
    if args and args[0] == "judge-pass":
        print("ej_nopass: judge-pass new skipped (no pass for this run)", flush=True)
        return ""
    return _admin(self, *args, **kw)


harness.Remote.admin = admin
