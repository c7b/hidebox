#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The film (16-drive-design §10, the judge script; fifth pass): the drive on two devices, desktop left and
phone right, one short caption per shot in the platform sans, no voice, no music, about 60 to 90 s.
Python stdlib here; Chromium and ffmpeg run on the server.

  python3 -I tools/film.py [--origin URL] [--host hidebox] [--out film]
  python3 -I tools/film.py --demo        the pipeline alone, on the pages live now (no chain, no drive)

1. Two browser contexts on the server through the E2E harness (tests/e2e/): a 1440×900 desktop and a
   390×844 phone with touch and 4× CPU throttle, each recorded with CDP Page.startScreencast. Both hold a
   judge pass, as E-J does (the network limits on new drives and test money).
2. The story is /judges, both tracks, on the real site. Track one: Make my drive; a folder dropped
   (Locking, Uploading, Private); one file shared Once with Delete it from my drive after; the phone
   opens it and reloads to "This link has ended."; Activity (Opened, It left your drive); What our
   server knows. Track two: the folder shared to Someone who pays you; the phone scans the pay link,
   pays with test money, opens a photo; Received → Payments shows it, Test money and Checked; What the
   chain sees. Each shot is marked with the page clock; waiting between shots is cut, and each shot's
   real time is retimed to its slot in the film.
3. On the server, as build, Debian's ffmpeg places the two tracks on the dark ground, burns in the
   captions with the platform sans (Noto Sans Bold) and ends on the brand card (the symbol, the name and
   the drive's line): 1920×1080, 30 fps, H.264, +faststart, no audio track, at most 25 MB.
Writes <out>/film.mp4 and <out>/poster.png. Re-rendering is this one command. Take the film's drive down
by id afterwards (its pay link is ended here).
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
import scenarios_drive as drv  # noqa: E402
from scenarios_chain import PAY_LINK, open_paid_folder, pay_page, pay_wait, seller_ready, tx_view  # noqa: E402

FPS = 30
WORK = "/home/build/work/deploy/film"
FONT = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"              # the platform sans
NIGHT, MOON, MOON_DIM = "0x0A0A0A", "0xFAFAFA", "0xA3A3A3"            # web/shared/ui/tokens.css, dark
DESK_BOX, PHONE_BOX = (95, 70, 1280, 800), (1455, 70, 370, 800)       # x, y, width, height on 1920×1080
END_CARD_S = 3
MAX_BYTES = 25 * 1024 * 1024
LENGTH = (60, 90)                                                      # seconds, the story (not --demo)
BRAND = "hidebox"                                                      # web/app/lib/i18n.js BRAND

# The captions: the deck's words and the UI's own labels; privacy sentences only from the claim registry.
MAKE = "It lives in this browser. No email, no password."              # C17-k
DROP = "Files lock in this browser before upload."                     # C32
SHARE = "After that, it leaves your drive. We write that on the Tari chain."   # C42 (share result)
ONCE = "It opens one time. When you open it, the link ends."           # C26
ACTIVITY = "We count opens per hour. We never store who opened it or their IP address."   # C40
KNOWN = "What our server knows."                                       # the sheet's title
SELL = "Share it with someone who pays you."                           # the share dialog's choice
SCAN = "The phone scans the pay link."
TEST = "Our demo wallet pays the owner for you, with test money."      # C33
OPENS = "It opens on the phone."
PAID = "Checked on the chain, not a wallet's word."                    # C11 short form
CHAIN_SEES = "The chain shows a payment with a hidden amount and a hidden owner. The fee is public."   # C36
TAGLINE = "Your private drive. Locked here. Shared your way."


def end_lines(cfg: dict) -> tuple:
    network = str(cfg.get("network", "esmeralda")).capitalize()
    mainnet = (cfg.get("ootle") or {}).get("mainnet_date", "")
    return ((BRAND, 72, MOON), (TAGLINE, 44, MOON),
            (f"{network} testnet: tTARI is test money, worth nothing. Ootle mainnet: {mainnet}.", 30, MOON_DIM))


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


def photo(t: T, base: str, name: str, spec: str) -> None:
    """A real JPEG for the film, made on the server by ffmpeg (a lavfi source, no files from outside)."""
    t.env.remote.as_build(f"cd {shlex.quote(base)} && ffmpeg -hide_banner -loglevel error -y -f lavfi -i {shlex.quote(spec)} "
                          f"-frames:v 1 -q:v 4 {shlex.quote(name)}")


def story(t: T, take: Take) -> None:
    desk, phone = take.desk, take.phone
    flows.home(desk, t.origin)
    flows.home(phone, t.origin)
    # Track one (16-drive-design §10): one computer, then the phone opens the link.
    with take.shot(MAKE, 5):
        take.hold(1.0)
        desk.click("home-make")
        desk.wait_for("drive-root", 120)
        desk.wait("document.querySelector('[data-testid=\"locker-root\"] .working') === null", 60)
        take.hold(1.5)
    base = drv.remote_tree(t, "secrets", {"letter.txt": b"Meet me at the old lighthouse at midnight. Bring the map.\n"})
    photo(t, base, "moon.jpg", "mandelbrot=s=1200x800:end_pts=40")
    photo(t, base, "lighthouse.jpg", "gradients=s=1200x800:c0=0x0A0A0A:c1=0x7008E7:n=2:seed=7")
    folder = f"{t.sid}-secrets"
    with take.shot(DROP, 7):
        desk.wait("!!document.querySelector('[data-testid=\"upload-dir-input\"]')", 30)
        desk.set_files("upload-dir-input", [base])
        desk.wait(f"[...document.querySelectorAll('[data-testid=\"folder-card\"]')].some((e) => e.dataset.name === {json.dumps(folder)})", 180)
        take.hold(2.0)
    with take.shot(SHARE, 8):
        drv.into(desk, folder)
        drv.wait_names(desk, ["letter.txt", "moon.jpg", "lighthouse.jpg"])
        take.hold(0.8)
        drv.row_menu(desk, "letter.txt", "share")
        desk.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
        take.hold(0.8)
        desk.click("share-next")
        desk.wait("document.getElementById('share-dialog')?.dataset.step === 'opens'", 10)
        desk.click("share-then-delete")
        take.hold(0.8)
        desk.click("share-make")
        desk.wait("document.getElementById('share-dialog')?.dataset.step === 'result'", 90)
        url = desk.value("share-link")
        take.hold(2.0)
    desk.key("Escape")
    with take.shot(ONCE, 8):
        t.check(flows.open_link(phone, url) == "opened", "the phone opens the file")
        take.hold(1.5)
        phone.reload()
        t.check(phone.wait_state("view-root", flows.VIEW_ASK, 60) == "burned", "the reload: This link has ended.")
        take.hold(2.0)
    desk.goto(t.origin + "/drive/activity")
    desk.wait("[...document.querySelectorAll('[data-event=\"left\"]')].some((x) => x.dataset.name === 'letter.txt')", 120)
    with take.shot(ACTIVITY, 7):
        take.hold(3.0)
    with take.shot(KNOWN, 5):
        desk.click("open-known")
        desk.wait_for("known-sheet", 15)
        take.hold(2.5)
    desk.key("Escape")
    # Track two: the folder for test money, the phone pays and opens a photo, the computer sees it.
    desk.goto(t.origin + "/drive")
    desk.wait_for("drive-root", 120)
    drv.wait_names(desk, [folder])
    with take.shot(SELL, 7):
        drv.row_menu(desk, folder, "share")
        desk.wait("document.getElementById('share-dialog')?.dataset.step === 'who' && !document.getElementById('share-dialog').hidden", 20)
        take.hold(0.8)
        desk.click("share-choice", "pay")
        take.hold(0.6)
        desk.click("share-next")
        desk.wait("document.getElementById('share-dialog')?.dataset.step === 'pay'", 10)
        take.hold(0.8)
        desk.click("pay-make")
        desk.wait("document.getElementById('share-dialog')?.dataset.step === 'result'", 180)
        desk.wait("!!document.querySelector('[data-testid=\"share-qr\"] svg')", 30)
        pay_url = desk.value("share-link")
        take.hold(2.5)
    sid = PAY_LINK.search(pay_url)[1]
    desk.key("Escape")
    seller_ready(t, sid)
    desk.goto(t.origin + "/drive/received")
    desk.wait_for("drive-root", 120)
    with take.shot(SCAN, 6):
        t.check(pay_page(phone, pay_url) == "wait", "the phone has the pay page")
        take.hold(2.5)
    with take.shot(TEST, 9):
        phone.click("pay-test")
        t.check(pay_wait(phone, ("open", "expired", "void", "error"), 420) == "open", "test money: Ready to open")
        take.hold(1.5)
    with take.shot(OPENS, 7):
        open_paid_folder(t, phone, ["moon.jpg", "lighthouse.jpg"], "moon.jpg")
        take.hold(2.0)
    desk.wait("(() => { const r = document.querySelector('[data-testid=\"sales-row\"]');"
              " return !!r && !!r.querySelector('[data-testid=\"sales-test\"]') && !!r.querySelector('[data-testid=\"sales-tx\"]'); })()", 420)
    with take.shot(PAID, 7):
        take.hold(3.0)
    tx = desk.attr("sales-tx", "href").rsplit("/", 1)[-1]
    with take.shot(CHAIN_SEES, 9):
        tx_view(t, desk, tx)
        take.hold(3.0)
    t.env.remote.admin("takedown", "share", "--", sid)              # ends the pay link and its claim
    t.note(f"film drive: folder {folder}, pay link {sid}")


def demo(t: T, take: Take) -> None:
    """The same pipeline on whatever is served now: no chain, no locker, nothing stored."""
    for page in (take.desk, take.phone):
        page.goto(t.origin + "/")
    with take.shot(TAGLINE, 4):
        take.hold(2)
    take.phone.goto(t.origin + "/how")
    take.desk.goto(t.origin + "/judges")
    with take.shot(DROP, 6):
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
        size = 44 if len(caption) <= 64 else max(30, int(44 * 64 / len(caption)))     # one line on 1920
        texts.append(drawtext(f"cap{i}.txt", size, MOON, "940", f"gte(t,{start:.3f})*lt(t,{stop:.3f})"))   # one caption at a time
    end_texts = []
    for i, (line, size, color) in enumerate(end):
        files[f"end{i}.txt"] = line
        end_texts.append(drawtext(f"end{i}.txt", size, color, str((480, 600, 690)[i] if i < 3 else 690 + 60 * (i - 2))))
    dx, dy, dw, dh = DESK_BOX
    px, py, pw, ph = PHONE_BOX
    graph = ";".join([
        f"color=c={NIGHT}:s=1920x1080:r={FPS}:d={total}[bg]",
        f"[0:v]scale={dw}:{dh},setsar=1[d]",
        f"[1:v]scale={pw}:{ph},setsar=1[p]",
        f"[bg][d]overlay={dx}:{dy}:shortest=1[a]",
        f"[a][p]overlay={px}:{py}:shortest=1," + ",".join(texts) + f",fps={FPS},format=yuv420p[film]",
        f"color=c={NIGHT}:s=1920x1080:r={FPS}:d={END_CARD_S}[ebg]",
        "[2:v]scale=160:-1[logo]",
        "[ebg][logo]overlay=(W-w)/2:280," + ",".join(end_texts) + f",fps={FPS},format=yuv420p[end]",
        "[film][end]concat=n=2:v=1:a=0[out]",
    ])
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-i", "desk.ffconcat", "-f", "concat", "-i", "phone.ffconcat",
               "-i", "logo.png", "-filter_complex", graph, "-map", "[out]",
               "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-movflags", "+faststart", "-an", "film.mp4"]
    logo = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-c:v", "librsvg", "-width", "320",
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
        # the symbol, light on the dark ground (its own light tile with a dark lock)
        logo = (ROOT / "web" / "shared" / "brand" / "symbol.svg").read_text().replace(".t{fill:#171717}", ".t{fill:#FAFAFA}") \
            .replace(".l{stroke:#FAFAFA}", ".l{stroke:#0A0A0A}")
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
    p.add_argument("--host", default="hidebox")
    p.add_argument("--out", type=Path, default=ROOT / "film")
    p.add_argument("--demo", action="store_true", help="only the pipeline, on whatever is served now")
    args = p.parse_args()
    env = Env(args.origin.rstrip("/"), Remote(args.host, Path(tempfile.mkdtemp(prefix="mutis-film-"))), args.out)
    env.stage()
    t = T(env, "Spooky")
    # Both contexts hold a judge pass, like E-J: new drives and test money are limited per network.
    judge = env.remote.admin("judge-pass", "new", "--uses", "6").strip() if not args.demo else None
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
