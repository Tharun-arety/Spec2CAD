"""The public UI must make model access and credential handling explicit."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_live_app_requires_an_explicit_access_choice():
    app = source("web/src/App.tsx")
    gate = source("web/src/components/AccessModeGate.tsx")

    assert "mode === 'live' && !accessSelected" in app
    assert "access-gate relative isolate h-full overflow-y-auto" in gate
    assert "Use the hosted demo" in gate
    assert "Use your own model API" in gate
    assert "provider charges and safeguards apply" in gate
    assert "Build" in gate and "CAD" in gate
    assert "Try Spec2CAD" in gate


def test_access_hero_connects_rotating_engineering_meaning_to_cad_proof():
    gate = source("web/src/components/AccessModeGate.tsx")
    proof = source("web/src/components/KineticCadProof.tsx")
    styles = source("web/src/styles.css")

    assert "term: 'Text'" in proof
    assert "term: 'Sketches'" in proof
    assert "term: 'Datasheets'" in proof
    assert "term: 'Mixed sources'" in proof
    assert "Grounded in" in gate
    assert "editable intent" in gate
    assert "Verified by" in gate and "measurement" in gate
    assert "Describe a part or attach" not in gate
    assert 'aria-label="Spec2CAD pipeline"' not in gate
    assert "prefers-reduced-motion: reduce" in proof
    assert "visibilitychange" in proof
    assert "IntersectionObserver" in proof
    assert "Pause proof" in proof and "Play proof" in proof
    assert "data-paused={paused}" in proof
    assert "illustrative evidence sequence" not in proof
    assert "Geometry appears." not in proof
    assert "EIG → Feature IR linked" in proof
    assert "geometry: 'coupling'" in proof
    assert "geometry: 'bracket'" in proof
    assert "geometry: 'enclosure'" in proof
    assert "geometry: 'plate'" in proof
    assert "proof-scene-leaders" in proof
    assert "proof-node-top-left" in styles
    assert "proof-node-top-right" in styles
    assert "proof-node-mid-left" in styles
    assert "proof-node-mid-right" in styles
    assert "proof-node-bottom-left" in styles
    assert "proof-node-bottom-right" in styles
    assert "proof-tone-success" in styles
    assert "Requirement" in proof and "Realization" in proof and "Observation" in proof
    assert "6800" in proof
    assert "proof-scene-lifecycle" in styles
    assert "proof-node-lifecycle" in styles
    assert "data-suspended={suspended}" in proof
    assert "sceneEpoch" in proof
    assert "aspect-ratio: 700 / 430" in styles
    assert gate.index("<KineticCadProof />") < gate.index("Try Spec2CAD")
    assert "setHeroFrame" in gate and "4200" in gate
    assert "const [frame, setFrame]" in proof
    assert "onFrameChange" not in proof
    assert '"copy proof"' in styles and '"access access"' in styles
    assert '"copy"' in styles and '"access"' in styles and '"proof"' in styles
    term_rule = styles[styles.index(".access-hero-term {"):styles.index("}", styles.index(".access-hero-term {"))]
    assert 'font-family: "IBM Plex Serif"' in term_rule
    assert "font-style: italic" in term_rule
    assert "font-size: clamp(58px, 5.55vw, 80px)" in term_rule
    assert "access-hero-term-long" not in styles
    mobile = styles[styles.index("@media (max-width: 639px)"):]
    assert "width: 100%" in mobile[mobile.index(".access-hero-term {"):mobile.index("}", mobile.index(".access-hero-term {"))]
    tablet = styles[styles.index("@media (min-width: 640px) and (max-width: 960px)"):]
    assert ".access-choice-grid > article > .grid" in tablet
    assert ".access-choice-grid > article button { width: 100%; }" in tablet


def test_access_page_mesh_is_decorative_bounded_and_reduced_motion_safe():
    mesh = source("web/src/components/EvidenceMesh.tsx")

    assert 'aria-hidden' in mesh
    assert "Math.min(window.devicePixelRatio || 1, 1.5)" in mesh
    assert "prefers-reduced-motion: reduce" in mesh
    assert "ResizeObserver" in mesh
    assert "window.cancelAnimationFrame(frame)" in mesh


def test_replay_bypasses_the_live_access_gate():
    app = source("web/src/App.tsx")

    assert "FORCED_REPLAY || state?.run_id.startsWith('recorded-')" in app


def test_model_credentials_have_no_storage_path_in_access_modules():
    connection = source("web/src/lib/modelConnection.ts")
    gate = source("web/src/components/AccessModeGate.tsx")
    fields = source("web/src/components/ModelConnectionFields.tsx")

    assert "localStorage" not in connection
    assert "localStorage" not in gate
    assert "localStorage" not in fields
    assert "The key is not saved with the run" in fields
    assert "never written to browser storage or run records" in gate


def test_agent_panel_uses_the_shared_connection_state():
    panel = source("web/src/components/AgentPanel.tsx")

    assert "modelSettings: ModelConnectionSettings" in panel
    assert "onModelSettingsChange" in panel
    assert "modelConnectionInput(modelSettings)" in panel


def test_recorded_catalog_load_is_not_gated_by_backend_fallback():
    app = source("web/src/App.tsx")
    effect_start = app.index("useEffect(() => {", app.index("loadReplayCatalog"))
    effect_end = app.index("}, [loadReplayCatalog, mode])", effect_start)
    effect = app[effect_start:effect_end]

    assert "void loadReplayCatalog()" in effect
    assert effect.index("void loadReplayCatalog()") < effect.index("if (REPLAY_AVAILABLE")


def test_recorded_catalog_failure_is_retryable_not_permanent_loading():
    showcase = source("web/src/components/ShowcaseWorkspace.tsx")
    replay = source("web/src/replay.ts")

    assert "Recorded workflows could not be loaded" in showcase
    assert "Retry examples" in showcase
    assert "catalogPromise = null" in replay


def test_generation_failure_preserves_the_user_draft_and_is_not_auto_retried():
    api = source("web/src/api.ts")
    app = source("web/src/App.tsx")
    panel = source("web/src/components/AgentPanel.tsx")

    assert "LIVE_REQUEST_TIMEOUT_MS = 75_000" in api
    assert "second paid model call or CAD revision" in api
    assert "X-Request-ID" in api
    assert "return true" in app and "return false" in app
    assert "if (succeeded) clear()" in panel
    assert "setInstruction('')" not in panel[panel.index("const submit"):panel.index("const clear")]


def test_recorded_assets_use_browser_and_edge_caches():
    replay = source("web/src/replay.ts")
    deployment = source("vercel.json")

    assert "cache: 'no-cache'" not in replay
    assert '"/assets/(.*)"' in deployment
    assert "max-age=31536000, immutable" in deployment
    assert "npm ci" in deployment


def test_workspace_brand_returns_to_access_choices_only_after_confirmation():
    app = source("web/src/App.tsx")
    shell = source("web/src/components/Shell.tsx")
    dialog = source("web/src/components/DiscardWorkspaceDialog.tsx")

    assert 'aria-label="Return to access options"' in shell
    assert "onHome={() => setReturnDialogOpen(true)}" in app
    assert "onConfirm={returnToAccessChoices}" in app
    assert "setAccessSelected(false)" in app
    assert "setMode('live')" in app
    assert 'role="alertdialog"' in dialog
    assert "This cannot be undone" in dialog
    assert "Stay here" in dialog
    assert "Leave workspace" in dialog
