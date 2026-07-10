"""
Bake live Perplexity + OpenAI research into demo_research/*.md.

This is a one-time (or occasional refresh) OFFLINE step. It is never called
by the running app: agents/researcher.py reads its committed output back at
demo runtime (agent_researcher() -> _load_baked()) instead of calling
Perplexity, so Perplexity is never contacted while the demo app is live.

Usage:
    python scripts/bake_research.py
    python scripts/bake_research.py --companies "Maersk,MSC,Hapag-Lloyd"
    python scripts/bake_research.py --out demo_research

Requires PERPLEXITY_API_KEY (live web research) and OPENAI_API_KEY
(synthesis, via the demo-mode Cortex seam) in the environment or a .env
file. DEPLOY_MODE=demo (the default) is what makes the synthesis step route
through OpenAI; the four research calls always hit Perplexity live here
regardless of DEPLOY_MODE, because this script calls
agents.researcher._run_live_research() directly.
"""
import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# Make this runnable from anywhere: python scripts/bake_research.py,
# python bake_research.py from inside scripts/, etc.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from config import PERPLEXITY_API_KEY  # noqa: E402
from agents.researcher import _run_live_research, _slug  # noqa: E402


# Dropdown key (as it appears in demo_data/sales_actuals.csv CUSTOMER_NAME)
# -> full company name used as the research query.
BAKED = {
    "Maersk": "A.P. Moller-Maersk",
    "MSC": "MSC Mediterranean Shipping Company",
    "Hapag-Lloyd": "Hapag-Lloyd AG",
}


def _bake_one(dropdown_key, query_name, out_dir):
    """Run the live research pipeline for one company and write its .md file.

    Returns (dropdown_key, success, error_traceback_or_None). Never raises —
    failures are caught, logged, and reported back so other companies in the
    ThreadPoolExecutor batch keep running.
    """
    start = time.monotonic()
    print(f"[bake] {dropdown_key} ({query_name}) — starting...", flush=True)
    try:
        content = _run_live_research(None, query_name)
        if not content or not content.strip():
            raise RuntimeError("live research returned empty output")
        elapsed = time.monotonic() - start
        path = os.path.join(out_dir, f"{_slug(dropdown_key)}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(
            f"[bake] {dropdown_key} — done in {elapsed:.1f}s, "
            f"{len(content):,} chars -> {path}",
            flush=True,
        )
        return dropdown_key, True, None
    except Exception:
        elapsed = time.monotonic() - start
        tb = traceback.format_exc()
        print(f"[bake] {dropdown_key} — FAILED after {elapsed:.1f}s", flush=True)
        print(tb, flush=True)
        return dropdown_key, False, tb


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Bake live Perplexity + OpenAI research into demo_research/*.md "
            "for the demo's flagship companies. Requires PERPLEXITY_API_KEY "
            "and OPENAI_API_KEY. Never called by the running app."
        )
    )
    parser.add_argument(
        "--companies",
        default=",".join(BAKED.keys()),
        help=(
            "Comma-separated dropdown keys to (re)bake. Default: all "
            f"flagship companies ({', '.join(BAKED.keys())})."
        ),
    )
    parser.add_argument(
        "--out",
        default="demo_research",
        help="Output directory for baked .md files (default: demo_research).",
    )
    args = parser.parse_args()

    if not PERPLEXITY_API_KEY:
        print(
            "ERROR: PERPLEXITY_API_KEY is not set. Baking requires live "
            "Perplexity access — set PERPLEXITY_API_KEY (and OPENAI_API_KEY, "
            "used for synthesis) in your environment or a .env file, then "
            "re-run this script. PERPLEXITY_API_KEY is NOT needed to run the "
            "demo app itself; it is only needed here.",
            file=sys.stderr,
        )
        sys.exit(1)

    keys = [k.strip() for k in args.companies.split(",") if k.strip()]
    unknown = [k for k in keys if k not in BAKED]
    if unknown:
        print(
            f"ERROR: unknown company key(s): {unknown}. Known keys: {list(BAKED.keys())}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not keys:
        print("ERROR: no companies to bake.", file=sys.stderr)
        sys.exit(1)

    out_dir = args.out if os.path.isabs(args.out) else os.path.join(_REPO_ROOT, args.out)
    os.makedirs(out_dir, exist_ok=True)

    print(
        f"[bake] Baking {len(keys)} companies into {out_dir} "
        f"(ThreadPoolExecutor max_workers=3)...",
        flush=True,
    )

    results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_bake_one, key, BAKED[key], out_dir): key for key in keys}
        for future in as_completed(futures):
            key, ok, _err = future.result()
            results[key] = ok

    meta = {
        "baked_at": datetime.now(timezone.utc).isoformat(),
        "companies": {key: BAKED[key] for key in keys},
        "notes": "generated by scripts/bake_research.py",
    }
    meta_path = os.path.join(out_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[bake] Wrote {meta_path}", flush=True)

    failed = [key for key, ok in results.items() if not ok]
    if failed:
        print(f"[bake] FAILED for: {failed}. See tracebacks above.", file=sys.stderr)
        sys.exit(1)

    print(f"[bake] All {len(keys)} companies baked successfully.", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
