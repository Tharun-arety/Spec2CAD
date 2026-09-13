"""Freeze the full demo run into static assets.

This is the precomputed fallback described in DEPLOYMENT.md. It runs the whole
pipeline once and writes everything a frontend needs to replay it -- evidence,
both DesignIntent revisions, every report, the proposals, both meshes and the
authorised STEP -- so the UI can be hosted as static files with no backend and
no CAD kernel.

The output is explicitly labelled as a recording. `mode: "recorded_replay"` is
written into the manifest and the frontend is expected to surface it, because a
replay that presents itself as live generation is a lie about what the system
just did.

    python scripts/freeze_demo.py --out build/frozen
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from spec2cad.cad.executor import export_step, export_stl
from spec2cad.pipeline import repair, run
from spec2cad.preview import NoRegion, render_evidence_preview

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "motor_adapter"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="freeze_demo")
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "frozen")
    parser.add_argument("--proposal", default="widen_to_recommended")
    parser.add_argument("--backend", default=None,
                        help="force a sketch backend; default is auto-selected")
    args = parser.parse_args(argv)

    out = args.out
    (out / "artifacts").mkdir(parents=True, exist_ok=True)
    (out / "sources").mkdir(parents=True, exist_ok=True)

    # Import here so the API serialisers stay the single source of shape truth.
    from api.main import _run_json

    result = run(
        EXAMPLE / "sketch.png", EXAMPLE / "motor_datasheet.pdf",
        EXAMPLE / "requirement.txt", args.backend,
    )
    result = repair(result, args.proposal, approved_by="frozen-demo")

    state = _run_json("frozen", result)

    # Geometry for every revision; STEP only where the gate authorised it.
    for rev in result.revisions:
        if rev.execution is None:
            continue
        export_stl(rev.execution, out / "artifacts" / f"v{rev.revision}.stl")
        if rev.released:
            export_step(rev.execution, out / "artifacts" / f"v{rev.revision}.step")
        (out / "artifacts" / f"v{rev.revision}.script.py").write_text(
            rev.script, encoding="utf-8"
        )

    for name in ("sketch.png", "motor_datasheet.pdf", "requirement.txt"):
        shutil.copy2(EXAMPLE / name, out / "sources" / name)

    # Pre-render every highlight, using the same renderer the live API uses, so
    # click-to-trace keeps working with no server behind it.
    previews = 0
    for ev in result.evidence.items:
        try:
            render_evidence_preview(ev, EXAMPLE, out / "previews" / f"{ev.id}.png")
            previews += 1
        except (NoRegion, FileNotFoundError):
            continue        # rule-derived evidence has no region to point at

    manifest = {
        "mode": "recorded_replay",
        "disclaimer": (
            "This is a recording of a pipeline run, not live generation. No CAD "
            "kernel is running behind this page. The STEP offered is the frozen "
            "artifact that the release gate authorised at the time of recording."
        ),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "sketch_backend": result.sketch_backend,
        "contains_fixture_evidence": result.evidence.contains_fixture_data,
        "applied_proposal": args.proposal,
        "previews_rendered": previews,
        "limits": [
            "Only the recorded run replays; documents cannot be uploaded.",
            f"Only the {args.proposal!r} resolution has a rebuilt revision. The "
            f"other options are shown but cannot be applied without a CAD kernel.",
        ],
        "revisions": [
            {
                "revision": rev.revision,
                "released": rev.released,
                "stl": f"artifacts/v{rev.revision}.stl",
                "step": f"artifacts/v{rev.revision}.step" if rev.released else None,
                "script": f"artifacts/v{rev.revision}.script.py",
            }
            for rev in result.revisions
        ],
        "state": state,
    }
    (out / "run.json").write_text(json.dumps(manifest, indent=2, default=str),
                                  encoding="utf-8")

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"froze {len(result.revisions)} revisions to {out}")
    for f in sorted(out.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(out).as_posix():34s} {f.stat().st_size:>9,} bytes")
    print(f"  {'TOTAL':34s} {total:>9,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
