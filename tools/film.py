#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The film (14-ghost-design §9 and §17 step 11): the judge script on two devices, desktop left and
phone right, one short caption per shot in the system sans, no voice, no music, about 60 to 90 s.
Python stdlib here; Chromium and ffmpeg run on the server.

  python3 -I tools/film.py [--origin URL] [--host ultron] [--out film]
  python3 -I tools/film.py --demo        the pipeline alone, on the pages live now (no chain, no locker)

1. Two browser contexts on the server through the E2E harness (tests/e2e/): a 1440×900 desktop and a
   390×844 phone with touch and 4× CPU throttle, each recorded with CDP Page.startScreencast. In direct
   mode both hold a judge pass, as E-J does, so the computer's wallet gets its sponsor grant.
2. The story is /judges, track one and then the Tari part, on the real site: the computer drops a
   file on the ghost; the phone opens the link and reloads to the gone page; the goodbye the release
   burned in advance (judge_demo_gone) is checked by the browser; the computer's locker shows its
   codes; the phone scans the address and sends a note by Tari; See what came opens it; See what a
   view key sees. Each shot is marked with the page clock; waiting between shots is cut, and each
   shot's real time is retimed to its slot in the film.
3. On the server, as build, Debian's ffmpeg places the two tracks on the night ground, burns in the
   captions with the platform sans (Noto Sans Bold; the Mutis Script fonts are gone) and ends on the
   wordmark card: 1920×1080, 30 fps, H.264, +faststart, no audio track, at most 25 MB.
Writes <out>/film.mp4 and <out>/poster.png. Re-rendering is this one command.
"""
import argparse
import bisect
import io
import json
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
FONT = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"              # the platform sans (DESIGN.md: system faces)
NIGHT, MOON, MOON_DIM = "0x13183A", "0xEEF0FF", "0xAEB4DC"            # web/shared/tokens.css, lights off
DESK_BOX, PHONE_BOX = (95, 70, 1280, 800), (1455, 70, 370, 800)       # x, y, width, height on 1920×1080
END_CARD_S = 3
MAX_BYTES = 25 * 1024 * 1024
LENGTH = (60, 90)                                                      # seconds, the story (not --demo)

# The captions: the deck's words (14-ghost-design §10.2), privacy sentences from the claim registry.
GIVE = "Give the ghost a secret."                                      # home
LINK = "You get a link. Your friend sees it once."                     # C26
GONE = "Then it's gone, and its goodbye goes on the Tari chain."       # C7-h
GOODBYE = "Its goodbye on the Tari chain, checked by your browser."    # C31
LOCKER = "It lives in this browser. No email, no password."             # C17-k, the locker's line
SEND = "It goes by Tari. Only they can open it."                       # C25
CAME = "See what came."
PEEK = "What came, and how much. No file sent to your locker opens with it."   # C15-k (C15 is on that screen)
TAGLINE = "Show it once. Then bye."


def end_lines(cfg: dict) -> tuple:
    network = str(cfg.get("network", "esmeralda")).capitalize()
    mainnet = (cfg.get("ootle") or {}).get("mainnet_date", "")
    return ((TAGLINE, 52, MOON), (f"{network} testnet: tTARI is test money, worth nothing. Ootle mainnet: {mainnet}.", 30, MOON_DIM))


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


def direct_mode(t: T) -> bool:
    cfg = t.env.config()
    return cfg.get("send_mode") == "direct" and bool((cfg.get("features") or {}).get("direct_send"))


def story(t: T, take: Take) -> None:
    desk, phone = take.desk, take.phone
    cfg = t.env.config()
    flows.home(desk, t.origin)
    flows.home(phone, t.origin)
    with take.shot(GIVE, 6):
        take.hold(1.5)
        desk.set_files("drop-input", [t.fixture("notes.txt")])
        desk.wait("!!document.querySelector('[data-testid=\"seal-progress\"], [data-testid=\"sealed-link\"]')", 30)
    with take.shot(LINK, 8):
        link = flows.wait_link(desk)
        desk.wait("!!document.querySelector('[data-testid=\"link-qr\"] svg')", 30)
        take.hold(1.0)
        t.check(flows.open_link(phone, link) == "opened", "the phone (the code's link) opens the file")
        take.hold(1.5)
    with take.shot(GONE, 7):
        phone.reload()
        t.check(phone.wait_state("view-root", flows.VIEW_ASK, 60) == "burned", "the reload: It's gone. It said bye.")
        take.hold(2.5)
    demo = cfg.get("judge_demo_gone")
    if demo and (cfg.get("features") or {}).get("seallog"):
        with take.shot(GOODBYE, 8):
            desk.goto(f"{t.origin}/s/{demo}")
            desk.wait("document.querySelector('[data-testid=\"gone-receipt\"]')?.dataset.receipt === 'done'", 60)
            take.hold(1.0)
            desk.click("gone-see")
            desk.wait("/included at checkpoint/.test(document.querySelector('.a-item--this [data-testid=\"verify-exit\"]')?.textContent || '')", 120)
            take.hold(2.0)
    # The Tari part: the locker on the computer, the phone carries things by its codes.
    make_drop_link(t, desk, "Film computer")
    if desk.exists("key-later"):
        desk.click("key-later")
    with take.shot(LOCKER, 6):
        desk.wait("!!document.querySelector('[data-testid=\"locker-qr\"] svg')", 30)
        _, address = locker_identity(desk)
        take.hold(2.5)
    phone.goto(f"{t.origin}/#to={address}")
    phone.wait("document.querySelector('#drop svg.ghost')?.dataset.state === 'courier'", 60)
    with take.shot(SEND, 9):
        take.hold(1.0)
        flows.lock_text(phone, "Stage door, nine o'clock.")
        phone.wait(f"document.querySelector('[data-testid=\"send-recipient\"]')?.value === {json.dumps(address)}", 180)
        take.hold(1.0)
        phone.click("send-submit")
        take.hold(1.5)
    t.check(phone.wait_state("send-status", ("delivered", "failed"), 420) == "delivered", "sent by Tari")
    with take.shot(SEND, 2):
        take.hold(1.5)
    desk.goto(t.origin + "/inbox")
    desk.wait("!!document.querySelector('[data-testid=\"inbox-item\"][data-source=\"send\"]')", 600)
    with take.shot(CAME, 7):
        t.check(open_inbox_item(t, desk, "send") == "opened", "See what came opens it")
        take.hold(2.0)
    desk.goto(t.origin + "/inbox")
    desk.wait_for("watch-mine", 60)
    with take.shot(PEEK, 8):
        desk.click("watch-mine")
        desk.wait("Number(document.querySelector('[data-testid=\"watch-summary\"]')?.dataset.deliveries || 0) >= 1", 600)
        take.hold(2.5)


def demo(t: T, take: Take) -> None:
    """The same pipeline on whatever is served now: no chain, no locker, nothing stored."""
    for page in (take.desk, take.phone):
        page.goto(t.origin + "/")
    with take.shot(GIVE, 4):
        take.hold(2)
    take.phone.goto(t.origin + "/how")
    take.desk.goto(t.origin + "/judges")
    with take.shot(LINK, 6):
        scroll_through(take, take.phone, "main", 4)


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


def render_script(shots: list[Shot], end: tuple = end_lines({})) -> tuple[str, dict[str, str]]:
    """The ffmpeg command (run on the server in WORK) and the small text files it reads."""
    files = {}
    total = sum(s.seconds for s in shots)
    texts = []
    for i, (caption, start, stop) in enumerate(captions(shots)):
        files[f"cap{i}.txt"] = caption
        texts.append(drawtext(f"cap{i}.txt", 44, MOON, "940", f"between(t,{start:.3f},{stop:.3f})"))
    end_texts = []
    for i, (line, size, color) in enumerate(end):
        files[f"end{i}.txt"] = line
        end_texts.append(drawtext(f"end{i}.txt", size, color, str(640 + 90 * i)))
    dx, dy, dw, dh = DESK_BOX
    px, py, pw, ph = PHONE_BOX
    graph = ";".join([
        f"color=c={NIGHT}:s=1920x1080:r={FPS}:d={total}[bg]",
        f"[0:v]scale={dw}:{dh},setsar=1[d]",
        f"[1:v]scale={pw}:{ph},setsar=1[p]",
        f"[bg][d]overlay={dx}:{dy}:shortest=1[a]",
        f"[a][p]overlay={px}:{py}:shortest=1," + ",".join(texts) + f",fps={FPS},format=yuv420p[film]",
        f"color=c={NIGHT}:s=1920x1080:r={FPS}:d={END_CARD_S}[ebg]",
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


def compose(remote: Remote, host: str, recordings: dict, shots: list[Shot], out: Path, end: tuple) -> dict:
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
        script, files = render_script(shots, end)
        for name, text in files.items():
            add(name, text.encode())
        add("render.sh", script.encode())
        logo = (ROOT / "web" / "shared" / "brand" / "logo.svg").read_text().replace('color="#151A3B"', 'color="#EEF0FF"')
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
    # Direct mode: a sponsor grant is two a day per network and the server's may be spent on tests, so
    # both contexts hold a judge pass, like E-J.
    judge = env.remote.admin("judge-pass", "new", "--uses", "3").strip() if not args.demo and direct_mode(t) else None
    with tempfile.TemporaryDirectory(prefix="mutis-frames-") as frames:
        try:
            take = Take(t.actor("desktop", judge_pass=judge), t.actor("iphone", judge_pass=judge), Path(frames))
            (demo if args.demo else story)(t, take)
            recordings = take.stop()
        finally:
            t.close()
        started = time.monotonic()
        result = compose(env.remote, args.host, recordings, take.shots, args.out, end_lines(env.config()))
    problems = [f"{result['bytes']} bytes > 25 MB"] if result["bytes"] > MAX_BYTES else []
    if not args.demo and not LENGTH[0] <= result["seconds"] <= LENGTH[1] + END_CARD_S:
        problems.append(f"{result['seconds']} s is outside {LENGTH[0]}–{LENGTH[1]} s")
    frames_seen = {name: len(rec.frames) for name, rec in recordings.items()}
    print(f"film: {args.out / 'film.mp4'} {result['seconds']} s, {result['bytes'] / 1e6:.1f} MB, frames {frames_seen}, "
          f"composed in {time.monotonic() - started:.0f} s" + "".join(f"\nFAIL {x}" for x in problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
