"""Freeze a CSS animation at fixed progress points and save the frames.

Animation cannot be judged from a normal screenshot, and it cannot be
judged by reading keyframes either - the fish pin was diving TAIL FIRST
for three rounds of "improvements" because nobody had actually looked at
it. This drives the animation with `animation-play-state: paused` and a
negative `animation-delay`, which pins it to an exact percentage, so the
frames can be tiled into a filmstrip and inspected.

Usage:  python tools/animation_filmstrip.py [duration_ms] [out_name]
        (needs the app running on 127.0.0.1:8090)
"""

import sys
from playwright.sync_api import sync_playwright

S = "/tmp/claude-0/-home-user-fwapp/0e8fc2b1-e35a-58de-80ef-5f56018b0462/scratchpad"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 700
OUT = sys.argv[2] if len(sys.argv) > 2 else "strip.png"
FRAMES = 10

HARNESS = """
<div id="stage" style="position:relative;width:900px;height:200px;background:#7fa9c9;overflow:hidden;">
  <div style="position:absolute;top:96px;left:0;right:0;height:104px;background:#4a7fa5;"></div>
</div>
"""

FISH = """
<svg viewBox="0 0 64 44" style="width:60px;height:44px;">
 <path d="M4 22 C16 4, 40 4, 50 22 C40 40, 16 40, 4 22 Z" fill="#6fb1e8"/>
 <path d="M50 22 L62 10 L58 22 L62 34 Z" fill="#4a93d6"/>
 <circle cx="17" cy="19" r="3" fill="#fff"/><circle cx="17" cy="19" r="1.4" fill="#22384d"/>
</svg>"""

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    pg = b.new_page(viewport={"width": 900, "height": 200})
    pg.goto("http://127.0.0.1:8090/", wait_until="domcontentloaded")
    pg.set_content(
        f'<link rel="stylesheet" href="http://127.0.0.1:8090/static/style.css">'
        f'<body style="margin:0">{HARNESS}</body>'
    )
    pg.wait_for_timeout(400)

    for i in range(FRAMES):
        progress = i / (FRAMES - 1)
        delay = -int(DURATION * progress)
        pg.evaluate(
            """([delay, fish, dur]) => {
              document.querySelectorAll('.pin-ghost').forEach(e => e.remove());
              const g = document.createElement('div');
              g.className = 'pin-ghost diving';
              g.innerHTML = fish;
              g.style.left = '450px'; g.style.top = '96px';
              g.style.animationDuration = dur + 'ms';
              g.style.animationDelay = delay + 'ms';
              g.style.animationPlayState = 'paused';
              document.getElementById('stage').appendChild(g);
            }""",
            [delay, FISH, DURATION],
        )
        pg.wait_for_timeout(60)
        pg.locator("#stage").screenshot(path=f"{S}/frame_{i}.png")
    b.close()
print("frames captured")
