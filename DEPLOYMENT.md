# Deployment feasibility — go / no-go

A decision, taken against measured numbers rather than assumed ones.

## The constraint, measured

The blocker for hosting anything CadQuery-based is the OpenCascade binding. On
this machine:

| Package | Size | Note |
|---|---|---|
| `OCP` | **119 MB** | a single 118 MB native binary (`OCP.cp310-win_amd64.pyd`) |
| `vtkmodules` | 42 MB | pulled in by CadQuery; **unused here** — we export STEP/STL, not VTK |
| `cadquery` | 2 MB | pure Python |
| **Total** | **≈163 MB** | before numpy, FastAPI, PyMuPDF |

Those are the **Windows** figures, and they turned out to understate the problem
badly. The Linux wheel set with all transitive dependencies measures **1165 MB**
when Vercel actually builds it (see below). An early guess of "~500 MB" was
wrong in both directions: too pessimistic about the local install, far too
optimistic about a deployed one. Only the measured build settles it.

## What that rules in and out

| Target | Verdict | Why |
|---|---|---|
| Vercel / Netlify functions | **No — measured** | see below |
| AWS Lambda (zip) | **No** | 250 MB unzipped limit; the measured Linux bundle is 1165 MB |
| AWS Lambda (container) | Yes | 10 GB image limit; cold starts still poor |
| **Fly.io / Render / Railway / Cloud Run** | **Yes — recommended** | a plain container, warm process, no cold-start penalty on a 118 MB import |
| Static hosting (Sites) | Yes, for the **frontend only** | see the fallback below |

### Vercel, measured rather than estimated

Vercel was tried directly. Its zero-config detects `api/main.py` as a Python
serverless function, installs `requirements.txt`, and the build fails:

```
Error: Total bundle size (1165.12 MB) exceeds the maximum function size (500 MB).
```

**1165 MB** — the Linux wheel set with all transitive dependencies is far larger
than the 163 MB measured on Windows. There is no trimming that closes a 2.3x
overrun, so the backend is not a serverless workload on any provider with a
function size cap.

The frontend deploys there fine. `.vercelignore` excludes the entire Python side
so Vercel builds only the static bundle, and the deployment runs in replay mode
(`VITE_REPLAY=1`).

**Live: https://spec2cad.vercel.app**

**Decision: GO, via a container** for live generation. The backend is an ordinary long-running
FastAPI process, not a serverless function. Trimming `vtkmodules` would save a
further 42 MB but is not required and is not worth the compatibility risk for a
prototype.

The frontend is static (`npm run build` → `web/dist`) and can be served from a
private Sites deployment, pointed at the container's origin via `VITE_API_BASE`.

## Container

`Dockerfile` in the repo root builds the backend. It uses the Linux
`cadquery-ocp` wheel, so the 118 MB binary above is the Windows equivalent of
what lands in the image; expect a ~700 MB image after the Python base layer.

```bash
docker build -t spec2cad .
docker run -p 8000:8000 --env-file .env spec2cad
```

The image runs `generate_inputs.py` at build time so `POST /runs/demo` works
immediately.

## The precomputed fallback — defined, implemented, and deployed

If the container path is unavailable (no budget for an always-on host, or a
deployment target that only serves static files), the demo still ships. It does
**not** degrade into a mock.

`scripts/freeze_demo.py` runs the real pipeline once and writes everything a
frontend needs to replay it:

```
build/frozen/
  run.json                     49,926 B   evidence, BOTH revisions, all reports, proposals
  artifacts/v1.stl            128,484 B   the blocked candidate (provisional)
  artifacts/v2.stl            128,484 B   the released geometry
  artifacts/v2.step            53,177 B   the STEP the gate authorised
  artifacts/v{1,2}.script.py    1,102 B   the generated CadQuery for each revision
  sources/                                the three input documents
  previews/*.png (9 files)             9 source highlights, pre-rendered
  TOTAL                       ~529,000 B
```

529 KB. The entire v1 → conflict → approval → v2 → release flow, including both
meshes and the authorised STEP, served as static files with no CAD kernel
running.

**It is labelled as what it is.** `run.json` carries:

```json
"mode": "recorded_replay",
"disclaimer": "This is a recording of a pipeline run, not live generation. ..."
```

The frontend must surface that. A replay presenting itself as live generation
would misrepresent the one thing this project is about — being honest about what
the system actually did.

Note that `v1.stl` has no companion STEP in the bundle. That is not an
omission: the release gate blocked v1, so no STEP was ever produced for it, and
the frozen bundle preserves that rather than quietly including one.

## What the fallback cannot do

- No uploads. Only the recorded run replays.
- No new repairs. Only the proposal frozen at record time (`widen_to_recommended`)
  has a resulting revision.

Both limits follow from there being no kernel. Say so in the UI rather than
disabling the buttons without explanation.
