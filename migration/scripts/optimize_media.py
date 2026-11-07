#!/usr/bin/env python3
"""Slim published media: prune unreferenced uploads, convert images to WebP
(rewriting references), and re-encode videos. Idempotent; safe to re-run.

"Used" = any /img/uploads reference in content/, layouts/, data/, hugo.yaml
(covers post bodies, front-matter banner:/image:, <video> src, the hero image).
Originals remain in wordpress/backup + migration/wp-export, so this is recoverable.

Requires: cwebp, ffmpeg, sips (macOS).  Run from anywhere:  python optimize_media.py
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "static" / "img" / "uploads"
SRC_DIRS = ["content", "layouts", "data"]
EXTRA = [ROOT / "hugo.yaml"]
SRC_SUFFIXES = {".md", ".html", ".yaml", ".yml", ".toml", ".json", ".xml"}
IMG_EXT = {".png", ".jpg", ".jpeg"}
VID_EXT = {".mp4", ".webm", ".mov"}

# matches /img/uploads/... or img/uploads/... (the hero uses no leading slash)
REF_RE = re.compile(r"/?img/uploads/[^\s\"')(<>\]\\]+\.[A-Za-z0-9]+")
# greedy path match so only the FINAL extension is swapped (some originals have
# double extensions like "foo.jpg.png" → disk becomes "foo.jpg.webp")
SUB_RE = re.compile(r"((?:/)?img/uploads/[^\s\"')(<>\]\\]+)\.(png|jpe?g)\b", re.IGNORECASE)


def src_files():
    out = []
    for d in SRC_DIRS:
        out += [p for p in (ROOT / d).rglob("*") if p.is_file() and p.suffix.lower() in SRC_SUFFIXES]
    out += [f for f in EXTRA if f.exists()]
    return out


def rel_of(ref):
    return ref.split("img/uploads/", 1)[1]


def img_width(p):
    r = subprocess.run(["sips", "-g", "pixelWidth", str(p)], capture_output=True, text=True)
    m = re.search(r"pixelWidth:\s*(\d+)", r.stdout)
    return int(m.group(1)) if m else 0


# A single run may not delete more than this share of the uploads tree without
# --allow-mass-prune. Above it, the run is either a broken reference scan or a
# deliberate post-migration clean-up, and only a human can tell which.
MAX_PRUNE_FRACTION = 0.5


def main(allow_mass_prune: bool = False):
    files = src_files()
    refs = set()
    unreadable = []
    for p in files:
        # Was `except Exception: pass`. A source file that could not be READ
        # then looked exactly like one referencing nothing, and the images it
        # used were pruned. Unknown is not "no" (CON-DATA-002).
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            unreadable.append(f"{p}: {exc}")
            continue
        for m in REF_RE.findall(text):
            refs.add(rel_of(m))
    if unreadable:
        sys.exit("refusing to prune: could not read " + str(len(unreadable))
                 + " source file(s), so their references are unknown:\n  "
                 + "\n  ".join(unreadable[:10]))
    missing = sorted(r for r in refs if not (UPLOADS / r).exists())
    print(f"referenced upload files: {len(refs)} | missing on disk: {len(missing)}")
    for m in missing[:10]:
        print("  MISSING (kept as-is):", m)
    keep = {r for r in refs if (UPLOADS / r).exists()}

    # 1) PRUNE unreferenced files — decided in full BEFORE anything is deleted
    # (spec: CON-PROC-006, guard destructive actions by construction).
    on_disk = [p for p in UPLOADS.rglob("*") if p.is_file()]
    doomed = [p for p in on_disk if p.relative_to(UPLOADS).as_posix() not in keep]
    if on_disk and not refs:
        sys.exit(f"refusing to prune: no source file references any upload, which "
                 f"would delete all {len(on_disk)} files. That is almost certainly a "
                 f"broken reference scan, not an unused tree.")
    if on_disk and len(doomed) / len(on_disk) > MAX_PRUNE_FRACTION and not allow_mass_prune:
        sys.exit(f"refusing to prune {len(doomed)} of {len(on_disk)} uploads "
                 f"(> {MAX_PRUNE_FRACTION:.0%}). If this is a deliberate post-migration "
                 f"clean-up, re-run with --allow-mass-prune.")
    pruned = 0
    for p in doomed:
        p.unlink(); pruned += 1
    print(f"pruned {pruned} unreferenced files")

    # 2) CONVERT images -> webp (only downscale oversized; never upscale)
    failed = set()
    converted = 0
    for rel in sorted(keep):
        src = UPLOADS / rel
        if src.suffix.lower() not in IMG_EXT or not src.exists():
            continue
        dst = src.with_suffix(".webp")
        args = ["cwebp", "-quiet", "-q", "80"]
        if img_width(src) > 1400:
            args += ["-resize", "1280", "0"]
        args += [str(src), "-o", str(dst)]
        r = subprocess.run(args)
        if r.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            src.unlink(); converted += 1
        else:
            failed.add(rel)
            if dst.exists():
                dst.unlink()
    print(f"converted {converted} images to webp | failed {len(failed)}")
    for f in list(failed)[:10]:
        print("  CONVERT FAILED (left as original):", f)

    # 3) REWRITE references .png/.jpg/.jpeg -> .webp (skip any that failed to convert)
    def repl(m):
        rel = rel_of(m.group(0))
        return m.group(0) if rel in failed else m.group(1) + ".webp"
    changed = 0
    for p in files:
        try:
            t = p.read_text(encoding="utf-8")
        except Exception:
            continue
        nt = SUB_RE.sub(repl, t)
        if nt != t:
            p.write_text(nt, encoding="utf-8"); changed += 1
    print(f"rewrote image refs in {changed} source files")

    # 4) RE-ENCODE videos in place (keep .mp4 name; only replace if smaller)
    venc = 0
    for rel in sorted(keep):
        src = UPLOADS / rel
        if src.suffix.lower() not in VID_EXT or not src.exists():
            continue
        tmp = src.with_name(src.stem + ".opt.mp4")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                            "-vcodec", "libx264", "-crf", "26", "-preset", "slow",
                            "-acodec", "aac", "-movflags", "+faststart", str(tmp)])
        if r.returncode == 0 and tmp.exists() and 0 < tmp.stat().st_size < src.stat().st_size:
            tmp.replace(src.with_suffix(".mp4")); venc += 1
            if src.suffix.lower() != ".mp4":  # e.g. .mov -> .mp4 (rare; would need ref fix)
                pass
        elif tmp.exists():
            tmp.unlink()
    print(f"re-encoded {venc} videos")

    # 5) resize the oversized logo in place (shown <=~90px)
    logo = ROOT / "static" / "img" / "logo.png"
    if logo.exists():
        subprocess.run(["sips", "-Z", "512", str(logo)], capture_output=True)
        print("resized static/img/logo.png to max 512px")

    # 6) drop now-empty dirs
    for d in sorted([p for p in UPLOADS.rglob("*") if p.is_dir()], reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    print("done.")


def cli():
    import argparse
    ap = argparse.ArgumentParser(
        description="Prune unreferenced uploads, convert images to WebP, re-encode video.")
    ap.add_argument("--allow-mass-prune", action="store_true",
                    # %% — argparse %-formats help strings, so a bare "50% of"
                    # reads as the "% o" conversion and crashes --help.
                    help=f"permit pruning more than {MAX_PRUNE_FRACTION:.0%}% of the uploads tree")
    args = ap.parse_args()
    return main(allow_mass_prune=args.allow_mass_prune)


if __name__ == "__main__":
    sys.exit(cli())
