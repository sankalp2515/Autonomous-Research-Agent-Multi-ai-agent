"""Fetch the benchmark data the research-synthesis evals score against.

Nothing here is committed: SciFact is CC BY-NC 2.0 and SYNERGY's abstracts may
not be republished in plaintext. Both land in evals/data/ (gitignored).

    python -m evals.fetch_data scifact      # ~3 MB from AllenAI's S3
    python -m evals.fetch_data synergy      # Hall_2012 only; needs `pip install synergy-dataset`

Archives are extracted with tarfile's 'data' filter (no absolute paths, no
traversal, no links out of the target), and the SYNERGY export reads the
downloaded files as data only.
"""

import csv
import io
import json
import os
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

DATA = Path(__file__).parent / "data"
SCIFACT_URL = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"


def scifact() -> None:
    target = DATA / "scifact"
    target.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(SCIFACT_URL, timeout=60) as resp:   # noqa: S310 (fixed https URL)
        blob = resp.read(50 * 1024 * 1024)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        tar.extractall(target, filter="data")
    n = sum(1 for _ in open(target / "data" / "claims_dev.jsonl", encoding="utf-8"))
    print(f"SciFact: {len(blob) / 1e6:.1f} MB, {n} dev claims -> {target / 'data'}")


def _abstract(index: dict | None) -> str:
    if not index:
        return ""
    pos = sorted((p, w) for w, ps in index.items() for p in ps)
    return " ".join(w for _, w in pos).replace("\n", " ")


def synergy(name: str = "Hall_2012") -> None:
    os.environ.setdefault("SYNERGY_SET", "synergy")     # v1.0: the full record set
    try:
        import synergy_dataset.base as base
    except ImportError:
        raise SystemExit("pip install synergy-dataset (into a throwaway venv is fine)")
    raw = DATA / "synergy" / "raw"
    src = raw / "synergy-dataset-1.0" / name
    if not (src / "labels.csv").exists():
        base.download_raw_subset(name, path=raw)
    labels = {}
    with open(src / "labels.csv", newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            labels[r["openalex_id"].lower()] = int(r["label_included"])
    rows = []
    for zpath in sorted(src.glob("works_*.zip")):
        with zipfile.ZipFile(zpath) as z:
            for member in z.namelist():
                for w in json.loads(z.read(member)):
                    wid = (w.get("id") or "").lower()
                    if wid in labels:
                        rows.append({"openalex_id": wid, "doi": w.get("doi") or "",
                                     "title": (w.get("title") or "").replace("\n", " "),
                                     "abstract": _abstract(w.get("abstract_inverted_index")),
                                     "publication_year": w.get("publication_year") or "",
                                     "label_included": labels[wid]})
    out = DATA / "synergy" / f"{name}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    inc = sum(r["label_included"] for r in rows)
    print(f"SYNERGY {name}: {len(rows)} records ({len(labels)} labelled), {inc} included -> {out}")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("scifact", "all"):
        scifact()
    if what in ("synergy", "all"):
        synergy()
