"""Turn the team's weekly repair PowerPoint into Hugo post bundles.

The shop already builds a deck of before/after photos every week for the TV in the store.
This reads that deck rather than asking anyone to type a repair in twice — which is why the
previous publishing flow lapsed.

A `.pptx` is a zip of XML, so this uses only `zipfile` + `ElementTree`. That was verified
against the real deck (`migration/wp-export/.../Repair-1.1.7.pptx`) before being chosen, so
it adds no dependency. `python-pptx` is the fallback if a future deck defeats it.

The format, read off that deck:

  * A **repair slide** has exactly 2 picture shapes and text containing both "Before" and
    "After". Boilerplate capability slides have 1 picture and neither label.
  * **Before/after is decided by x-position**, never by filename — slides 7 and 8 of the
    reference deck have the higher-numbered image on the left.
  * The **title** is the topmost text shape; the **captions** are the low-y text shapes on
    each side, with runs joined (bold formatting splits a sentence across runs).
  * Furniture to drop: deck version, page number, the slide's date, the company footer.
  * The slide's own date is a stale placeholder (every repair slide reads 10-03-2021 in a
    deck dated 20-02-2022) and is ignored entirely.
"""
import io
import re
import sys
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "migration" / "scripts"))

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

DEFAULT_SLIDE_WIDTH = 12_192_000            # EMU, 13.33in widescreen

# Text that is deck chrome rather than content.
_VERSION_RE = re.compile(r"^\s*\d+\.\d+\.\d+\s*$")
_DATE_RE = re.compile(r"^\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\s*$")
_PAGENO_RE = re.compile(r"^\s*\d{1,3}\s*$")
_FOOTER_RE = re.compile(r"gadjoy\s*repair\s*services", re.I)
_LABEL_RE = re.compile(r"^\s*(before|after)\s*$", re.I)

# A title has to look like one. The team's convention is "Device – Work done".
_TITLE_MIN_LEN = 8


class DeckFormatError(Exception):
    """The deck does not match the expected format.

    Raised rather than skipping, because publication is unattended: a slide that looks like
    a repair but cannot be read must stop the run and be seen, not vanish from the output.
    """


@dataclass
class Image:
    name: str
    data: bytes


@dataclass
class Repair:
    slide: int
    title: str
    before_image: Image
    after_image: Image
    before_caption: str
    after_caption: str
    video: Optional[Image] = None


@dataclass
class Skip:
    slide: int
    reason: str


@dataclass
class DeckParse:
    repairs: List[Repair]
    skipped: List[Skip]


def _is_furniture(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    return bool(
        _VERSION_RE.match(t) or _DATE_RE.match(t) or _PAGENO_RE.match(t)
        or _FOOTER_RE.search(t)
    )


def _shape_text(sp) -> str:
    """Join every run in one shape. Bold formatting splits a sentence into several runs
    ("We had " / "Replaced the Charging port" / " and tested..."), so per-shape joining is
    what recovers the original sentence."""
    return "".join(t.text or "" for t in sp.iter(A + "t"))


def _offset(el) -> Tuple[int, int]:
    off = el.find(".//" + A + "off")
    if off is None:
        return (-1, -1)
    try:
        return (int(off.get("x", -1)), int(off.get("y", -1)))
    except (TypeError, ValueError):
        return (-1, -1)


def build_repair(slide, texts, pictures, slide_width, video) -> Repair:
    """Assemble one repair from a slide's text shapes and pictures.

    `texts` is [(text, x, y)], `pictures` is [(name_or_Image, x)]. Split out from the XML
    reading so the geometry rules are unit-testable without a .pptx.
    """
    mid = slide_width // 2

    content = [(t, x, y) for (t, x, y) in texts
               if not _is_furniture(t) and not _LABEL_RE.match(t.strip())]
    if not content:
        raise DeckFormatError(
            f"slide {slide}: looks like a repair slide (2 pictures, Before/After labels) but "
            f"has no usable text. The deck template may have changed."
        )

    # Title: topmost remaining text shape.
    title_text, _tx, title_y = min(content, key=lambda c: c[2])
    title = " ".join(title_text.split())
    if len(title) < _TITLE_MIN_LEN:
        raise DeckFormatError(
            f"slide {slide}: no usable title (best candidate was {title!r}). "
            f"Expected the team's 'Device – Work done' heading."
        )

    # Captions: the lowest text shape on each side of the midpoint, excluding the title.
    below = [c for c in content if c[2] > title_y]
    left = [c for c in below if c[1] < mid]
    right = [c for c in below if c[1] >= mid]
    before_caption = " ".join(max(left, key=lambda c: c[2])[0].split()) if left else ""
    after_caption = " ".join(max(right, key=lambda c: c[2])[0].split()) if right else ""

    ordered = sorted(pictures, key=lambda p: p[1])
    return Repair(
        slide=slide,
        title=title,
        before_image=ordered[0][0],
        after_image=ordered[-1][0],
        before_caption=before_caption,
        after_caption=after_caption,
        video=video,
    )


def parse_deck(path: Path) -> DeckParse:
    path = Path(path)
    z = zipfile.ZipFile(path)
    names = z.namelist()

    slide_width = DEFAULT_SLIDE_WIDTH
    if "ppt/presentation.xml" in names:
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        sz = pres.find(P + "sldSz")
        if sz is not None and sz.get("cx"):
            slide_width = int(sz.get("cx"))

    slide_names = sorted(
        (n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
        key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()),
    )

    repairs, skipped = [], []
    for name in slide_names:
        num = int(re.search(r"slide(\d+)\.xml", name).group(1))
        root = ET.fromstring(z.read(name))
        rels = ET.fromstring(z.read(f"ppt/slides/_rels/slide{num}.xml.rels"))
        rmap = {r.get("Id"): r.get("Target").split("/")[-1] for r in rels}

        texts = []
        for sp in root.iter(P + "sp"):
            t = _shape_text(sp)
            if t.strip():
                x, y = _offset(sp)
                texts.append((t, x, y))

        pictures = []
        for pic in root.iter(P + "pic"):
            blip = pic.find(".//" + A + "blip")
            if blip is None:
                continue
            rid = blip.get(R + "embed")
            media = rmap.get(rid)
            if not media:
                continue
            x, _y = _offset(pic)
            pictures.append((media, x))

        flat = " ".join(t for t, _x, _y in texts).lower()
        has_labels = "before" in flat and "after" in flat

        if len(pictures) != 2 or not has_labels:
            skipped.append(Skip(
                slide=num,
                reason=(f"not a repair slide: {len(pictures)} picture(s), "
                        f"before/after labels {'present' if has_labels else 'absent'}"),
            ))
            continue

        # <a:videoFile> is DrawingML, NOT presentationml. This originally looked for
        # `p:videoFile`, so no video was ever found — and the test only asserted the
        # attribute existed, which is true of a permanently-None attribute.
        video = None
        for vf in root.iter(A + "videoFile"):
            media = rmap.get(vf.get(R + "link") or vf.get(R + "embed"))
            if media and f"ppt/media/{media}" in names:
                video = Image(media, z.read(f"ppt/media/{media}"))
                break

        loaded = [(Image(m, z.read(f"ppt/media/{m}")), x) for m, x in pictures]
        repairs.append(build_repair(num, texts, loaded, slide_width, video))

    return DeckParse(repairs=repairs, skipped=skipped)


# ============================================================================
# Generation: repair -> Hugo post bundle
# ============================================================================

# Only slugs that already exist under content/categories/ may be emitted.
# `test_taxonomy_is_real` rejects anything else, and inventing a taxonomy term is
# forbidden outright (Principle III). The test cross-checks this list against the real
# directory, so a drift here fails rather than silently publishing a broken category link.
VALID_CATEGORIES = {
    "repair", "mobiles", "laptop-and-desktop", "apple-watch",
    "display-and-glass-replacement", "water-damage", "hinge-repair",
    "chip-level-and-ic-repair-mobile", "replacements",
}

_DEVICE_MAP = [
    (r"\b(iphone|ipad|redmi|vivo|oppo|realme|samsung|galaxy|moto|nokia|oneplus|mi|poco|lava|infinix|tecno)\b", "mobiles"),
    (r"\b(laptop|macbook|desktop|notebook|hp|dell|lenovo|acer|asus|thinkpad|imac)\b", "laptop-and-desktop"),
    (r"\b(watch)\b", "apple-watch"),
]
_WORK_MAP = [
    (r"\b(display|combo|glass|touch|screen|lcd)\b", "display-and-glass-replacement"),
    (r"\b(water|liquid)\b", "water-damage"),
    (r"\b(hinge)\b", "hinge-repair"),
    (r"\b(chip|ic|board|motherboard)\b", "chip-level-and-ic-repair-mobile"),
]


def slugify(title: str) -> str:
    """Match the slug style of the migrated corpus: lowercase, ASCII, hyphenated.

    Titles use an en dash ("Redmi Note 7 – Charging port Replacement"), which normalises
    away rather than becoming a stray hyphen run.
    """
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("–", " ").replace("—", " ").replace("&", " and ")
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return re.sub(r"-{2,}", "-", t)


def unique_slug(base: str, existing) -> str:
    """Follow the corpus convention of a numeric suffix on collision."""
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def categories_for(text: str) -> List[str]:
    """Classify from the title. Unmapped work falls back to `repair` rather than guessing."""
    low = text.lower()
    cats = []
    for pattern, slug in _DEVICE_MAP + _WORK_MAP:
        if re.search(pattern, low) and slug not in cats:
            cats.append(slug)
    cats = [c for c in cats if c in VALID_CATEGORIES]
    if "repair" not in cats:
        cats.insert(0, "repair")
    return cats or ["repair"]


# --- privacy interlock -------------------------------------------------------
def detect_identifiers(data: bytes, name: str) -> List[dict]:
    """Identifier hits in an in-memory image, using the shared detector."""
    from device_identifiers import find_identifiers, ocr_words

    suffix = Path(name).suffix or ".png"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"probe{suffix}"
        p.write_bytes(data)
        text, words = ocr_words(p)
        return find_identifiers(text, words)


def redact_bytes(data: bytes, name: str) -> Tuple[bytes, List[str]]:
    """Obscure any device/customer identifiers, returning (bytes, kinds removed).

    Photographs of About screens publish serials, IMEIs and MAC addresses; 229 such images
    had to be redacted retrospectively in PR #16. Doing it here means nothing un-redacted is
    ever written into `static/`, so the site cannot acquire the problem again.

    Returns the input unchanged when nothing is found. Output is PNG when modified, so the
    single lossy encode happens later in `to_webp`.
    """
    from PIL import Image as PILImage
    from redact_device_identifiers import MAX_REDACT_FRACTION, auto_boxes, mosaic

    hits = detect_identifiers(data, name)
    if not hits:
        return data, []

    suffix = Path(name).suffix or ".png"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"in{suffix}"
        p.write_bytes(data)
        boxes = auto_boxes(p)
        im = PILImage.open(p).convert("RGB")

    covered = 0
    clamped = []
    for left, top, right, bottom in boxes:
        left, top = max(0, int(left)), max(0, int(top))
        right, bottom = min(im.width, int(right)), min(im.height, int(bottom))
        if right > left and bottom > top:
            clamped.append((left, top, right, bottom))
            covered += (right - left) * (bottom - top)

    fraction = covered / float(im.width * im.height) if im.width and im.height else 0
    if fraction > MAX_REDACT_FRACTION:
        raise DeckFormatError(
            f"{name}: redacting the identifiers would obscure {fraction:.0%} of the photo "
            f"(cap {MAX_REDACT_FRACTION:.0%}). Publish a photo of the device instead of its "
            f"About screen."
        )

    for b in clamped:
        im = mosaic(im, b)
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue(), sorted({h["kind"] for h in hits})


def to_webp(data: bytes, quality: int = 88, max_width: int = 1400) -> bytes:
    """Match the site's media convention: WebP, downscaled only if oversized."""
    from PIL import Image as PILImage

    im = PILImage.open(io.BytesIO(data)).convert("RGB")
    if im.width > max_width:
        im = im.resize((max_width, round(im.height * max_width / im.width)), PILImage.LANCZOS)
    out = io.BytesIO()
    im.save(out, "WEBP", quality=quality, method=6)
    return out.getvalue()


# --- post assembly -----------------------------------------------------------
@dataclass
class Post:
    slug: str
    front_matter: dict
    body: str
    images: Dict[str, bytes] = field(default_factory=dict)
    redactions: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def bundle_path(self) -> str:
        d = str(self.front_matter["date"])[:10].replace("-", "/")
        return f"content/blog/{d}/{self.slug}/index.md"


def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    return "'" + s.replace("'", "''") + "'" if (":" in s or s.startswith(" ") or "'" in s) else s


def render_front_matter(fm: dict) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}:")
                lines += [f"- {item}" for item in v]
        else:
            lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines)


def build_post(repair: Repair, date: str, issue: int, existing_slugs) -> Post:
    slug = unique_slug(slugify(repair.title), set(existing_slugs))
    y, m = date[:4], date[5:7]
    stem = f"/img/uploads/{y}/{m}/{slug}"

    images, redactions = {}, {}
    for role, img in (("before", repair.before_image), ("after", repair.after_image)):
        cleaned, removed = redact_bytes(img.data, img.name)
        if removed:
            redactions[role] = removed
        images[f"static/img/uploads/{y}/{m}/{slug}-{role}.webp"] = to_webp(cleaned)

    summary = repair.before_caption or repair.title
    fm = {
        "title": repair.title,
        "date": f"{date}T10:00:00",
        "slug": slug,
        "draft": False,
        "categories": categories_for(f"{repair.title} {repair.before_caption}"),
        "tags": [],
        "aliases": [],                       # never had a legacy /blog/ URL (FR-018)
        "description": summary,
        "summary": summary,
        "banner": f"{stem}-before.webp",
        "origin": "deck",                    # scopes the migrated-count invariant
        "deck_issue": issue,
        "deck_slide": repair.slide,
    }
    body = "\n".join([
        "", "## Before", "",
        f"![]({stem}-before.webp)", "",
        f"**{repair.before_caption}**", "",
        "## After", "",
        f"![]({stem}-after.webp)", "",
        f"**{repair.after_caption}**", "",
    ])
    return Post(slug=slug, front_matter=fm, body=body, images=images, redactions=redactions)


@dataclass
class PublishReport:
    published: List[Post] = field(default_factory=list)
    already_present: List[int] = field(default_factory=list)
    skipped: List[Skip] = field(default_factory=list)
    redactions: Dict[str, List[str]] = field(default_factory=dict)
    # Slugs that needed a numeric suffix because the base was already taken. Not an error —
    # the same model with the same fault genuinely recurs — but with auto-merge on it is the
    # one signal that a deck may be a re-run of work already published, so it is surfaced
    # rather than silently disambiguated. (The 2022 reference deck sets every one of these,
    # because its repairs were published on WordPress and migrated years ago.)
    resurfaced_slugs: List[str] = field(default_factory=list)
    # Slides whose video was left unpublished. Reported rather than dropped in silence:
    # the privacy interlock OCRs still images and cannot inspect video frames, so embedding
    # a clip would let an About screen bypass the redaction this site spent 229 images
    # building. Skipping is the consistent choice; hiding the skip is not (FR-010).
    skipped_videos: List[str] = field(default_factory=list)


def _existing_state(out_root: Path):
    """Slugs already taken, and (issue, slide) pairs already published — the idempotence key."""
    slugs, published = set(), set()
    blog = out_root / "content" / "blog"
    for md in blog.rglob("index.md") if blog.is_dir() else []:
        text = md.read_text(encoding="utf-8", errors="ignore")
        if not text.startswith("---"):
            continue
        head = text.split("---", 2)[1]
        slug = re.search(r"^slug:\s*(.+)$", head, re.M)
        issue = re.search(r"^deck_issue:\s*(\d+)$", head, re.M)
        slide = re.search(r"^deck_slide:\s*(\d+)$", head, re.M)
        if slug:
            slugs.add(slug.group(1).strip().strip("'\""))
        if issue and slide:
            published.add((int(issue.group(1)), int(slide.group(1))))
    return slugs, published


def publish_deck(deck: Path, date: str, issue: int, out_root: Path,
                 dry_run: bool = False) -> PublishReport:
    """Parse a deck and write every new repair under `out_root`.

    Idempotent on (issue, slide): re-running a deck that has already been published adds
    nothing, so a retried workflow cannot duplicate the week's posts.
    """
    out_root = Path(out_root)
    parsed = parse_deck(deck)
    slugs, done = _existing_state(out_root)
    report = PublishReport(skipped=list(parsed.skipped))

    for repair in parsed.repairs:
        if (issue, repair.slide) in done:
            report.already_present.append(repair.slide)
            continue
        post = build_post(repair, date=date, issue=issue, existing_slugs=slugs)
        if post.slug != slugify(repair.title):
            report.resurfaced_slugs.append(post.slug)
        slugs.add(post.slug)
        report.published.append(post)
        if post.redactions:
            report.redactions[post.slug] = sorted(
                {k for kinds in post.redactions.values() for k in kinds}
            )
        if repair.video:
            report.skipped_videos.append(f"{post.slug} (slide {repair.slide})")
        if dry_run:
            continue
        md = out_root / post.bundle_path
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_front_matter(post.front_matter) + "\n" + post.body, encoding="utf-8")
        for rel, data in post.images.items():
            p = out_root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    return report
