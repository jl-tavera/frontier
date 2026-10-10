# Screen perception — pixels → elements → UI tree (track 7)

> Appendix H of [solution.md](../solution.md) · Status: adopted as component [E] (solution.md §3.2, §5 Track 7) · Links checked 2026-10-10.

## 1. Summary

**Decision:** a hybrid, CPU-only pipeline.
- **OCR** (RapidOCR with a Latin model) gives exact text and boxes.
- **Classic CV** (OpenCV) gives widget boxes: fields, buttons, grid lines.
- **Heuristics** turn those into a **UI tree**: containment, grouping, label↔field pairing, grids.
- **The model** (the planner or the VLM, through OpenRouter) sees an element list, plus a Set-of-Mark image only when the screen is new, and answers with an **element id**, never x,y. On a mapped app it is not asked at all: the saved snapshot replays first (Spec W).
- **Raw coordinates from the VLM** are a last-resort fallback.

The whole pipeline is built around caching, because measurement (§6) shows that recognizing every line is the expensive part, not finding them.

---

## 2. Problem and constraints

```
framebuffer (numpy, 1280×800, lossless)
   → elements  [{id, text, bbox, kind, conf}]          kind: menu, button, field, label, link, cell, title
   → UI tree   (window → panels → forms/grids → widgets)
   → used by:  grounding (3.2) · fingerprint (2.3) · app map (2.4) · drift detection (2.6) · read_grid (4.2)
```

There's no DOM and no accessibility tree; the transport only gives us pixels ([Appendix C](C-transport-rfb.md)). Perception **rebuilds the accessibility tree a normal app would expose**. That's exactly the problem Apple's *Screen Recognition* paper solves for mobile apps.

**What makes our case easier than the papers:**
- Pixels are lossless (Raw encoding): no JPEG noise. Identical text renders to **identical pixels**, which makes caching exact.
- Fonts are fixed and the UI is flat, light-themed and web-styled, with standard widgets (see `poc/out/before.png`).
- Text is Spanish/Latin script, printed horizontally.

**What makes it harder:**
- The evaluation app is unseen, so there's no training or labels for it.
- The deploy is CPU-only (Railway).
- 5 minutes per task, and the UI changes at 15:30.

---

## 3. Options considered

### 3.1 OCR — text + box

| Engine | Pros | Cons | Verdict |
|---|---|---|---|
| **RapidOCR** (PaddleOCR PP-OCR models on ONNX Runtime) | PaddleOCR accuracy without the Paddle framework. Pip install, CPU-friendly. Separate det/rec stages we can call independently (§6). Measured: numbers, dates and codes read near-perfectly | Default model is Chinese+English, so it **drops accents** (Gómez → Gomez). Line-level boxes, not word-level | **Primary.** Swap in the Latin rec model (PP-OCRv5 `latin_PP-OCRv5_mobile_rec` lists Spanish) |
| PaddleOCR 3.x (PP-OCRv5/v6) | Best open-source accuracy; Latin models; v6 is one model for about 50 languages | Heavy framework install, bigger image, slower on CPU | Discarded for deploy weight: RapidOCR runs the same model family |
| Tesseract 5 (`spa`) | Tiny; word-level boxes + confidence; Spanish pack | Weak on small UI text unless upscaled 2–3× and binarized; weak on text over colored buttons | **Deferred cross-check** for low-confidence lines (Spec C builds without it; added if accents fail or the click hit rate drops below 95 % live) |
| EasyOCR | Simple API | Pulls in PyTorch; slow on CPU | Discarded |
| docTR, Surya | Strong document OCR + layout | Tuned for documents; want a GPU | Discarded |
| Cloud OCR (Google Vision, Azure Read) | Very accurate | Network round trip per screen, cost, a key to manage | Discarded: latency inside the 5-minute budget |
| VLM as OCR (the VLM reading the image) | Understands context | Imprecise boxes, seconds per call, tokens | Semantics only (§3.3), never as the source of boxes |

### 3.2 Non-text widgets — fields, buttons, grid lines, icons

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Classic CV (OpenCV)**: edges/contours → rectangles; projection profiles / Hough lines → grid rows and columns | Deterministic, about ms per screen, no model. Flat web-style UIs have crisp 1-px borders | Struggles with borderless or icon-only controls | **Chosen** |
| Learned detector: OmniParser's YOLO detector, UIED's CNN | Finds icons and unusual widgets | OmniParser V2 publishes GPU numbers only (0.6 s/frame on A100); its Florence-2 icon captioner is impractical on CPU | Optional, only if the unseen app is icon-heavy |

Chen et al. (2020) asked exactly this question: old-fashioned CV, deep learning, or a mix? Their answer was **a mix**: CV for non-text widget boxes and a dedicated detector for text. That's our split.

### 3.3 Semantics — which element is the one the task means

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **The model + element list (text) + Set-of-Mark image on new screens**: numbered boxes drawn on the screenshot; the model answers `click #12` | The model never predicts pixels. SoM and OmniParser show that marks plus a parsed element list greatly improve grounding for general-purpose VLMs. Text-only on known screens keeps it cheap | Only as good as the element list (§3.1/§3.2) | **Chosen** |
| Claude computer-use with direct x,y | Nothing to build | Pixel guesses; no element tree to feed the map or drift detection; can't tell why a click missed | **Last-resort fallback** for targets with no text and no box |
| Specialist grounding models (UI-TARS, OS-Atlas, UGround, ShowUI, SeeClick) | State of the art on ScreenSpot / ScreenSpot-Pro | Need a GPU and model serving; another service to deploy | Discarded for the hackathon; listed as next step |

### 3.4 Building the tree — the two routes in the literature

The literature takes two routes:
- **Learned end-to-end:** a model outputs the structure directly. pix2code (2017) produces a DSL; Pix2Struct (2022) parses screenshots into simplified HTML; ScreenAI (2024) produces a "screen schema" of type + box + text. These need training data and a GPU.
- **Detect, then group with heuristics:** REMAUI (2015) uses OCR + CV and then merges into a view hierarchy; UIED (2020) is a hybrid detector; Xie et al. (2022) add Gestalt grouping; Apple's Screen Recognition (2021) uses a detector + grouping + reading order to produce an accessibility tree.

---

## 4. Chosen design

### 4.1 Building the tree: detect, then group with heuristics

**We take the second route**, because it works on an unseen app with no training. The steps:
1. **Containment.** If box A lies inside box B, A is B's child. That gives window → panel/dialog → widgets.
2. **Perceptual grouping (Gestalt, Xie 2022).** Widgets that are aligned, close together and similarly styled become one group: a menu bar, a filter row, a form, a toolbar.
3. **Label ↔ field pairing.** An input box takes as its label the nearest text **above** or **to the left** of it. On SIGECOM, "Cliente" sits above the text box and "Estado" above the select. That's what makes `fill_field("Cliente", "Ruiz")` possible.
4. **Grids.** A header row of text aligned with columns of repeated rows becomes a table with named columns. On SIGECOM that's Código, Cliente, Fecha, Vence, Valor, Estado. That feeds `read_grid()` (4.2).
5. **Kind classification by rules:**
   - Text inside a bordered box with a fill → button.
   - Empty bordered box → field.
   - Bordered box with ▾ → select.
   - Blue underlined text → link.
   - Text in the top band → menu.
   - Text in the header row → column header.

**Above the tree: the app map.** The literature treats each screen tree as a node and each action as an edge:
- GUI Ripping (Memon 2003) builds a "GUI forest" plus an event-flow graph.
- DroidBot (2017) builds a UI transition graph.
- AppAgent (2023) has an LLM explore the app and write per-app docs.

That's our tracks 2.2 and 2.4. Perception only has to deliver a stable tree and fingerprint for each node.

### 4.2 Fingerprint and change detection

- **Fingerprint:** the sorted set of *stable* texts (title, menu, labels, column headers), plus a coarse layout hash of the tree. Values are excluded: grid cells, dates, the "Hoy:" clock. It doesn't depend on resolution, because it uses text and relative structure, not pixels.
- **Moved, not changed:** before any OCR, a static element whose crop no longer matches at its stored bbox is searched over the frame with `cv2.matchTemplate`; lossless frames make the match exact, so a hit at ≥ 0.95 updates the bbox and skips perception (Spec W). Only a crop found nowhere triggers OCR.
- **Drift (15:30):**
  - Same fingerprint but a known element is missing or has moved means a **changed screen**.
  - An unknown fingerprint after a known action means a **changed route**.
  - Either way, it's reported to 2.6.

### 4.3 Recommended pipeline

```
action → settle → changed_bbox (poc/rfb_poc.py:149)
              │
              ▼
  ┌── text DETECTION on changed region (or full screen if new) ── ~0.7 s full screen
  │      each line box → hash its pixels → line cache hit? ── yes → text (≈0 ms)
  │                                                    └── no → RECOGNITION (~50 ms/line) → cache
  ├── CV boxes (OpenCV contours + grid lines) ── ms
  ▼
merge → elements → tree (containment · grouping · label↔field · grids · kinds)
  │
  ├─► fingerprint → screen cache: known screen = reuse whole tree, re-read only changed region
  ├─► app map (2.4) / drift (2.6)
  └─► the model: element list as text; + SoM image only on new or unexpected screens
fallbacks: conf < 0.8 → flagged (upscale + Tesseract deferred) · no text/no box → VLM raw x,y
```

**Two caches make this fast:**
- **Line cache:** key = hash of the line's pixels, value = text. Because frames are lossless and fonts are fixed, the same label always renders to the same bytes.
- **Screen cache:** key = fingerprint, value = tree. It also lets **lazy grid reading** work: recognize only the columns or rows the task asks about.

---

## 5. Trade-offs we accept

- **Icons with no text aren't understood.** They fall back to the VLM's raw coordinates, or to the optional detector.
- **Heuristic grouping can mis-pair labels** on dense forms. Action verification (3.3) catches it: "typed into a field, the wrong area changed."
- **CPU only:** no specialist grounding models and no learned tree models. They're next steps if we get a GPU.
- **Latin-script, horizontal text** is an assumption already stated in the design.

---

## 6. Evidence and measurement

Setup: RapidOCR (`rapidocr_onnxruntime`, default models) on `poc/out/before.png` (Facturas, 1280×800). Laptop CPU with 16 threads; Railway will be slower, so re-measure there.

| Run | Time | Notes |
|---|---|---|
| Full pipeline (det + angle cls + rec), full screen | **7.95 s** | 145 lines; far too slow per step |
| Full pipeline without the angle classifier | 7.82 s | the classifier isn't the cost |
| **Detection only**, full screen | **0.72 s** | finding the boxes is cheap |
| **Recognition only**, one 520×35 crop | **52 ms** | so about 145 × 50 ms ≈ 7 s is all recognition |
| Full pipeline on the 520×35 crop | 2.5–2.7 s | det upscales tiny inputs; for diffs, run det on a padded region or reuse last boxes |

**Accuracy observations:**
- Menus, buttons, labels, codes (`FV-10159`), dates and amounts (`1.810.000`) were read correctly at 0.97–1.00 confidence.
- **Accents were dropped** (Gómez → Gomez, Ferretería → Ferreteria, Díaz → Diaz). That's the default Chinese+English model, so we need the Latin rec model.
- **The angle classifier flipped "Todos" into "sopol"** inside the select. UI text is never rotated, so turn the classifier off (`use_cls=False`), which fixed it.
- Header "Código" was read as "oo" with **0.52 confidence**. A confidence threshold flags such lines; re-OCR (upscale or Tesseract) is deferred until live numbers ask for it.
- Small casing errors appeared in the title ("SIGEcoM"), so title text needs case-insensitive matching.

**Conclusion:** detect once, recognize lazily and cache by line pixels. A known screen then costs about 0.7 s (detection) plus near-zero recognition, and a diff region costs a few hundred ms. Full recognition of a 20-row grid stays a deliberate `read_grid()` cost (about 5–7 s) and is a candidate for the clipboard/export path (4.1, 4.4).

---

## 7. Open questions

**Still to measure** (each one is the "Done when" of a 7.x unit):
- Latin model accuracy on accents.
- CV box recall for inputs and buttons.
- Label↔field pairing on Facturas plus one form.
- Grid JSON vs the screen.
- Click hit rate via `click_text`.
- Timings on Railway.

---

## 8. Sources

**OCR engines**
- RapidOCR — https://github.com/RapidAI/RapidOCR
- PaddleOCR (PP-OCRv5 Latin rec model; PP-OCRv6 in 3.x) — https://github.com/PaddlePaddle/PaddleOCR
- Tesseract — https://github.com/tesseract-ocr/tesseract

**Detecting elements and building the tree**
- REMAUI: *Reverse Engineering Mobile Application User Interfaces with REMAUI* (Nguyen & Csallner, ASE 2015) — https://doi.org/10.1109/ASE.2015.32
- Screen Recognition: *Creating Accessibility Metadata for Mobile Applications from Pixels* (Zhang et al., CHI 2021) — https://arxiv.org/abs/2101.04893
- *Object Detection for Graphical User Interface: Old Fashioned or Deep Learning or a Combination?* (Chen et al., ESEC/FSE 2020) — https://arxiv.org/abs/2008.05132
- UIED (the hybrid tool behind Chen et al.) — https://github.com/MulongXie/UIED
- *Psychologically-Inspired, Unsupervised Inference of Perceptual Groups of GUI Widgets from GUI Images* (Xie et al., ESEC/FSE 2022) — https://arxiv.org/abs/2206.10352
- pix2code (Beltramelli, 2017) — https://arxiv.org/abs/1705.07962
- Pix2Struct (Lee et al., ICML 2023) — https://arxiv.org/abs/2210.03347
- ScreenAI (Baechler et al., IJCAI 2024) — https://arxiv.org/abs/2402.04615

**Elements for LLM agents and grounding**
- OmniParser (Lu et al., 2024) — https://arxiv.org/abs/2408.00203 · V2 model card — https://huggingface.co/microsoft/OmniParser-v2.0
- Set-of-Mark prompting (Yang et al., 2023) — https://arxiv.org/abs/2310.11441
- SeeClick + ScreenSpot (Cheng et al., ACL 2024) — https://arxiv.org/abs/2401.10935
- ScreenSpot-Pro (Li et al., 2025) — https://arxiv.org/abs/2504.07981
- UGround (Gou et al., ICLR 2025) — https://arxiv.org/abs/2410.05243
- OS-Atlas (Wu et al., 2024) — https://arxiv.org/abs/2410.23218
- UI-TARS (Qin et al., 2025) — https://arxiv.org/abs/2501.12326
- ShowUI (Lin et al., CVPR 2025) — https://arxiv.org/abs/2411.17465
- Ferret-UI (You et al., ECCV 2024) — https://arxiv.org/abs/2404.05719

**Exploration graph above the tree**
- GUI Ripping: *Reverse Engineering of Graphical User Interfaces for Testing* (Memon, Banerjee & Nagarajan, WCRE 2003) — https://doi.org/10.1109/WCRE.2003.1287256
- DroidBot (Li et al., ICSE 2017) — https://github.com/honeynet/droidbot
- AppAgent (Zhang et al., 2023) — https://arxiv.org/abs/2312.13771

_All links in this section were checked online on 2026-10-10 (the five that had been cited from memory included). The GUI Ripping entry now points at the DOI because the author's page was unreachable._
