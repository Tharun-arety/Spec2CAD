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

`scripts/freeze_demo.py` runs the real pipeline for five evidence conditions and writes a
catalog plus everything the frontend needs to replay each one:

```
build/frozen/
  catalog.json                           five benchmark summaries
  scenarios/
    flanged-shaft-coupling/              text only; underspecified → clarified
    sheet-metal-enclosure/               sketch only; ambiguous → clarified
    motor-mount-bracket/                 text + sketch; conflict → repair
    hydraulic-manifold/                  sketch + document; entity linking
    blower-transition-duct/              all sources; infeasible → repair
      run.json                           evidence, reports, and revision state
      artifacts/                         STL, authorised STEP, generated script
      sources/                           the original recorded inputs
      previews/                          source highlights where available
  TOTAL                                  ~5.0 MB
```

The catalog includes nine CAD revisions in total. The coupling and enclosure
preserve blocked v1 geometry plus approved clarification-driven v2 models. The
motor bracket and duct preserve blocked v1 geometry plus approved engineering
repairs. The manifold releases while explicitly declining to claim a pressure
proof without material allowables and FEA.

**It is labelled as what it is.** Every scenario's `run.json` carries:

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

- No uploads. Only the five recorded runs replay.
- No new repairs. Only the motor-bracket width and duct-length approvals frozen
  at record time have resulting revisions.

Both limits follow from there being no kernel. Say so in the UI rather than
disabling the buttons without explanation.


---

# Deploying the backend on Render (free, no card)

Oracle and Cloud Run both require a card even to stay free. Render does not, and
neither does Railway. Between those two, Render gives **750 instance-hours a
month** against Railway's ~144 awake-hours ($1 of credit at 0.5 GB), and a cold
Render service **answers slowly** where Railway documents that a first request
to a slept service may return **502**. On a link handed to an employer,
"loading" beats "error", so: Render.

It is also x86, so unlike Oracle's ARM instances the existing `Dockerfile` needs
no Python version change.

## Sizing, measured

| | |
|---|---|
| CadQuery import alone | **328 MB**, 2.4 s |
| Peak during a full run + repair | **369 MB** |
| With uvicorn | ≈ **410 MB** against a 512 MB cap |

That is ~80% utilised. Fine for one visitor at a time, which is what a demo
needs; it is not headroom for concurrent geometry builds.

## Steps

1. Create a Render account and connect the GitHub repo. No card required.
2. Render reads `render.yaml` at the repo root and creates the `spec2cad-api`
   web service from it: Docker runtime, free plan, health check on `/health`.
3. Note the assigned URL, e.g. `https://spec2cad-api.onrender.com`.
4. Point the frontend at it by setting two build variables on the Vercel
   project, then redeploying:

   ```
   VITE_API_BASE=https://<your-service>.onrender.com
   VITE_REPLAY_FALLBACK=1
   ```

   Remove `VITE_REPLAY=1` from `vercel.json`'s build command when you do — that
   flag forces replay and ignores the backend entirely.

5. Optionally set `OPENAI_API_KEY` in the Render dashboard to turn on real
   sketch extraction. Without it the drawing falls back to its recorded
   fixture, labelled as such.

## What was fixed to make this work

- **The Dockerfile hardcoded port 8000.** Render injects `$PORT`; a fixed port
  fails the health check and the deploy rolls back. It now honours `${PORT:-8000}`.
- **CORS was hardcoded to localhost.** It now reads `SPEC2CAD_ALLOWED_ORIGINS`
  and additionally matches `https://spec2cad*.vercel.app` by regex, so preview
  deployments work too.

## Cold starts are shown, not hidden

A free instance sleeps after 15 minutes idle. The frontend polls `/health` on
load and renders a waking state with a running counter and an explanation of
why the wait exists, rather than a spinner that looks hung. If the backend never
answers within the budget, the user is **offered** the recorded replay as a
button -- it is never substituted silently, and the "Recorded replay" notice is
gated on actually being in replay mode.

## Keeping the replay bundle

`web/public/replay` stays in the repo. It is the fallback when the backend is
asleep, out of hours, or not deployed at all, and it is what a `VITE_REPLAY=1`
build serves. Regenerate and publish the complete catalog with
`python scripts/freeze_demo.py` whenever the pipeline output changes. Use
`--scenario <id> --no-publish` for an isolated local recording.
# Public launch guardrails

The API enforces per-client request bursts, per-client and global daily model-call
budgets, one concurrent CAD job, bounded uploads/prompts/conversations, and a
bounded in-memory B-Rep cache. Configure the `SPEC2CAD_*` values in `render.yaml`
for the desired public-demo budget. Keep `SPEC2CAD_USAGE_SALT` and
`SPEC2CAD_ADMIN_TOKEN` secret. The run-list endpoint is disabled when no admin
token is configured.

Also set a project-level monthly budget and alert in the OpenAI dashboard. The
application limits reduce abuse; the provider project budget is the final spend
ceiling if instances restart or application controls fail.
