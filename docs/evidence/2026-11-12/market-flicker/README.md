<!-- SPDX-License-Identifier: MIT -->
# The market's flicker, before and after

The market (`/market`) and a public shop's page (`/shop/demo-shop`) changed their look while they opened. These are
the frames that show it, and the frames after the fix.

## How the frames were made

- A new incognito context of a desktop Chrome for each run, viewport 1280 × 800.
- A CDP screencast (`Page.startScreencast`, every frame) from the navigation to 3 s after the load event. Chrome sends
  a frame each time it paints something new, so each JPEG is one change on the screen.
- Each run loads the page twice: `fresh` (an empty cache) and `cached` (a reload).
- `frames.json` gives each frame's time in seconds since the epoch, the navigation's start (`start`), the first
  contentful paint and the load time.
- `sheet.jpg` puts a run's frames side by side, numbered in order.
- `trace-*.txt` gives one more fresh load: when each resource arrived, and when `<body>`, `<main>` and the
  stylesheets changed (ms after the navigation's start).

## Before (release `mvp-november-2026-11-12`)

`before/market/` (3 runs) and `before/shop/` (2 runs). Every load, fresh or cached, shows the same steps:

1. At about 0.6 s, the first frame: the server's text in the site's look (the site's header and footer), the listings
   as a bullet list.
2. At about 1.7 s, the app switches the page to the drive's look (`driveLook`): the drive's stylesheets load only
   now, the site's header and footer go, and a different top bar comes in.
3. The market then draws its own page with an empty list (about 0.1 s), and the list comes back from
   `GET /api/v1/market`.

The cause: `app/shop.html` started in the site's look, and the app ended every shop and market page in the drive's
look. The server's text also used other markup and other words than the app, and the market drew its page before
its listings came.

## After

See the next section, added after the deploy.
