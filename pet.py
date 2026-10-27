#!/usr/bin/env python3
"""A pixel cat that lives in a small herdr pane and reacts to your agents.

  any agent blocked   -> stops, looks at you with a "!" bubble
  any agent working   -> runs back and forth (faster with more agents working)
  everyone idle       -> wanders, sits, blinks; falls asleep after a while
  no agents           -> sleeps

The bottom line shows agent counts and the cached subscription usage that
llm_usage.py keeps for the sidebar. Press q to close.

Commands:
  run    draw the cat in the current terminal (the herdr pane entrypoint)
  open   open the cat pane below the focused pane (herdr action)
"""

import json
import os
import random
import select
import shutil
import sys
import time

import llm_usage

FPS = 8
POLL_SECONDS = 1.5
SLEEP_AFTER = 90  # seconds of everyone idle before the cat dozes off
PANE_ROWS = 12  # terminal rows the pane shrinks itself to after opening

PALETTE = {
    "k": (120, 66, 40),    # outline
    "o": (245, 169, 98),   # fur
    "d": (214, 124, 58),   # stripes
    "w": (255, 244, 230),  # muzzle and belly
    "p": (244, 164, 184),  # ears and nose
    "e": (30, 30, 46),     # eyes
}

HEAD = [
    "..........k......k...",
    ".........kpk....kpk..",
    ".........kopkkkkpok..",
    "........koooooooooook",
    "........koo%oooo%oook",
    "........koo&oooo&oook",
    "........kowwwppwwwook",
    "........kowwwwwwwwok.",
    ".....kkkkkooowwooookk",
]
BODY = [
    "....kooddoodkkkkkkkk.",
    "...koooodoooodook....",
    "...kooooooooooook....",
    "....kwwwwwwwwwwk.....",
]
TAILS = {
    "up": ["..k.", ".kok", ".kok", ".kok", "..ko"],
    "wag": [".k..", "kok.", "kok.", ".kok", "..ko"],
}
LEGS = {
    "stand": ["....ko.ko....ko.ko...", "....kk.kk....kk.kk..."],
    "run1": ["...ko...ko..ko...ko..", "..kk...kk..kk...kk..."],
    "run2": [".....ko.ko....koko...", ".....kk.kk....kkkk..."],
    "tuck": [],
}
WIDTH = len(HEAD[0])
HEIGHT = len(HEAD) + len(BODY) + 2  # pixels; every pose is padded to this


def sprite(eyes="open", legs="stand", tail="up"):
    """Pixel rows for one pose, facing right, bottom-aligned to HEIGHT."""
    head = list(HEAD)
    if eyes == "closed":
        head[4] = head[4].replace("%", "o")
        head[5] = head[5].replace("&", "k")
    else:
        head[4] = head[4].replace("%", "e")
        head[5] = head[5].replace("&", "e")
    if eyes == "wide":
        head[3] = "........kooeooooeoook"
    rows = [list(r) for r in head + BODY]
    for i, line in enumerate(TAILS[tail]):
        for x, c in enumerate(line):
            if c != "." and rows[4 + i][x + 1] == ".":
                rows[4 + i][x + 1] = c
    rows = ["".join(r) for r in rows] + LEGS[legs]
    return ["." * WIDTH] * (HEIGHT - len(rows)) + rows


POSES = {
    "run1": sprite(legs="run1"),
    "run2": sprite(legs="run2"),
    "stand": sprite(),
    "wag": sprite(tail="wag"),
    "blink": sprite(eyes="closed"),
    "sleep": sprite(eyes="closed", legs="tuck"),
    "alert": sprite(eyes="wide", tail="wag"),
}


def render(pixels, flip):
    """Half-block truecolor lines: each text row shows two pixel rows."""
    if flip:
        pixels = [row[::-1] for row in pixels]
    lines = []
    for y in range(0, len(pixels), 2):
        top, bottom = pixels[y], pixels[y + 1] if y + 1 < len(pixels) else "." * WIDTH
        out = []
        for t, b in zip(top, bottom):
            tc, bc = PALETTE.get(t), PALETTE.get(b)
            if tc and bc:
                out.append("\033[38;2;%d;%d;%dm\033[48;2;%d;%d;%dm▀\033[0m" % (tc + bc))
            elif tc:
                out.append("\033[38;2;%d;%d;%dm▀\033[0m" % tc)
            elif bc:
                out.append("\033[38;2;%d;%d;%dm▄\033[0m" % bc)
            else:
                out.append(" ")
        lines.append(out)
    return lines


FRAMES = {name: (render(p, False), render(p, True)) for name, p in POSES.items()}
SPRITE_ROWS = len(FRAMES["stand"][0])


def agent_counts():
    listing = llm_usage.herdr("agent", "list")
    counts = {"working": 0, "blocked": 0, "idle": 0}
    try:
        agents = (json.loads(listing.stdout).get("result") or {}).get("agents") or []
    except ValueError:
        return None
    for agent in agents:
        status = agent.get("agent_status")
        if status in ("working", "blocked"):
            counts[status] += 1
        elif status in ("idle", "done"):
            counts["idle"] += 1
    return counts


def usage_summary():
    """Usage from the sidebar's cache; the cat never calls the providers itself."""
    data = llm_usage.read_json(llm_usage.state_dir() / "cache.json") or {}
    parts = []
    for provider in data.get("providers", []):
        windows = {w["label"]: w["used"] for w in provider.get("windows", [])}
        shown = ["%s %d%%" % (label, round(windows[label])) for label in ("5h", "week") if label in windows]
        if shown:
            parts.append("%s %s" % (provider["name"], " ".join(shown)))
    worst = max([w["used"] for p in data.get("providers", []) for w in p.get("windows", [])] or [0])
    return " · ".join(parts), worst


class Cat:
    def __init__(self):
        self.x = 0.0
        self.facing = 1
        self.mood = "idle"
        self.idle_since = time.time()
        self.wander_until = 0.0
        self.tick = 0

    def update(self, counts, width):
        self.tick += 1
        room = max(0, width - WIDTH)
        if counts is None or not any(counts.values()):
            mood = "sleep"
        elif counts["blocked"]:
            mood = "alert"
        elif counts["working"]:
            mood = "run"
        elif time.time() - self.idle_since > SLEEP_AFTER:
            mood = "sleep"
        else:
            mood = "idle"
        if mood != "idle" and mood != "sleep":
            self.idle_since = time.time()
        self.mood = mood

        if mood == "run":
            speed = 1.0 + 0.5 * min(counts["working"], 4)
            self.x += speed * self.facing
            if self.x <= 0 or self.x >= room:
                self.x = min(max(self.x, 0), room)
                self.facing *= -1
            return "run1" if self.tick % 2 else "run2"
        if mood == "idle":
            now = time.time()
            if now < self.wander_until:
                self.x += 0.5 * self.facing
                if self.x <= 0 or self.x >= room:
                    self.x = min(max(self.x, 0), room)
                    self.facing *= -1
                return "run1" if self.tick % 4 < 2 else "run2"
            if random.random() < 0.01:
                self.wander_until = now + random.uniform(1.5, 4)
                self.facing = random.choice((-1, 1))
            if self.tick % 37 in (0, 1):
                return "blink"
            return "wag" if (self.tick // 6) % 4 == 0 else "stand"
        if mood == "alert":
            return "alert"
        return "sleep"


def draw(cat, pose, counts, usage, worst, width, height):
    sprite_lines = FRAMES[pose][0 if cat.facing > 0 else 1]
    x = int(cat.x)
    bubble = ""
    if cat.mood == "alert":
        bubble = "\033[1;38;2;249;226;175m!\033[0m  someone needs you"
    elif cat.mood == "sleep":
        z = ("z", "z Z", "z Z z")[(cat.tick // FPS) % 3]
        bubble = "\033[38;2;180;190;254m%s\033[0m" % z
    elif worst >= 90:
        bubble = "\033[38;2;243;139;168mnearly out of usage…\033[0m"

    out = ["\033[H"]
    top_pad = max(0, height - SPRITE_ROWS - 3)
    for _ in range(max(0, top_pad - 1)):
        out.append("\033[K\n")
    if top_pad:
        bx = min(x + WIDTH - 4, max(0, width - 22)) if cat.facing > 0 else x
        out.append(" " * bx + bubble + "\033[K\n")
    for line in sprite_lines:
        out.append(" " * x + "".join(line) + "\033[K\n")
    out.append("\033[38;2;88;91;112m" + "▔" * width + "\033[0m\033[K\n")

    if counts is None:
        status = "herdr not reachable"
    else:
        status = "working %d · blocked %d · idle %d" % (counts["working"], counts["blocked"], counts["idle"])
    footer = status + ("   " + usage if usage else "")
    out.append("\033[2m" + footer[:width] + "\033[0m\033[K")
    out.append("\033[J")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def shrink_pane():
    """Bring a freshly split pane down to PANE_ROWS, whichever way resize moves the border."""
    pane = os.environ.get("HERDR_PANE_ID")
    if not pane:
        return
    direction = "down"
    for _ in range(8):
        rows = shutil.get_terminal_size().lines
        if rows <= PANE_ROWS + 1:
            return
        llm_usage.herdr("pane", "resize", "--pane", pane, "--direction", direction, "--amount", "0.1")
        time.sleep(0.25)
        if shutil.get_terminal_size().lines > rows:
            direction = "up"  # that grew the pane; the border moves the other way here


def cmd_run(_args):
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd) if os.isatty(fd) else None
    cat = Cat()
    counts, usage, worst = None, "", 0
    next_poll = 0.0
    try:
        if saved:
            tty.setcbreak(fd)
        sys.stdout.write("\033[?25l\033[2J")
        shrink_pane()
        while True:
            now = time.time()
            if now >= next_poll:
                counts = agent_counts()
                usage, worst = usage_summary()
                next_poll = now + POLL_SECONDS
            size = shutil.get_terminal_size()
            pose = cat.update(counts, size.columns)
            draw(cat, pose, counts, usage, worst, size.columns, size.lines)
            if not saved:
                time.sleep(1.0 / FPS)
                continue
            ready, _, _ = select.select([sys.stdin], [], [], 1.0 / FPS)
            if ready and os.read(fd, 1) in (b"q", b"Q", b"\x03"):
                return 0
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\033[0m\033[?25h\n")
        sys.stdout.flush()
        if saved:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def cmd_open(_args):
    plugin = os.environ.get("HERDR_PLUGIN_ID") or "llm-usage"
    opened = llm_usage.herdr("plugin", "pane", "open", "--plugin", plugin, "--entrypoint", "pet",
                             "--placement", "split", "--direction", "down", "--no-focus")
    if opened.returncode != 0:
        print(opened.stderr.strip(), file=sys.stderr)
    return opened.returncode


def main(argv):
    commands = {"run": cmd_run, "open": cmd_open}
    if not argv or argv[0] not in commands:
        print(__doc__.strip())
        return 2
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
