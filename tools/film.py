#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The film (11-brand §12.6, spec §18.5): about 40 s, desktop left, phone right, captions in Mutis
Script, no voice, no music. Python stdlib here; Chromium and ffmpeg run on the server.

  python3 -I tools/film.py [--origin URL] [--host ultron] [--out film]
  python3 -I tools/film.py --demo        the pipeline alone, on the pages live now (no app needed)

1. Two browser contexts on the server through the E2E harness (tests/e2e/): a 1440×900 desktop and a
   390×844 phone with touch and 4× CPU throttle, each recorded with CDP Page.startScreencast.
2. The story of 11-brand §12.6 runs on the real site. Each shot is marked with the page clock;
   waiting between shots is cut, and each shot's real time is retimed to its slot in the film.
3. On the server, as build, Debian's ffmpeg places the two tracks on the stage colour, burns in the
   captions with Courier Prime (Mutis Script is its renamed subset) and ends on the lockup card:
   1920×1080, 30 fps, H.264, +faststart, no audio track, at most 25 MB.
Writes <out>/film.mp4 and <out>/poster.png. Re-rendering is this one command.
"""
import argparse
import bisect
import io
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
import flows  # noqa: E402
from harness import Env, Remote, T  # noqa: E402
from scenarios import locker_identity, make_drop_link  # noqa: E402
from scenarios_chain import open_inbox_item  # noqa: E402

FPS = 30
WORK = "/home/build/work/deploy/film"
FONT = "/usr/share/fonts/opentype/courier-prime/Courier Prime.otf"
STAGE, STAGE_FG, STAGE_FG_2 = "0x0E0D0B", "0xEEE9DE", "0xA39C8F"       # web/shared/tokens.css
DESK_BOX, PHONE_BOX = (40, 70, 1280, 800), (1435, 70, 370, 800)       # x, y, width, height on 1920×1080
END_CARD_S = 3
MAX_BYTES = 25 * 1024 * 1024

# 11-brand §12.6
DROP = "(Drop a file.)"
NOISE = "(Left: your file. Right: what we store.)"
ONCE = "(It opens once.)"
LEAVES = "(Then it leaves. On the record.)"     # with SealLog on: every exit gets a receipt (C7)
LEAVES_UNRECORDED = "(Then it leaves.)"
SEND = "(Or send it to a Tari address. The key rides inside a stealth payment.)"
NEVER = "(We never see inside.)"
END_LINES = (("Every secret leaves on cue.", 52, STAGE_FG), ("Testnet · tTARI has no monetary value", 30, STAGE_FG_2))


@dataclass
class Shot:
    caption: str
    seconds: float
    start: float
    end: float


class Take:
    """The two recorded pages and the shots marked on them (both pages share the server's clock)."""

    def __init__(self, desk, phone, folder: Path):
        self.desk, self.phone = desk, phone
        self.recordings = {"desk": desk.record(folder / "desk", 1440, 900),
                           "phone": phone.record(folder / "phone", 780, 1688)}
        self.shots: list[Shot] = []

    @contextmanager
    def shot(self, caption: str, seconds: float):
        start = self.desk.clock()
        yield
        self.hold(0.3)
        self.shots.append(Shot(caption, seconds, start, self.desk.clock()))

    def hold(self, seconds: float) -> None:
        """Let the pages paint (frames keep arriving and are saved) without acting."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            self.desk.b.drain(min(left, 0.1))

    def stop(self) -> dict:
        return {name: page.stop_recording() for name, page in (("desk", self.desk), ("phone", self.phone))}


def story(t: T, take: Take) -> None:
    desk, phone = take.desk, take.phone
    make_drop_link(t, phone, "Film")                     # off camera: the phone gets a locker to send to
    if phone.exists("key-later"):
        phone.click("key-later")
    phone.goto(t.origin + "/locker")
    phone.wait_for("locker-address")
    _, address = locker_identity(phone)
    flows.home(desk, t.origin)
    flows.home(phone, t.origin)
    with take.shot(DROP, 5):
        desk.set_files("drop-input", [t.fixture("photo-gps.jpg")])
        desk.wait("!!document.querySelector('[data-testid=\"seal-progress\"]')", 30)
    with take.shot(NOISE, 5):
        link = flows.wait_link(desk)
        take.hold(1.5)
    with take.shot(ONCE, 7):
        desk.click("copy-link")
        t.check(flows.open_link(phone, link) == "opened", "the phone opens the photo")
        take.hold(1.0)
    with take.shot(LEAVES if (t.env.config().get("features") or {}).get("seallog") else LEAVES_UNRECORDED, 6):
        phone.reload()
        t.check(phone.wait_state("view-root", flows.VIEW_ASK, 60) == "burned", "the reload says it made its exit")
        take.hold(1.5)
    with take.shot(SEND, 5):
        desk.goto(t.origin + "/send")
        desk.wait_for("drop-input")
        flows.seal_text(desk, "Stage door, nine o'clock.")
        desk.fill("send-recipient", address)
        desk.wait_for("send-safety")
        desk.click("send-submit")
    t.check(desk.wait_state("send-status", ("delivered", "failed"), 420) == "delivered", "Delivered")
    with take.shot(SEND, 2):
        take.hold(1.5)
    phone.goto(t.origin + "/inbox")
    phone.wait("!!document.querySelector('[data-testid=\"inbox-item\"][data-source=\"send\"]')", 600)
    with take.shot(SEND, 3):
        t.check(open_inbox_item(t, phone, "send") == "opened", "the phone's inbox opens it")
        take.hold(1.0)
    flows.home(desk, t.origin)
    with take.shot(NEVER, 7):
        scroll_through(take, desk, "#exit-wall", 5)


def demo(t: T, take: Take) -> None:
    """The same pipeline on whatever is served now (the holding page needs no app)."""
    for page in (take.desk, take.phone):
        page.goto(t.origin + "/")
    with take.shot(DROP, 4):
        take.hold(2)
    with take.shot(NEVER, 6):
        scroll_through(take, take.phone, "#exit-wall", 4)


def scroll_through(take: Take, page, selector: str, seconds: float) -> None:
    """Scroll `selector` (or the page, if it isn't there) from its top to its bottom in small steps."""
    top, height = page.eval(f"(() => {{ const e = document.querySelector({selector!r}) || document.body;"
                            " const r = e.getBoundingClientRect(); return [r.top + scrollY, r.height]; })()")
    steps = int(seconds * 10)
    for i in range(steps + 1):
        page.eval(f"scrollTo(0, {top + height * i / steps})")
        take.hold(seconds / steps)


def frame_list(frames: list[tuple[float, str]], shots: list[Shot], folder: str) -> str:
    """An ffconcat list: for each output frame, the recorded frame on screen at the matching moment."""
    times = [ts for ts, _ in frames]
    names = []
    for shot in shots:
        n = round(shot.seconds * FPS)
        for k in range(n):
            moment = shot.start + (shot.end - shot.start) * k / n
            names.append(frames[max(bisect.bisect_right(times, moment) - 1, 0)][1])
    runs = []
    for name in names:
        if runs and runs[-1][0] == name:
            runs[-1][1] += 1
        else:
            runs.append([name, 1])
    lines = ["ffconcat version 1.0"]
    for name, count in runs:
        lines += [f"file {folder}/{name}", f"duration {count / FPS:.6f}"]
    lines.append(f"file {folder}/{runs[-1][0]}")       # the demuxer drops the last entry's duration
    return "\n".join(lines) + "\n"


def captions(shots: list[Shot]) -> list[tuple[str, float, float]]:
    out, at = [], 0.0
    for shot in shots:
        if out and out[-1][0] == shot.caption:
            out[-1] = (shot.caption, out[-1][1], at + shot.seconds)
        else:
            out.append((shot.caption, at, at + shot.seconds))
        at += shot.seconds
    return out


def drawtext(textfile: str, size: int, color: str, y: str, enable: str = "") -> str:
    return (f"drawtext=fontfile='{FONT}':textfile={textfile}:fontsize={size}:fontcolor={color}"
            f":x=(w-text_w)/2:y={y}" + (f":enable='{enable}'" if enable else ""))


def render_script(shots: list[Shot]) -> tuple[str, dict[str, str]]:
    """The ffmpeg command (run on the server in WORK) and the small text files it reads."""
    files = {}
    total = sum(s.seconds for s in shots)
    texts = []
    for i, (caption, start, end) in enumerate(captions(shots)):
        files[f"cap{i}.txt"] = caption
        texts.append(drawtext(f"cap{i}.txt", 44, STAGE_FG, "940", f"between(t,{start:.3f},{end:.3f})"))
    end_texts = []
    for i, (line, size, color) in enumerate(END_LINES):
        files[f"end{i}.txt"] = line
        end_texts.append(drawtext(f"end{i}.txt", size, color, str(640 + 90 * i)))
    dx, dy, dw, dh = DESK_BOX
    px, py, pw, ph = PHONE_BOX
    graph = ";".join([
        f"color=c={STAGE}:s=1920x1080:r={FPS}:d={total}[bg]",
        f"[0:v]scale={dw}:{dh},setsar=1[d]",
        f"[1:v]scale={pw}:{ph},setsar=1[p]",
        f"[bg][d]overlay={dx}:{dy}:shortest=1[a]",
        f"[a][p]overlay={px}:{py}:shortest=1," + ",".join(texts) + f",fps={FPS},format=yuv420p[film]",
        f"color=c={STAGE}:s=1920x1080:r={FPS}:d={END_CARD_S}[ebg]",
        "[2:v]scale=744:-1[logo]",
        "[ebg][logo]overlay=(W-w)/2:290," + ",".join(end_texts) + f",fps={FPS},format=yuv420p[end]",
        "[film][end]concat=n=2:v=1:a=0[out]",
    ])
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-i", "desk.ffconcat", "-f", "concat", "-i", "phone.ffconcat",
               "-i", "logo.png", "-filter_complex", graph, "-map", "[out]",
               "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-movflags", "+faststart", "-an", "film.mp4"]
    logo = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-c:v", "librsvg", "-width", "1488",
            "-i", "logo.svg", "logo.png"]
    poster = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{shots[0].seconds + 2:.2f}",
              "-i", "film.mp4", "-frames:v", "1", "poster.png"]
    script = "set -euo pipefail\n" + "\n".join(" ".join(shlex.quote(a) for a in c) for c in (logo, command, poster))
    return script + "\n", files


def compose(remote: Remote, host: str, recordings: dict, shots: list[Shot], out: Path) -> dict:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        def add(name: str, content: bytes) -> None:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        for name, rec in recordings.items():
            if not rec.frames:
                raise SystemExit(f"film: the {name} page sent no frames")
            tar.add(rec.folder, name)
            add(f"{name}.ffconcat", frame_list(rec.frames, shots, name).encode())
        script, files = render_script(shots)
        for name, text in files.items():
            add(name, text.encode())
        add("render.sh", script.encode())
        logo = (ROOT / "web" / "shared" / "brand" / "logo.svg").read_text().replace('color="#16130E"', 'color="#EEE9DE"')
        add("logo.svg", logo.encode())
    remote.as_build(f"rm -rf {WORK} && mkdir -p {WORK} && tar -x -C {WORK} && cd {WORK} && bash render.sh",
                    data.getvalue())
    out.mkdir(parents=True, exist_ok=True)
    for name in ("film.mp4", "poster.png"):
        got = subprocess.run(remote.prefix + [f"sudo -iu build cat {WORK}/{name}"], capture_output=True, check=True)
        (out / name).write_bytes(got.stdout)
    probe = remote.as_build(f"cd {WORK} && ffprobe -v error -show_entries format=duration -of csv=p=0 film.mp4 && "
                            f"cd /tmp && rm -rf {WORK}")
    return {"seconds": round(float(probe.strip()), 1), "bytes": (out / "film.mp4").stat().st_size}


def main() -> int:
    p = argparse.ArgumentParser(description="record and compose the film")
    p.add_argument("--origin", default="https://srv2052606.hstgr.cloud")
    p.add_argument("--host", default="ultron")
    p.add_argument("--out", type=Path, default=ROOT / "film")
    p.add_argument("--demo", action="store_true", help="only the pipeline, on whatever is served now")
    args = p.parse_args()
    env = Env(args.origin.rstrip("/"), Remote(args.host, Path(tempfile.mkdtemp(prefix="mutis-film-"))), args.out)
    env.stage()
    t = T(env, "FILM")
    with tempfile.TemporaryDirectory(prefix="mutis-frames-") as frames:
        try:
            take = Take(t.actor("desktop"), t.actor("iphone"), Path(frames))
            (demo if args.demo else story)(t, take)
            recordings = take.stop()
        finally:
            t.close()
        started = time.monotonic()
        result = compose(env.remote, args.host, recordings, take.shots, args.out)
    problems = [f"{result['bytes']} bytes > 25 MB"] if result["bytes"] > MAX_BYTES else []
    if not args.demo and not 30 <= result["seconds"] <= 45:
        problems.append(f"{result['seconds']} s is outside 30–45 s")
    frames_seen = {name: len(rec.frames) for name, rec in recordings.items()}
    print(f"film: {args.out / 'film.mp4'} {result['seconds']} s, {result['bytes'] / 1e6:.1f} MB, frames {frames_seen}, "
          f"composed in {time.monotonic() - started:.0f} s" + "".join(f"\nFAIL {x}" for x in problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
