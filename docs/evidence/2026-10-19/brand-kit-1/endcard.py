# SPDX-License-Identifier: MIT
"""The film's end card alone, as a still, to see it without recording the film (docs/review/brand-kit-1.md). On the
server as `build` (Debian's ffmpeg with librsvg, Noto Sans), from a copy of the repository:

  python3 -I docs/evidence/2026-10-19/brand-kit-1/endcard.py --out endcard.png

It asks tools/film.py for its own render script (one dummy shot), runs the script's two picture steps (the symbol and
the wordmark, through librsvg) and the end card's part of its filter graph, word for word, on two blank inputs in
place of the recordings. Python stdlib only.
"""
import argparse
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tests" / "e2e")]
import film  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    end = film.end_lines({"network": "esmeralda", "ootle": {"mainnet_date": "2026-11-11"}})
    script, files = film.render_script([film.Shot("A caption.", 1.0, 0.0, 1.0)], end)
    commands = [shlex.split(line) for line in script.splitlines()[1:] if line]
    pictures = [c for c in commands if "librsvg" in c]
    main_cmd = next(c for c in commands if "-filter_complex" in c)
    graph = main_cmd[main_cmd.index("-filter_complex") + 1].split(";")
    card = [part for part in graph if any(k in part for k in ("[ebg]", "[2:v]", "[3:v]", "[mark]"))]
    work = Path(tempfile.mkdtemp(prefix="mutis-endcard-"))
    try:
        for name, text in files.items():
            (work / name).write_text(text)
        (work / "logo.svg").write_text((ROOT / "web" / "shared" / "brand" / "symbol.svg").read_text())
        (work / "wordmark.svg").write_text(film.wordmark_svg())
        for c in pictures:
            subprocess.run(c, cwd=work, check=True)
        blank = ["-f", "lavfi", "-i", f"color=c={film.NIGHT}:s=1920x1080:d=1"]
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *blank, *blank, "-i", "logo.png", "-i", "wordmark.png",
                        "-filter_complex", ";".join(card), "-map", "[end]", "-frames:v", "1", "endcard.png"], cwd=work, check=True)
        shutil.copyfile(work / "endcard.png", args.out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"{args.out}: the end card ({len(card)} filters of the film's graph)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
