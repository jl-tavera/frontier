# Frontier design system

Taken from https://frontier.lab10.ai/ on 2026-10-10 with agent-browser: the `:root` custom properties and stylesheet rules are copied exactly, and the component sizes come from computed styles at a 1440px viewport. Tokens you can drop into a page: [`tokens.css`](tokens.css).


## Principles

- **Dark terminal.** Near-black ground (`#0a0a0a`), off-white text, sections that alternate between `--fr-bg` and `--fr-surface` and are split by 1px `--fr-line` rules.
- **Square everything.** Border radius is 0 throughout. The only round things are small status dots.
- **Mono carries the voice.** Headings, labels, buttons, numbers and dates are set in Geist Mono, in uppercase written into the copy itself (no `text-transform`). Running prose is set in Geist.
- **Two accents, used sparingly.** Lavender `#a9a0ec` marks action and emphasis: the CTA, highlighted words, the glow and focus ring. Yellow `#f6f072` marks time and liveness: dates, the blinking cursor, single lit pixels.
- **Pixels as ornament.** A grid of dark squares with a few lavender or yellow ones lit, a dot-grid background, and the Doto pixel face for the wordmark and the closing headline.
- **Stepped motion.** Transitions use `steps(2,end)` over 0.1s, so states snap instead of fading. Cursors blink with `step-end`, hovered pixels flicker for 0.42s, and all of it is disabled under `prefers-reduced-motion`.

## Color

| Token | Value | Use |
|---|---|---|
| `--fr-bg` | `#0a0a0a` | page, header, odd sections, cards |
| `--fr-surface` | `#141414` | even sections, terminal body, card hover |
| `--fr-hover` | `#1c1c1c` | row/cell hover, terminal title bar |
| `--fr-dot` | `#1f1f1f` | dot-grid dots |
| `--fr-pixel` / `--fr-pixel-2` | `#2a2a2a` / `#3a3a3a` | unlit hero pixels |
| `--fr-line` | `#262626` | section dividers, card borders, list rules |
| `--fr-line-strong` | `#666` | ghost-button and toggle borders |
| `--fr-fg` | `#fafafa` | headings, primary text |
| `--fr-fg-muted` | `#a3a3a3` | body copy |
| `--fr-fg-subtle` | `#808080` | eyebrows, dates, meta |
| `--lab10-lavender` | `#a9a0ec` | primary CTA fill, highlight text, focus, glow, arrows |
| `--fr-lavender-deep` | `#1f1b3a` | background behind lavender text, active timeline row |
| `--lab10-yellow` | `#f6f072` | cursor, dates in chips, lit pixels, status dot |
| `--fr-yellow-deep` | `#26240a` | background of the date chip |
| `--fr-success` | `#3ecf8e` | terminal `✓` line |
| `--fr-warning` | `#ff9f43` | `[ ! ]` warnings |
| `--fr-danger` / `-soft` / `-deep` | `#ff5a5f` / `#ff8a8d` / `#2a0f10` | errors (not shown on the landing page) |

Lavender text always sits on `--fr-lavender-deep`, and dark text (`--fr-bg`) sits on a lavender fill.

## Typography

| Role | Family | Size / line height | Weight | Tracking |
|---|---|---|---|---|
| Display (hero h1) | Geist Mono | 64 / 72 | 500 | -0.03em (-1.92px) |
| Pixel display (closing CTA headline, wordmark) | Doto | ~80 | 900 | normal |
| Section h2 | Geist Mono | 48 / 52.8 | 500 | -0.02em (-0.96px) |
| Card / step h3 | Geist Mono | 20 / 28 | 500 | normal |
| Step number `01_` | Geist Mono | 48 | 500 | normal |
| Lead paragraph | Geist | 18 / 28 | 400 | normal |
| Body | Geist | 16 / 24 | 400 | normal |
| FAQ question | Geist | 18 / 28 | 500 | normal |
| Nav link | Geist | 14 / 21 | 400 | normal |
| Eyebrow / label / meta | Geist Mono | 12 / 18 | 500 | 0.08em |
| Button | Geist Mono | 12–13 | 500 | 0.08em |

Uppercase is used for headings, eyebrows, labels and buttons. Body copy and FAQ questions are in sentence case.

## Space and layout

- 4px base. The gaps that occur on the page are 4, 8, 12, 16, 24, 32, 48 and 80.
- Container: `max-width: 1200px`, centred, 120px side margin at 1440px. Text blocks are capped at 620–900px.
- Sections: `py-16` (64px) on mobile and `py-24` (96px) from `md` up. The hero is `min-height: calc(100svh - 72px)`.
- Common grids: two columns for heading-plus-content (h2 left, terminal/timeline/FAQ right), four columns for steps and benefit cards, and a five-column logo wall.
- Header: sticky, 72px tall plus a 1px bottom border, background `--fr-bg`.

## Borders and elevation

- 1px solid `--fr-line` everywhere. Buttons and toggles use `--fr-line-strong`.
- The only shadow is `--fr-glow` (a 1px lavender ring plus a 32px lavender haze), applied on hover to cards and CTAs.
- **Corner brackets:** 12px lavender L-shaped corners on cards (`.fr-corner`), hidden at rest and shown on hover. The closing CTA panel shows them permanently.

## Components

### Header
Wordmark `FRONTIER` in Doto, followed by a lavender block cursor and `BOG / 26` in subtle mono. On the right are the nav links (Geist 14), `ENTRAR` as a ghost button and `APLICAR →` as an outlined button.

### Buttons
| Variant | Style |
|---|---|
| Primary | 52px tall, `0 24px` padding, lavender fill and border, `--fr-bg` text, Geist Mono 13/500 at 0.08em, trailing `→`. Gets `--fr-glow` on hover. |
| Ghost | 44–52px tall, `0 18px` padding, transparent, 1px `--fr-line-strong`, `--fr-fg` text. Background goes to `--fr-hover` on hover. |
| Icon toggle | 36×36, 1px `--fr-line-strong`, lavender `+`/`−` (used by the FAQ). |

### Hero
A full-bleed grid of 16px `--fr-pixel` squares with random gaps and a few lit lavender or yellow pixels (`cursor: crosshair`). Above the headline sits a date line with a yellow dot. The centred h1 has one key phrase highlighted (lavender text on `--fr-lavender-deep`, `0 10px` padding) and ends in a blinking yellow block cursor. Below it: primary and ghost CTAs, a `POWERED BY Lab10` line, and a bottom meta bar of yellow dates and subtle cities.

### Section header
`01 / PARA QUIÉN ES` is the eyebrow (mono 12, subtle, 0.08em), followed by an uppercase mono h2 and a muted Geist lead paragraph capped near 680px.

### Bracketed statement
A centred `[ QUÉ ES FRONTIER ]` label, then a large paragraph where key phrases switch from muted to `--fr-fg` and lavender, then a mono command line (`$frontier apply --career=next-level`).

### Fit cards ([✓] / [✕])
Two bordered cards with 32px padding. The positive card uses a lavender `[✓]` label, `→` bullets and full-contrast text, and carries the glow plus corner brackets. The negative card uses a subtle `[✕]` label, `_` bullets and muted text.

### Terminal block
A title bar on `--fr-hover` holds three 10px squares (grey, yellow, grey) and the label `FRONTIER / RUN`. The body sits on `--fr-bg` with a 1px `--fr-line` border. The prompt `$` is lavender, the rows are `> label ..... value` with muted labels, dotted leaders and `--fr-fg` values, and the last line is a green `✓` with a blinking yellow cursor.

### Feature cells
Three or four columns separated by `--fr-line`, each with 32px padding, a mono eyebrow number, a mono h3 and muted body text. Hover changes the background to `--fr-hover`, reveals the corner brackets and makes the pixel flicker.

### Logo wall
Monochrome white logos in a five-column grid of borderless cells. A `SPONSOR OFICIAL` strip follows, then a text link styled `¿Tu empresa está contratando? Ver planes →` that turns lavender on hover.

### Steps
A 1px rule, then four columns. Each column has a mono 48px number `01` followed by a lavender underscore cursor (`.fr-us`, which blinks on hover), a mono h3 and muted body text.

### Benefit cards
Four bordered cards. Each has a 16px pixel square at the top left (yellow on the first, `--fr-pixel` on the rest) that turns lavender and flickers on hover, a mono h3 and muted body text.

### Timeline
Rows separated by `--fr-line`: a subtle mono date (`26 SEP`) in a 120px column and a Geist 18/500 label. The active row bleeds 16px past the column on `--fr-lavender-deep`, with the date in lavender and a yellow dot. A `[ ! ] …` warning in `--fr-warning` mono sits beside it.

### FAQ accordion
Rows have `20px 0` padding and are separated by `--fr-line`. Each row has a mono subtle index (`01`), a Geist 18/500 question and a 36px `+`/`−` toggle on the right. The open answer is indented to the question text and set in muted Geist 16.

### Closing CTA
The section uses the `.fr-grid-bg` dot grid. Inside it, a `--fr-surface` panel with permanent lavender corner brackets holds a yellow date chip (`--fr-yellow-deep` background, yellow mono text, dot), the Doto pixel headline, muted copy, a primary CTA plus `> cierre 04.10.26` in mono, and a small pixel-art cluster on the right. The footer below repeats the wordmark and `powered by Lab10`.

## Motion

| Rule | Value |
|---|---|
| State transitions | `.fr-step-transition`: background, color, box-shadow and border-color over 0.1s `steps(2,end)` |
| Cursor | `fr-blink` 1s `step-end` infinite |
| Hover flicker | `fr-flicker` 0.42s `step-end` on pixels and squares |
| Corner reveal | opacity over 0.12s `steps(2,end)` |
| Pulse | `fr-pulse` 1s `steps(2,end)` infinite (live dots) |
| Focus | 2px lavender outline, 2px offset |
| Reduced motion | all of the above `animation: none` |

## Do / don't

- **Do** keep every corner square, every border 1px, and the accents to small areas.
- **Do** put labels, numbers and dates in mono and prose in Geist.
- **Don't** use gradients (apart from the dot grid and the yellow hatch `.fr-reserva`), soft shadows, eased fades or rounded cards.
- **Don't** set lavender text directly on `--fr-bg` for large areas. Give it the `--fr-lavender-deep` plate.
