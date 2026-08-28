/* Waterline: the three motion behaviours of the Fishlog design.
 *
 * Design constraints this file is written against, in order of importance:
 *
 *   1. It must be impossible for this script to break the app. Every behaviour
 *      here is decoration over markup that already works. The whole file is
 *      wrapped so a throw cannot escape, and the reveal pass fails OPEN - if
 *      IntersectionObserver is missing or anything throws, content is shown,
 *      never left hidden. A design flourish that can hide the notebook is not
 *      a flourish, it is an outage.
 *
 *   2. It must not fight the main thread. The app is read on cheap phones on
 *      bad signal. Listeners are passive, the splash reuses one node instead of
 *      allocating per click, and nothing here reads layout during a scroll.
 *
 *   3. It must respect prefers-reduced-motion at the source, not just in CSS.
 *      Skipping the work entirely is cheaper than animating something the
 *      stylesheet will then refuse to show.
 *
 * A previous session's trap, worth restating here: deleting markup orphans the
 * JavaScript bound to it, and one throw kills every handler registered after
 * it. Each behaviour below is installed inside its own try/catch for exactly
 * that reason - a missing .waterline must not cost the page its reveals.
 */
(function () {
  "use strict";

  var reduced = false;
  try {
    reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {
    /* matchMedia is ancient and universal, but a throw here must not stop the
       rest of the file from installing. */
  }

  var line = document.querySelector(".waterline");

  /* ---------------------------------------------------------------- splash --
     One reused node. Creating an element per click and removing it on
     animationend allocates on every tap and leaves garbage behind if the
     animation never fires (a backgrounded tab, for one). */
  try {
    if (!reduced) {
      var splash = document.createElement("div");
      splash.className = "splash";
      splash.setAttribute("aria-hidden", "true");
      document.body.appendChild(splash);

      document.addEventListener(
        "pointerdown",
        function (ev) {
          // Only the primary button, and never on a text selection drag.
          if (ev.button !== 0) return;

          splash.classList.remove("is-live");
          splash.style.left = ev.clientX + "px";
          splash.style.top = ev.clientY + "px";
          // Force a reflow so restarting the animation actually restarts it.
          // Without this, two taps in quick succession show only the first.
          void splash.offsetWidth;
          splash.classList.add("is-live");

          if (line) {
            // The ripple runs from the horizontal position of the touch, so
            // the line answers where the finger actually landed.
            var rect = line.getBoundingClientRect();
            var x = ev.clientX - rect.left;
            if (x >= 0 && x <= rect.width) {
              line.style.setProperty("--ripple-x", x + "px");
              line.classList.remove("is-rippling");
              void line.offsetWidth;
              line.classList.add("is-rippling");
            }
          }
        },
        { passive: true }
      );
    }
  } catch (e) {}

  /* ------------------------------------------------------------- surfacing --
     Fails open: if anything goes wrong, everything is shown. The hidden state
     is applied by this script and only ever to elements it has an observer
     for, so content cannot be stranded invisible. */
  try {
    var targets = document.querySelectorAll(
      ".card, .place-card, .dash-tile, .catch-card, .intel-card, .candidate-card"
    );

    if (!targets.length) {
      /* nothing to do */
    } else if (reduced || typeof IntersectionObserver !== "function") {
      /* Leave every element in its resting, visible state. */
    } else {
      /* Anything already on screen when the script runs is NEVER hidden.
         Only what the angler has yet to scroll to gets the reveal.

         This was a real bug, caught by tools/design_sheet.py and not by any
         test: hiding every card and waiting for the observer left the top of
         the page blank, because content that is already visible has nothing
         to animate into. On a slow phone that blank is what the app looks
         like for as long as the script takes to arrive.

         The rule this encodes: a reveal may add motion to content arriving on
         screen, but it may never be the thing that decides whether content is
         on screen at all. */
      var fold = window.innerHeight || document.documentElement.clientHeight;
      var deferred = [];
      for (var t = 0; t < targets.length; t++) {
        if (targets[t].getBoundingClientRect().top < fold) continue;
        deferred.push(targets[t]);
      }
      targets = deferred;
    }

    if (targets.length && !reduced && typeof IntersectionObserver === "function") {
      var io = new IntersectionObserver(
        function (entries) {
          for (var i = 0; i < entries.length; i++) {
            if (!entries[i].isIntersecting) continue;
            var el = entries[i].target;
            // Stagger by position within the group, capped so a long list
            // never leaves the last card waiting on a visible delay.
            var delay = Math.min(Number(el.dataset.surfaceIndex || 0), 6) * 45;
            setTimeout(function (node) {
              return function () {
                node.classList.add("is-surfaced");
              };
            }(el), delay);
            io.unobserve(el);
          }
        },
        { rootMargin: "0px 0px -40px 0px", threshold: 0.01 }
      );

      for (var i = 0; i < targets.length; i++) {
        targets[i].dataset.surfaceIndex = String(i);
        targets[i].classList.add("js-reveal");
        io.observe(targets[i]);
      }

      /* The safety net. If an element is still hidden after two seconds -
         observer never fired, tab was backgrounded during load, anything -
         show it. Being late is acceptable; being invisible is not. */
      setTimeout(function () {
        for (var j = 0; j < targets.length; j++) {
          targets[j].classList.add("is-surfaced");
        }
      }, 2000);
    }
  } catch (e) {
    // Belt and braces: strip the hiding class off everything.
    try {
      var stuck = document.querySelectorAll(".js-reveal");
      for (var k = 0; k < stuck.length; k++) stuck[k].classList.add("is-surfaced");
    } catch (e2) {}
  }

  /* ------------------------------------------------------- loading + bite --
     HTMX drives most navigation in this app, so the waterline swells on
     htmx:beforeRequest and settles on htmx:afterRequest. Both events are
     guarded: the listeners are harmless if HTMX is not present. */
  try {
    if (line) {
      document.body.addEventListener("htmx:beforeRequest", function () {
        line.classList.add("is-loading");
      });
      var settle = function () {
        line.classList.remove("is-loading");
      };
      document.body.addEventListener("htmx:afterRequest", settle);
      document.body.addEventListener("htmx:responseError", settle);
      document.body.addEventListener("htmx:sendError", settle);

      // A full page navigation gets the same signal, so tapping a plain link
      // on a slow connection does not look like nothing happened.
      window.addEventListener("beforeunload", function () {
        line.classList.add("is-loading");
      });
    }
  } catch (e) {}

  /* The bite, on the control that starts a session. Fires on submit rather
     than on click so it plays exactly when the app has committed. */
  try {
    if (!reduced) {
      document.addEventListener("submit", function (ev) {
        var form = ev.target;
        if (!form || !form.querySelector) return;
        var btn = form.querySelector(".btn-primary");
        if (!btn) return;
        btn.classList.add("is-biting");
        setTimeout(function () {
          btn.classList.remove("is-biting");
        }, 500);
      }, true);
    }
  } catch (e) {}

  /* Pause the ambient layer when the tab is not being looked at. A CSS
     animation keeps running in a background tab, and this app spends its whole
     working life in a pocket beside a rod - an animation nobody can see is
     pure battery. The class drives animation-play-state; nothing here reads or
     writes layout. */
  try {
    var root = document.documentElement;
    var syncVisibility = function () {
      root.classList.toggle("is-hidden", document.visibilityState === "hidden");
    };
    document.addEventListener("visibilitychange", syncVisibility);
    syncVisibility();
  } catch (e) {}
})();
