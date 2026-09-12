#!/usr/bin/env python3
"""
Sahih al-Bukhari Hadith Automated Translation Script (Parallel Edition)
========================================================================
Translates English Sahih al-Bukhari JSON files into target language directories
matching their ISO shortcodes while strictly adhering to critical exclusion rules
and preserving exact JSON structure.

CRITICAL RULE:
Do NOT translate, modify, process, or write files for 'en', 'ur', or 'ar'.

Usage:
  python translate_bukhari.py -l fr              # Single language
  python translate_bukhari.py --all              # All languages sequentially
  python translate_bukhari.py --all --workers 8  # All languages, 8 parallel workers
  python translate_bukhari.py --all --resume     # Skip already-done files
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.parse
import multiprocessing
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants & Exclusion Rules
# ---------------------------------------------------------------------------
EXCLUDED_LANGUAGES = {'en', 'ur', 'ar'}
BASE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = BASE_DIR / "en" / "bukhari" / "hadiths"

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
def is_excluded_language(lang_code: str) -> bool:
    """Return True if the target language is in the excluded list ('en', 'ur', 'ar')."""
    return lang_code.lower().strip() in EXCLUDED_LANGUAGES


def split_text_into_chunks(text: str, max_chunk_size: int = 1500) -> list:
    """Split text into smaller chunks at sentence boundaries to fit URL limits."""
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    parts = text.split('. ')
    current_chunk = ""

    for idx, part in enumerate(parts):
        sentence = part + ('. ' if idx < len(parts) - 1 else '')
        if len(current_chunk) + len(sentence) <= max_chunk_size:
            current_chunk += sentence
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text]


def translate_chunk_google(text: str, target_lang: str, source_lang: str = 'en', retries: int = 3, delay: float = 0.05) -> str:
    """Translate a single chunk via Google Translate free endpoint with retry logic."""
    if not text.strip():
        return text

    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl={source_lang}&tl={target_lang}&dt=t"
        f"&q={urllib.parse.quote(text)}"
    )
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                res = json.loads(response.read().decode('utf-8'))
                translated = "".join([item[0] for item in res[0] if item and item[0]])
                if delay > 0:
                    time.sleep(delay)
                return translated
        except Exception as e:
            if attempt < retries:
                time.sleep(1.0 * attempt)
            else:
                return text  # Fall back to original on complete failure


def translate_text(text: str, target_lang: str, source_lang: str = 'en', delay: float = 0.05) -> str:
    """Translate full text, chunking if necessary."""
    chunks = split_text_into_chunks(text, max_chunk_size=1500)
    translated_chunks = [
        translate_chunk_google(chunk, target_lang, source_lang, delay=delay)
        for chunk in chunks
    ]
    return " ".join(translated_chunks)


def process_language(args_tuple):
    """
    Worker function: translate all source files for a given language.
    Accepts a tuple for multiprocessing compatibility.
    """
    target_lang, resume, delay, dry_run = args_tuple

    # Re-configure stdout per-process (needed for Windows multiprocessing)
    sys.stdout.reconfigure(encoding='utf-8')

    target_lang_clean = target_lang.lower().strip()

    # ---- CRITICAL EXCLUSION GUARD ----
    if is_excluded_language(target_lang_clean):
        print(f"[SKIP EXCLUDED] '{target_lang_clean}' is excluded (en/ur/ar). No files written.", flush=True)
        return target_lang_clean, False, 0, 0

    target_dir = BASE_DIR / target_lang_clean / "bukhari" / "hadiths"
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    if not SOURCE_DIR.exists():
        print(f"[ERROR] Source dir not found: {SOURCE_DIR}", flush=True)
        return target_lang_clean, False, 0, 0

    # Sort files numerically
    source_files = sorted(
        SOURCE_DIR.glob("*.json"),
        key=lambda p: int(p.stem) if p.stem.isdigit() else p.name
    )

    print(f"[START] [{target_lang_clean}] Processing {len(source_files)} files...", flush=True)

    translated_files = 0
    total_hadiths = 0
    skipped = 0

    for file_path in source_files:
        out_file_path = target_dir / file_path.name

        if resume and out_file_path.exists():
            skipped += 1
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                hadith_list = json.load(f)

            translated_list = []
            for item in hadith_list:
                translated_list.append({
                    "hadithNo": item.get("hadithNo"),
                    "text": translate_text(item.get("text", ""), target_lang=target_lang_clean, delay=delay),
                    "grades": item.get("grades", [])
                })

            total_hadiths += len(translated_list)

            if not dry_run:
                with open(out_file_path, "w", encoding="utf-8") as out_f:
                    json.dump(translated_list, out_f, ensure_ascii=False, indent=2)

            translated_files += 1

        except Exception as e:
            print(f"[ERROR] [{target_lang_clean}] {file_path.name}: {e}", flush=True)

    print(
        f"[DONE] [{target_lang_clean}] {translated_files} files, "
        f"{total_hadiths} hadiths translated, {skipped} skipped (resume).",
        flush=True
    )
    return target_lang_clean, True, translated_files, total_hadiths


# ---------------------------------------------------------------------------
# Main CLI Entry Point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Translate Sahih al-Bukhari hadiths from English into target ISO language directories."
    )
    parser.add_argument("-l", "--target-lang", type=str,
                        help="Target language ISO code (e.g., fr, id, es).")
    parser.add_argument("--all", action="store_true",
                        help="Process all available ISO language dirs (excluding en, ur, ar).")
    parser.add_argument("--workers", type=int, default=4,
                        help="Number of parallel worker processes (default: 4).")
    parser.add_argument("--limit-files", type=int, default=None,
                        help="Limit number of source JSON files per language (for testing).")
    parser.add_argument("--resume", action="store_true",
                        help="Skip target files that already exist.")
    parser.add_argument("--delay", type=float, default=0.05,
                        help="Delay in seconds between API chunk requests (default: 0.05s).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Test without writing output files.")

    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')

    if not args.target_lang and not args.all:
        parser.print_help()
        print("\n[ERROR] Specify --target-lang ISO_CODE or --all.")
        sys.exit(1)

    if args.all:
        all_dirs = sorted([
            d.name for d in BASE_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ])
        valid_langs = [d for d in all_dirs if not is_excluded_language(d)]
        print(f"[INFO] {len(valid_langs)} target languages found (en/ur/ar excluded).")
        print(f"[INFO] Running with {args.workers} parallel workers.\n")

        worker_args = [(lang, args.resume, args.delay, args.dry_run) for lang in valid_langs]

        # Use multiprocessing pool
        with multiprocessing.Pool(processes=args.workers) as pool:
            results = pool.map(process_language, worker_args)

        # Summary
        success = [r for r in results if r[1]]
        print(f"\n{'='*60}")
        print(f"COMPLETE: {len(success)}/{len(valid_langs)} languages fully processed.")
        total_h = sum(r[3] for r in success)
        print(f"Total hadiths translated: {total_h:,}")
        print(f"{'='*60}")

    else:
        target_lang = args.target_lang
        if is_excluded_language(target_lang):
            print(f"\n[SKIP EXCLUDED] '{target_lang}' is in EXCLUDED_LANGUAGES (en, ur, ar). Nothing done.")
            sys.exit(0)
        result = process_language((target_lang, args.resume, args.delay, args.dry_run))
        print(f"\nResult: lang={result[0]}, success={result[1]}, files={result[2]}, hadiths={result[3]}")


if __name__ == "__main__":
    main()
