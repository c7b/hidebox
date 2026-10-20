## Bytes on the wire per page (Chromium's encodedDataLength: headers and body as sent)

| Page | First visit before | after | Requests | Images at load before | after | Repeat visit before | after | Requests to the network before | after | After a release before | after |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `/ @1440` | 156,319 | 141,621 | 36 → 36 | 40,584 | 37,520 | 26,194 | 3,722 | 30 (28 × 304) | 3 (1 × 304) | 103,811 | 9,762 |
| `/how @1440` | 142,553 | 131,608 | 18 → 18 | 16,709 | 13,617 | 10,238 | 738 | 14 (14 × 304) | 1 (1 × 304) | 62,271 | 5,225 |
| `/made @1440` | 149,079 | 136,608 | 17 → 17 | 16,709 | 13,617 | 8,809 | 738 | 12 (12 × 304) | 1 (1 × 304) | 67,860 | 17,234 |
| `/judges @1440` | 136,332 | 126,355 | 17 → 17 | 16,709 | 13,617 | 9,523 | 738 | 13 (13 × 304) | 1 (1 × 304) | 56,050 | 4,969 |
| `/fine-print @1440` | 139,299 | 128,805 | 17 → 17 | 18,830 | 15,577 | 9,523 | 738 | 13 (13 × 304) | 1 (1 × 304) | 59,017 | 8,735 |
| `/this-page-does-not-exist @1440` | 140,186 | 127,483 | 17 → 17 | 24,117 | 21,039 | 15,594 | 2,995 | 12 (11 × 304) | 1 (0 × 304) | 52,496 | 2,995 |
| `/drive @1440` | 205,404 | 181,700 | 41 → 41 | 26,752 | 23,674 | 34,885 | 3,043 | 37 (36 × 304) | 2 (1 × 304) | 168,804 | 5,837 |
| `/ @390` | 158,890 | 144,178 | 35 → 35 | 43,155 | 40,077 | 26,194 | 3,722 | 30 (28 × 304) | 3 (1 × 304) | 103,811 | 9,762 |
| `/how @390` | 142,553 | 131,608 | 18 → 18 | 16,709 | 13,617 | 10,238 | 738 | 14 (14 × 304) | 1 (1 × 304) | 62,271 | 5,225 |
| `/made @390` | 149,079 | 136,608 | 17 → 17 | 16,709 | 13,617 | 8,809 | 738 | 12 (12 × 304) | 1 (1 × 304) | 67,860 | 17,234 |
| `/judges @390` | 136,332 | 126,355 | 17 → 17 | 16,709 | 13,617 | 9,523 | 738 | 13 (13 × 304) | 1 (1 × 304) | 56,050 | 4,969 |
| `/fine-print @390` | 139,299 | 128,805 | 17 → 17 | 18,830 | 15,577 | 9,523 | 738 | 13 (13 × 304) | 1 (1 × 304) | 59,017 | 8,735 |
| `/this-page-does-not-exist @390` | 150,063 | 137,360 | 17 → 17 | 33,994 | 30,916 | 15,594 | 2,995 | 12 (11 × 304) | 1 (0 × 304) | 52,496 | 2,995 |
| `/drive @390` | 221,807 | 198,103 | 41 → 41 | 43,155 | 40,077 | 34,885 | 3,043 | 37 (36 × 304) | 2 (1 × 304) | 168,804 | 5,837 |

## What a repeat visit still asks the network for (after)

- `/ @1440`: / (304), /api/v1/config (200), /api/v1/pow (403)
- `/how @1440`: /how (304)
- `/made @1440`: /made (304)
- `/judges @1440`: /judges (304)
- `/fine-print @1440`: /fine-print (304)
- `/this-page-does-not-exist @1440`: /this-page-does-not-exist (404)
- `/drive @1440`: /api/v1/config (200), /drive (304)
- `/ @390`: / (304), /api/v1/config (200), /api/v1/pow (403)
- `/how @390`: /how (304)
- `/made @390`: /made (304)
- `/judges @390`: /judges (304)
- `/fine-print @390`: /fine-print (304)
- `/this-page-does-not-exist @390`: /this-page-does-not-exist (404)
- `/drive @390`: /api/v1/config (200), /drive (304)

## Every image file the build serves, bytes (and the .br a browser gets for SVG)

| File | Before | After | After, br |
|---|--:|--:|--:|
| `apple-touch-icon.png` | 5,147 | 2,319 |  |
| `favicon-32.png` | 1,597 | 1,042 |  |
| `favicon.ico` | 5,142 | 3,889 |  |
| `favicon.svg` | 1,697 | 1,697 | 643 |
| `icon-192.png` | 7,072 | 4,276 |  |
| `icon-512.png` | 19,129 | 11,888 |  |
| `icon-maskable-512.png` | 10,572 | 4,722 |  |
| `og-s.png` | 48,468 | 24,901 |  |
| `og.png` | 142,970 | 141,178 |  |
| `shared/brand/favicon.svg` | 1,697 | 1,697 | 643 |
| `shared/brand/symbol.svg` | 1,687 | 1,687 | 634 |
| `shared/icons.svg` | 5,013 | 5,024 | 1,065 |
| `shared/ui/icons.svg` | 31,300 | 31,300 | 6,440 |
| `site/media/404/box-zero-480.avif` | 6,574 | 6,574 |  |
| `site/media/404/box-zero-480.webp` | 9,612 | 9,612 |  |
| `site/media/404/box-zero-720.avif` | 11,088 | 11,088 |  |
| `site/media/404/box-zero-720.webp` | 17,532 | 17,532 |  |
| `site/media/404/box-zero-960.avif` | 16,450 | 16,450 |  |
| `site/media/404/box-zero-960.webp` | 27,982 | 27,982 |  |
| `site/media/motion/hidebox-A-hero.mp4` | 403,555 | deleted |  |
| `site/media/motion/hidebox-A-hero.webm` | 2,375,563 | deleted |  |
| `site/media/motion/hidebox-A-hero_poster.png` | 238,804 | deleted |  |
| `site/media/motion/hidebox-B-sides.mp4` | 143,659 | deleted |  |
| `site/media/motion/hidebox-B-sides.webm` | 886,021 | deleted |  |
| `site/media/motion/hidebox-B-sides_poster.png` | 219,268 | deleted |  |
| `site/media/motion/hidebox-C-encrypt.mp4` | 314,639 | deleted |  |
| `site/media/motion/hidebox-C-encrypt.webm` | 2,564,279 | deleted |  |
| `site/media/motion/hidebox-C-encrypt_poster.png` | 232,188 | deleted |  |
| `site/media/motion/hidebox-D-pay.mp4` | 379,646 | deleted |  |
| `site/media/motion/hidebox-D-pay.webm` | 3,241,933 | deleted |  |
| `site/media/motion/hidebox-D-pay_poster.png` | 181,506 | deleted |  |
| `site/media/v3/different-1536.avif` | 34,113 | 34,113 |  |
| `site/media/v3/different-1536.webp` | 48,274 | 48,274 |  |
| `site/media/v3/different-640.avif` | 6,895 | 6,895 |  |
| `site/media/v3/different-640.webp` | 9,244 | 9,244 |  |
| `site/media/v3/different-960.avif` | 14,985 | 14,985 |  |
| `site/media/v3/different-960.webp` | 19,430 | 19,430 |  |
| `site/media/v3/gem-1024.avif` | 20,176 | 20,176 |  |
| `site/media/v3/gem-1024.webp` | 35,932 | 35,932 |  |
| `site/media/v3/gem-480.avif` | 6,975 | 6,975 |  |
| `site/media/v3/gem-480.webp` | 10,878 | 10,878 |  |
| `site/media/v3/gem-720.avif` | 12,145 | 12,145 |  |
| `site/media/v3/gem-720.webp` | 19,688 | 19,688 |  |
| `site/media/v3/hero-1024.avif` | 25,611 | 25,611 |  |
| `site/media/v3/hero-1024.webp` | 46,530 | 46,530 |  |
| `site/media/v3/hero-480.avif` | 9,209 | 9,209 |  |
| `site/media/v3/hero-480.webp` | 14,838 | 14,838 |  |
| `site/media/v3/hero-720.avif` | 15,311 | 15,311 |  |
| `site/media/v3/hero-720.webp` | 26,558 | 26,558 |  |
| `site/media/v3/who-1024.avif` | 18,514 | 18,514 |  |
| `site/media/v3/who-1024.webp` | 35,070 | 35,070 |  |
| `site/media/v3/who-480.avif` | 6,896 | 6,896 |  |
| `site/media/v3/who-480.webp` | 11,236 | 11,236 |  |
| `site/media/v3/who-720.avif` | 11,442 | 11,442 |  |
| `site/media/v3/who-720.webp` | 20,312 | 20,312 |  |
| **all** | **12,032,052** | **805,120** | |

## The pictures the browser took (after, scrolled through)

| Page | Picture | Shown (CSS px) | Device px needed | Candidate taken (w) | Its file |
|---|---|--:|--:|--:|--:|
| `/ @1440` | `/site/media/v3/hero-720.avif` | 515 | 515 | 720 | 15,311 |
| `/ @1440` | `/site/media/v3/different-640.avif` | 512 | 512 | 640 | 6,895 |
| `/ @1440` | `/site/media/v3/who-480.avif` | 433 | 433 | 480 | 6,896 |
| `/ @1440` | `/site/media/v3/gem-480.avif` | 465 | 465 | 480 | 6,975 |
| `/ @1440` | `/site/media/v3/hero-720.avif` | 360 | 360 | 720 | 15,311 |
| `/this-page-does-not-exist @1440` | `/site/media/404/box-zero-480.avif` | 480 | 480 | 480 | 6,574 |
| `/drive @1440` | `/site/media/v3/hero-480.avif` | 416 | 416 | 480 | 9,209 |
| `/ @390` | `/site/media/v3/hero-1024.avif` | 358 | 1074 | 1024 | 25,611 |
| `/ @390` | `/site/media/v3/different-1536.avif` | 358 | 1074 | 1536 | 34,113 |
| `/ @390` | `/site/media/v3/who-1024.avif` | 358 | 1074 | 1024 | 18,514 |
| `/ @390` | `/site/media/v3/gem-1024.avif` | 358 | 1074 | 1024 | 20,176 |
| `/ @390` | `/site/media/v3/hero-1024.avif` | 358 | 1074 | 1024 | 25,611 |
| `/this-page-does-not-exist @390` | `/site/media/404/box-zero-960.avif` | 358 | 1074 | 960 | 16,450 |
| `/drive @390` | `/site/media/v3/hero-1024.avif` | 358 | 1074 | 1024 | 25,611 |
