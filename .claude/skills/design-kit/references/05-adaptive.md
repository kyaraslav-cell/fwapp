# 05 — Adaptive: the phone in one hand is the design target

Not "responsive" as an afterthought. The phone at the waterside is the primary
case; the desktop view is the adaptation.

## Breakpoints

Three, and they are content breakpoints, not device names.

| | Width | The case |
|---|---|---|
| **base** | ≤ 480px | one hand, daylight, bad signal. **Design here first.** |
| **mid** | 481–900px | tablet, or a phone turned sideways to read the map |
| **wide** | > 900px | desk. Reviewing the notebook, not fishing. |

Write base styles unprefixed and add `min-width` queries upward. A design written
desktop-first and narrowed always leaks desktop density into the phone.

Use intrinsic layout — `flex-wrap`, `grid-template-columns: repeat(auto-fit,
minmax(…, 1fr))`, `clamp()` for type — so most of the app never needs a query at
all. Guidelines: flex and grid over JS measurement, always.

## The thumb zone

On a one-handed grip the thumb sweeps an arc from the bottom corner of the
holding side. The bottom third is comfortable; the top corners require a
regrip — which means putting down a rod.

- **Primary action: bottom third.** The running-session float already lives here.
- **Destructive action: never in the arc.** End session, delete a catch, remove a
  water — these go top, or behind a confirm.
- **Navigation: bottom**, if it is used mid-session.
- **Reference content: top.** Conditions, the day strip, the score band. Read,
  not touched.

## Touch targets

**48×48 CSS px minimum**, including the tappable padding — 44 is Apple's floor
and 48 is Google's; take the larger, because the real hand is cold and wet.

The running-session float is currently 44px. Take it to 48.

Spacing between adjacent targets ≥ 8px. Two 48px buttons flush against each other
are one 96px mistarget.

Also, from the guidelines and worth having:

```css
:root { touch-action: manipulation; }          /* kills the 300ms double-tap delay */
.sheet { overscroll-behavior: contain; }       /* drawer scroll does not chain to the page */
.app { padding-bottom: env(safe-area-inset-bottom); }   /* notches and home bars */
```

Set `-webkit-tap-highlight-color` deliberately rather than leaving the default
grey rectangle.

## The five flow screens

Standing rule 5 fixes the order. Each gets **one** primary action, in the thumb
zone, at 48px:

| Screen | The one action | Reference content |
|---|---|---|
| Home / places | open a water | favourites, water-type filter |
| Lake | open the map | day strip, conditions, catch baseline **with its `n`** |
| Map | pick a spot | heat overlay, zone bands **with confidence** |
| Session start | start | method, rod count |
| Catch logging | log the catch | species, weight, length, bait, photo |

Two rules that follow from `CLAUDE.md` rather than from layout:

- **A blank session must be as easy to record as a good one** (law 3). If ending
  with zero catches takes more taps than ending with five, the layout has a bug.
- **Conditions and the map stay reachable during an active session** (standing
  rule 10). They do not disappear behind a session UI.

## Motion budget

`transform` and `opacity` only, so no animation can force layout. Anything that
animates `width`, `height`, `top`, `left`, `margin` or `filter` is a bug — run
the installed `fixing-motion-performance` skill against it.

- in-app: short and small. A card that flies 40px reads as a website; this is an
  instrument.
- `/welcome`: may be richer. It is read once, on wifi.
- **`prefers-reduced-motion` means fewer and gentler, not zero.** Keep the opacity
  that carries comprehension; drop every position change.
- No autoplaying video in the app. No animation longer than ~500ms on a control.

## Content handling

- long water names, long species names, and three languages of everything —
  `min-width: 0` on flex children so truncation can happen at all
- every list has an empty state; never render broken UI for an empty array
- `width` and `height` on every `<img>`, or the layout jumps on slow signal
- `loading="lazy"` below the fold; `fetchpriority="high"` above it — and **never
  `decoding="async"` on the same element**, which `docs/17 §6` records as a
  shipped bug

## Checklist before phase 6

- [ ] designed at 390px first, widened afterwards
- [ ] each of the five screens has exactly one primary action, in the thumb zone
- [ ] every target ≥ 48px, ≥ 8px apart
- [ ] destructive actions out of the thumb arc
- [ ] `touch-action`, `overscroll-behavior`, safe-area insets set
- [ ] blank session is no harder to log than a good one
- [ ] conditions and map reachable during an active session
- [ ] motion is `transform`/`opacity` only, reduced-motion variant present
- [ ] no horizontal scroll at 320px
