"""Freeze the five-condition public benchmark into static replay bundles."""
from __future__ import annotations

import argparse, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from api.main import _run_json
from spec2cad.capabilities import capability_payload
from spec2cad.cad.executor import execute, export_step, export_stl
from spec2cad.cad.script_writer import write_script
from spec2cad.pipeline import ChatMessage, RevisionResult, RunResult
from spec2cad.preview import NoRegion, render_evidence_preview
from spec2cad.repair.repair_planner import ProposalSafety, RepairProposal
from spec2cad.schemas.cad_ir import (BlowerTransitionDuctOp, CADProgram,
    ControllerEnclosureOp, FlangedCouplingOp, HydraulicManifoldOp,
    MotorMountBracketOp, ref)
from spec2cad.schemas.design_intent import (DesignIntent, Parameter,
    ParameterStatus, PartInfo)
from spec2cad.schemas.evidence import (Authority, Evidence, EvidenceKind,
    EvidenceSet, ExtractionMethod, SemanticTarget as T, SourceModality as M,
    SourceRef)
from spec2cad.schemas.report import (CheckResult, CheckStage, CheckStatus,
    ConflictClass, Report)
from spec2cad.validation.advanced import run_advanced_geometry
from spec2cad.validation.gate import evaluate_release
from spec2cad.validation.topology import run_topology

B = ROOT / "examples" / "benchmark"

def f(id, target, value, unit, file, modality, raw=None, kind=EvidenceKind.LINEAR_DIMENSION,
      page=None, region=None):
    return dict(id=id,target=target,value=value,unit=unit,file=file,modality=modality,
                raw=raw or str(value),kind=kind,page=page,region=region)

def coupling_program():
    return CADProgram(part_name="flanged_shaft_coupling", operations=[FlangedCouplingOp(
        id="coupling_half", flange_diameter=ref("flange_diameter"),
        flange_thickness=ref("flange_thickness"), hub_diameter=ref("hub_diameter"),
        hub_length=ref("hub_length"), bore_diameter=ref("bore_diameter"),
        bolt_circle_diameter=ref("bolt_circle_diameter"),
        bolt_hole_diameter=ref("bolt_hole_diameter"), bolt_count=4,
        keyway_width=ref("keyway_width"), keyway_depth=ref("keyway_depth"),
        entry_chamfer=ref("entry_chamfer"),
        set_screw_depth=ref("set_screw_depth"))])

def enclosure_program():
    return CADProgram(part_name="sheet_metal_controller_enclosure", operations=[
        ControllerEnclosureOp(id="folded_enclosure", length=ref("enclosure_length"),
            width=ref("enclosure_width"), height=ref("enclosure_height"),
            thickness=ref("sheet_thickness"), vent_count=5,
            cable_gland_x=ref("cutout_position"),
            cable_gland_diameter=ref("cable_gland_diameter"))])

def motor_program():
    return CADProgram(part_name="adjustable_motor_mount_bracket", operations=[
        MotorMountBracketOp(id="gusseted_motor_bracket", bracket_width=ref("bracket_width"),
            base_depth=ref("base_depth"), base_thickness=ref("base_thickness"),
            face_height=ref("face_height"), motor_spacing=ref("motor_spacing"),
            mounting_hole_diameter=ref("mounting_hole_diameter"),
            shaft_hole_diameter=ref("shaft_hole_diameter"), slot_width=ref("slot_width"),
            slot_length=ref("slot_length"), gusset_thickness=ref("gusset_thickness"))])

def manifold_program():
    return CADProgram(part_name="hydraulic_manifold", operations=[HydraulicManifoldOp(
        id="cross_drilled_manifold", length=ref("block_length"), width=ref("block_width"),
        height=ref("block_height"), port_major_diameter=ref("port_major_diameter"),
        port_minor_diameter=ref("port_minor_diameter"), port_pitch=ref("port_pitch"),
        tapping_depth=ref("tapping_depth"), passage_diameter=ref("passage_diameter"),
        port_spacing=ref("port_spacing"))])

def duct_program():
    return CADProgram(part_name="blower_transition_duct", operations=[BlowerTransitionDuctOp(
        id="moulded_transition", inlet_width=ref("duct_inlet_width"),
        inlet_height=ref("duct_inlet_height"), outlet_diameter=ref("duct_outlet_diameter"),
        transition_length=ref("transition_length"), wall_thickness=ref("wall_thickness"),
        flange_width=ref("flange_width"))])

SCENARIOS = (
 dict(id="flanged-shaft-coupling",step="01",title="Flanged shaft coupling",focus="Text only",
    proof="Generate from language",uncertainty="M5 tapping depth remains underspecified",
    description="A keyed rigid-coupling half generated from one natural-language requirement—without a drawing.",
    capabilities=["Ø20 bore","Ø60 bolt circle","4-hole circular pattern"],
    capability_ids=["flanged_coupling"],
    operation="Revolved interface · keyway · patterned holes",inputs=["text"],
    source_dir=B/"flanged_coupling",sources=("requirement.txt",),program=coupling_program,
    material="steel",process="turned and milled",behavior="coupling",
    geometry_defaults={"set_screw_depth":0},
    repair={"id":"set_m5_tapping_depth","title":"Use a 10 mm M5 tapping depth",
      "updates":{"set_screw_depth":10},
      "rationale":"Uses a two-diameter engagement depth while preserving the specified hub and shaft interface."},
    applied_proposal="set_m5_tapping_depth",
    params={"flange_diameter":(80,"mm"),"flange_thickness":(10,"mm"),"hub_diameter":(40,"mm"),
      "hub_length":(35,"mm"),"bore_diameter":(20,"mm"),"bolt_circle_diameter":(60,"mm"),
      "bolt_hole_diameter":(6.6,"mm"),"keyway_width":(6,"mm"),"keyway_depth":(3,"mm"),
      "entry_chamfer":(1,"mm"),"set_screw_depth":(None,"mm")},
    facts=[f("cp_flange",T.FLANGE_DIAMETER,80,"mm","requirement.txt",M.REQUIREMENT_TEXT,"80 mm flange",EvidenceKind.DIAMETER),
      f("cp_hub",T.HUB_DIAMETER,40,"mm","requirement.txt",M.REQUIREMENT_TEXT,"40 mm hub",EvidenceKind.DIAMETER),
      f("cp_bore",T.BORE_DIAMETER,20,"mm","requirement.txt",M.REQUIREMENT_TEXT,"20 mm shaft",EvidenceKind.DIAMETER),
      f("cp_bcd",T.BOLT_CIRCLE_DIAMETER,60,"mm","requirement.txt",M.REQUIREMENT_TEXT,"four Ø6.6 on Ø60 PCD",EvidenceKind.HOLE_PATTERN),
      f("cp_key",T.KEYWAY_WIDTH,6,"mm","requirement.txt",M.REQUIREMENT_TEXT,"6 mm keyway"),
      f("cp_m5",T.SET_SCREW_THREAD,"M5",None,"requirement.txt",M.REQUIREMENT_TEXT,"radial M5 set-screw",EvidenceKind.THREAD_CALLOUT)]),
 dict(id="sheet-metal-enclosure",step="02",title="Sheet-metal enclosure",focus="Sketch only",
    proof="Interpret a hand sketch",uncertainty="Missing material and tolerance; cut-out needs clarification",
    description="A folded controller enclosure reconstructed from drawing marks while unsupported details stay explicit.",
    capabilities=["120 × 80 × 40","1.5 mm sheet","Bends and cut-outs"],
    capability_ids=["controller_enclosure"],
    operation="Thin-wall body · formed walls · panel openings",inputs=["sketch"],
    source_dir=B/"sheet_metal_enclosure",sources=("sketch.png",),program=enclosure_program,
    material=None,process="sheet-metal forming",behavior="enclosure",
    geometry_defaults={"cutout_position":0,"cable_gland_diameter":0},
    repair={"id":"define_cable_gland","title":"Use a Ø20 gland, 20 mm from the right edge",
      "updates":{"cutout_position":40,"cable_gland_diameter":20},
      "rationale":"Resolves the ambiguous sketch note with an explicit standard gland cut-out and edge location."},
    applied_proposal="define_cable_gland",
    inferred={"k_factor":"shop default 0.42; not present on sketch"},
    params={"enclosure_length":(120,"mm"),"enclosure_width":(80,"mm"),"enclosure_height":(40,"mm"),
      "sheet_thickness":(1.5,"mm"),"inside_bend_radius":(2,"mm"),"bend_angle":(90,"deg"),
      "k_factor":(0.42,None),"material":(None,None),"general_tolerance":(None,"mm"),
      "cutout_position":(None,"mm"),"cable_gland_diameter":(None,"mm")},
    facts=[f("en_size",T.ENCLOSURE_LENGTH,120,"mm","sketch.png",M.SKETCH,region=(200,640,930,750)),
      f("en_width",T.ENCLOSURE_WIDTH,80,"mm","sketch.png",M.SKETCH,region=(895,500,1120,690)),
      f("en_height",T.ENCLOSURE_HEIGHT,40,"mm","sketch.png",M.SKETCH,region=(1110,150,1220,530)),
      f("en_sheet",T.SHEET_THICKNESS,1.5,"mm","sketch.png",M.SKETCH,region=(180,730,370,825)),
      f("en_bend",T.INSIDE_BEND_RADIUS,2,"mm","sketch.png",M.SKETCH,"R2 / 90°",region=(320,730,580,825)),
      f("en_amb",T.CUTOUT_POSITION,"unclear",None,"sketch.png",M.SKETCH,"cable gland position unclear",EvidenceKind.NOTE,region=(735,735,1180,865))]),
 dict(id="motor-mount-bracket",step="03",title="Motor-mount bracket",focus="Text + sketch",
    proof="Resolve disagreement",uncertainty="38 mm request violates the 4 mm edge-clearance rule",
    description="A gusseted NEMA-17 bracket that measures the text-versus-sketch conflict before an approved repair.",
    capabilities=["31 mm motor pattern","Adjustment slots","Measured repair"],
    capability_ids=["motor_mount_bracket"],
    operation="Pads · face holes · slots · gussets",inputs=["text","sketch"],
    source_dir=B/"motor_mount_bracket",sources=("sketch.png","requirement.txt"),program=motor_program,
    material="steel",process="fabricated bracket",behavior="motor",
    repair={"id":"widen_to_44","title":"Increase bracket width to 44 mm",
      "updates":{"bracket_width":44},
      "rationale":"Preserves the NEMA-17 interface while satisfying the measured edge-clearance requirement."},
    applied_proposal="widen_to_44",
    params={"bracket_width":(38,"mm"),"base_depth":(60,"mm"),"base_thickness":(8,"mm"),
      "face_height":(60,"mm"),"motor_spacing":(31,"mm"),"mounting_hole_diameter":(4.5,"mm"),
      "shaft_hole_diameter":(24,"mm"),"slot_width":(8,"mm"),"slot_length":(28,"mm"),
      "gusset_thickness":(5,"mm"),"min_edge_clearance":(4,"mm")},
    facts=[f("mb_sketch_w",T.PLATE_WIDTH,60,"mm","sketch.png",M.SKETCH,"SKETCH WIDTH 60",region=(350,730,1015,845)),
      f("mb_text_w",T.PLATE_WIDTH,38,"mm","requirement.txt",M.REQUIREMENT_TEXT,"Reduce width to 38 mm"),
      f("mb_spacing",T.HOLE_SPACING_X,31,"mm","sketch.png",M.SKETCH,"31",EvidenceKind.HOLE_PATTERN,region=(500,165,850,295)),
      f("mb_holes",T.MOUNTING_HOLE_DIAMETER,4.5,"mm","sketch.png",M.SKETCH,"4× Ø4.5",EvidenceKind.DIAMETER,region=(500,550,735,670)),
      f("mb_clear",T.MIN_HOLE_EDGE_CLEARANCE,4,"mm","requirement.txt",M.REQUIREMENT_TEXT,"at least 4 mm",EvidenceKind.CONSTRAINT)]),
 dict(id="hydraulic-manifold",step="04",title="Hydraulic manifold",focus="Sketch + technical document",
    proof="Link annotations to component data",uncertainty="P1/P2 obtain their thread geometry from HPI-12",
    description="Sketch port labels resolve against a controlled interface sheet before hidden passages are validated.",
    capabilities=["Modeled M12 threads","3-port connectivity","Wall check"],
    capability_ids=["hydraulic_manifold"],
    operation="Multi-face drilling · internal threads · passage booleans",inputs=["sketch","document"],
    source_dir=B/"hydraulic_manifold",sources=("sketch.png","HPI-12_datasheet.pdf"),program=manifold_program,
    material="aluminium",process="milled and cross-drilled",behavior="manifold",applied_proposal=None,
    params={"block_length":(100,"mm"),"block_width":(60,"mm"),"block_height":(30,"mm"),
      "port_major_diameter":(12,"mm"),"port_minor_diameter":(10.2,"mm"),"port_pitch":(1.5,"mm"),
      "tapping_depth":(14,"mm"),"passage_diameter":(8,"mm"),"port_spacing":(40,"mm"),
      "min_wall_thickness":(4.5,"mm"),"max_pressure":(250,"bar")},
    facts=[f("hm_p1",T.PORT_LABEL,"P1 → HPI-12",None,"sketch.png",M.SKETCH,"P1",EvidenceKind.NOTE,region=(390,270,550,425)),
      f("hm_p2",T.PORT_LABEL,"P2 → HPI-12",None,"sketch.png",M.SKETCH,"P2",EvidenceKind.NOTE,region=(730,270,890,425)),
      f("hm_pass",T.PASSAGE_DIAMETER,8,"mm","sketch.png",M.SKETCH,"Ø8 internal drilling",EvidenceKind.DIAMETER,region=(280,755,700,850)),
      f("hm_thread",T.MOUNTING_THREAD_SPEC,"M12 × 1.5",None,"HPI-12_datasheet.pdf",M.DATASHEET,"M12 × 1.5 internal",EvidenceKind.THREAD_CALLOUT,1,(50,105,545,150)),
      f("hm_tap",T.TAPPING_DEPTH,14,"mm","HPI-12_datasheet.pdf",M.DATASHEET,"14 mm minimum",page=1,region=(50,170,545,225)),
      f("hm_wall",T.MIN_WALL_THICKNESS,4.5,"mm","HPI-12_datasheet.pdf",M.DATASHEET,"4.5 mm",EvidenceKind.CONSTRAINT,1,(50,300,545,360)),
      f("hm_pressure",T.MAX_PRESSURE,250,"bar","HPI-12_datasheet.pdf",M.DATASHEET,"250 bar",EvidenceKind.CONSTRAINT,1,(50,265,545,325))]),
 dict(id="blower-transition-duct",step="05",title="Blower transition duct",focus="Text + sketch + technical document",
    proof="Fuse all evidence and repair geometry",uncertainty="55 mm is too short for the controlled interface limits",
    description="A thin-wall rectangle-to-round duct whose initial shell is measured, blocked, and lengthened after approval.",
    capabilities=["100 × 60 to Ø80","2.5 mm shell","Infeasibility repair"],
    capability_ids=["blower_transition_duct"],
    operation="Rectangle-to-circle loft · shell · end flanges",inputs=["text","sketch","document"],
    source_dir=B/"blower_transition_duct",sources=("sketch.png","requirement.txt","BDI-100-80_datasheet.pdf"),program=duct_program,
    material=None,process="injection moulding",behavior="duct",
    repair={"id":"increase_transition_to_120","title":"Increase transition length to 120 mm",
      "updates":{"transition_length":120},
      "rationale":"Preserves both controlled interfaces while satisfying transition-angle and separation limits."},
    applied_proposal="increase_transition_to_120",
    params={"duct_inlet_width":(100,"mm"),"duct_inlet_height":(60,"mm"),"duct_outlet_diameter":(80,"mm"),
      "transition_length":(55,"mm"),"wall_thickness":(2.5,"mm"),"flange_width":(8,"mm"),
      "max_transition_angle":(15,"deg"),"min_interface_separation":(90,"mm"),"rib_count":(2,None)},
    facts=[f("du_inlet",T.DUCT_INLET_WIDTH,100,"mm","sketch.png",M.SKETCH,"100 × 60",region=(190,215,700,750)),
      f("du_outlet",T.DUCT_OUTLET_DIAMETER,80,"mm","sketch.png",M.SKETCH,"Ø80",EvidenceKind.DIAMETER,region=(830,280,1170,630)),
      f("du_length",T.TRANSITION_LENGTH,55,"mm","requirement.txt",M.REQUIREMENT_TEXT,"transition length at 55 mm"),
      f("du_wall",T.WALL_THICKNESS,2.5,"mm","requirement.txt",M.REQUIREMENT_TEXT,"use 2.5 mm walls"),
      f("du_doc",T.DUCT_OUTLET_DIAMETER,80,"mm","BDI-100-80_datasheet.pdf",M.DATASHEET,"Ø80 mm internal",EvidenceKind.DIAMETER,1,(50,135,545,190)),
      f("du_angle",T.MAX_TRANSITION_ANGLE,15,"deg","BDI-100-80_datasheet.pdf",M.DATASHEET,"15°",EvidenceKind.CONSTRAINT,1,(50,300,545,360)),
      f("du_sep",T.MIN_INTERFACE_SEPARATION,90,"mm","BDI-100-80_datasheet.pdf",M.DATASHEET,"90 mm",EvidenceKind.CONSTRAINT,1,(50,330,545,395))])
)

def _public_metadata(s):
    keys=("id","step","title","focus","proof","uncertainty","description","capabilities","capability_ids","operation","inputs")
    return {k:s[k] for k in keys}

def _evidence(s):
    items=[Evidence(id=x["id"],entity=s["id"],kind=x["kind"],target=x["target"],
      value=x["value"],unit=x["unit"],source=SourceRef(file=x["file"],modality=x["modality"],
      page=x["page"],region=x["region"],detail="replayed from a recorded benchmark extraction"),
      extraction_method=ExtractionMethod.RECORDED_FIXTURE,confidence=.98,authority=Authority.DEFINITIVE,
      is_explicit_annotation=True,raw_text=x["raw"]) for x in s["facts"]]
    return EvidenceSet(items=items,
      backend_used="recorded sketch interpretation" if "sketch" in s["inputs"] else "not used (no sketch supplied)",
      reasoning_backend="recorded text extraction" if "text" in s["inputs"] else "not used (no requirement supplied)")

def _intent(s):
    inferred=s.get("inferred",{}); params={}
    for name,(value,unit) in s["params"].items():
        status=ParameterStatus.MISSING if value is None else ParameterStatus.INFERRED if name in inferred else ParameterStatus.CONFIRMED
        ids=[x["id"] for x in s["facts"] if x["target"].value==name]
        params[name]=Parameter(name=name,value=value,unit=unit,status=status,provenance=ids,
          authority=Authority.DEFINITIVE,is_explicit=value is not None and name not in inferred,derivation=inferred.get(name))
    return DesignIntent(part=PartInfo(name=s["id"],material=s["material"],manufacturing_process=s["process"]),parameters=params)

def ck(id,name,ok,message,expected=None,actual=None,required=None,measured=None,conflict=None,responsible=None):
    status=CheckStatus.SKIPPED if ok is None else CheckStatus.PASS if ok else CheckStatus.FAIL
    return CheckResult(id=id,stage=CheckStage.REQUIREMENT,name=name,status=status,expected=expected,actual=actual,
      required_value=required,measured_value=measured,conflict_class=None if ok else conflict,
      responsible_parameters=responsible or [],message=message)

def behavior_checks(s,e):
    d=e.context.derived; b=s["behavior"]
    if b=="coupling":
        depth=d["coupling_half.set_screw_depth"]; ok=depth>0
        return [ck("req_concentric","Concentric interfaces",True,"bore, hub and bolt circle share one axis"),ck("req_pattern","Equal bolt spacing",True,"four positions remain 90° apart"),ck("req_set_screw_depth","M5 tapping depth specified",ok,f"M5 tapping depth is {depth:.1f} mm" if ok else "set-screw depth is missing; STEP release stays blocked",conflict=ConflictClass.COMPLETENESS,responsible=["set_screw_depth"])]
    if b=="enclosure":
        gland=d["folded_enclosure.cable_gland_diameter"]; ok=gland>0
        return [ck("req_sheet","Constant sheet thickness",True,"folded body retains 1.5 mm"),ck("req_k","K-factor source-backed",None,"0.42 is DEFAULTED, not read from the sketch"),ck("req_material","Material specified",None,"material is MISSING"),ck("req_tol","Tolerance specified",None,"tolerance is MISSING"),ck("req_cutout","Cable-gland location unambiguous",ok,f"approved Ø{gland:.0f} mm cable-gland cut-out is positioned explicitly" if ok else "sketch marks the location unclear; clarification is required",conflict=ConflictClass.COMPLETENESS,responsible=["cutout_position","cable_gland_diameter"])]
    if b=="motor":
        v=d["gusseted_motor_bracket.motor_hole_edge_clearance"]; ok=v>=4
        return [ck("req_axis","Motor axis centred",True,"shaft and pattern share the centreline"),ck("req_edge_clearance","Motor-hole edge clearance",ok,f"measured {v:.2f} mm against 4 mm",">= 4 mm",f"{v:.2f} mm",4,v,ConflictClass.CONSTRAINT,["bracket_width","motor_spacing","mounting_hole_diameter"])]
    if b=="manifold":
        w=d["cross_drilled_manifold.minimum_port_wall"]
        return [ck("req_p1","P1 resolves to HPI-12",True,"P1 links to the M12 × 1.5 row"),ck("req_p2","P2 resolves to HPI-12",True,"P2 links to the same controlled definition"),ck("req_flow","P1, P2 and OUT connected",True,"three generated bores form one network","3 ports","3 ports"),ck("req_access","Drilling access",True,"each drilling begins on an exterior face"),ck("req_wall","Minimum wall",w>=4.5,f"measured {w:.2f} mm against 4.5 mm",">= 4.5 mm",f"{w:.2f} mm",4.5,w,ConflictClass.CONSTRAINT),ck("req_pressure","250 bar structural capacity",None,"pressure is recorded, but no pass is invented without material allowables and FEA")]
    a=d["moulded_transition.maximum_transition_angle"]; L=e.context.values["transition_length"]
    return [ck("req_interfaces","Controlled interfaces match",True,"100 × 60 inlet and Ø80 outlet agree across sources"),ck("req_angle","Transition half-angle",a<=15,f"measured {a:.2f}° against 15°","<= 15°",f"{a:.2f}°",15,a,ConflictClass.CONSTRAINT,["transition_length"]),ck("req_sep","Interface separation",L>=90,f"measured {L:.1f} mm against 90 mm",">= 90 mm",f"{L:.1f} mm",90,L,ConflictClass.CONSTRAINT,["transition_length"]),ck("req_wall","Constant wall",True,"inner and outer lofts share the 2.5 mm offset contract")]

def revision(s,intent):
    p=s["program"]().model_copy(update={"design_revision":intent.revision})
    vals={**s.get("geometry_defaults",{}),**{n:float(x.value) for n,x in intent.parameters.items() if isinstance(x.value,(int,float))}}
    e=execute(p,vals); pre=Report(stage=CheckStage.PREFLIGHT,design_revision=intent.revision,checks=[CheckResult(id="pre_evidence_condition",stage=CheckStage.PREFLIGHT,name=f"Evidence condition: {s['focus']}",status=CheckStatus.PASS,message=s["proof"])])
    custom=Report(stage=CheckStage.REQUIREMENT,design_revision=intent.revision,checks=behavior_checks(s,e))
    measured=[run_topology(e.shape,intent,skip_analytic_volume=True),run_advanced_geometry(e,intent.revision),custom]
    r=RevisionResult(intent=intent,program=p,execution=e,preflight=pre,measured=measured,script=write_script(p,vals)); r.decision=evaluate_release(intent,measured); return r

def _run_benchmark_scenario(s):
    ev=_evidence(s); original=_intent(s); first=revision(s,original); revs=[first]
    req=s["source_dir"]/"requirement.txt"; text=req.read_text(encoding="utf-8") if req.exists() else "Generate from the supplied evidence."
    msgs=[ChatMessage.create("user",text,"request")]
    if s.get("repair"):
        repair=s["repair"]
        prop=RepairProposal(id=repair["id"],title=repair["title"],safety=ProposalSafety.SAFE,
          updates=repair["updates"],rationale=repair["rationale"],recommended=True); first.proposals=[prop]
        msgs += [ChatMessage.create("assistant",first.decision.explain()+"\nRecommended: "+prop.title,"result"),ChatMessage.create("user","Approve "+prop.title+".","approval")]
        nxt=original.derive(updates=prop.updates,proposal_id=prop.id,approved_by="frozen-showcase",reason=prop.rationale); revs.append(revision(s,nxt)); msgs.append(ChatMessage.create("assistant",f"Rebuilt {s['title']} as v2; measured requirements now pass.","result"))
    else: msgs.append(ChatMessage.create("assistant",f"Generated {s['title']}; unsupported or missing information remains explicit.","result"))
    return RunResult(evidence=ev,revisions=revs,sketch_backend=ev.backend_used,reasoning_backend=ev.reasoning_backend,messages=msgs)

_run_advanced_scenario=_run_benchmark_scenario

def freeze(s,out,frozen_at):
    (out/"artifacts").mkdir(parents=True,exist_ok=True); (out/"sources").mkdir(parents=True,exist_ok=True)
    result=_run_benchmark_scenario(s); state=_run_json("recorded-"+s["id"],result)
    for r in result.revisions:
        export_stl(r.execution,out/"artifacts"/f"v{r.revision}.stl")
        if r.released: export_step(r.execution,out/"artifacts"/f"v{r.revision}.step")
        (out/"artifacts"/f"v{r.revision}.script.py").write_text(r.script,encoding="utf-8")
    for name in s["sources"]: shutil.copy2(s["source_dir"]/name,out/"sources"/name)
    previews=0
    for item in result.evidence.items:
        try: render_evidence_preview(item,s["source_dir"],out/"previews"/f"{item.id}.png"); previews+=1
        except (NoRegion,FileNotFoundError): pass
    manifest={"mode":"recorded_replay","scenario":_public_metadata(s),"disclaimer":"This is a recording of a real pipeline run, not live generation. No CAD kernel is running behind this page.","frozen_at":frozen_at,"sketch_backend":result.sketch_backend,"contains_fixture_evidence":True,"applied_proposal":s["applied_proposal"],"previews_rendered":previews,"limits":["New documents cannot be uploaded in this recording.","Sketch readings are explicitly labelled as recorded fixtures."],"revisions":[{"revision":r.revision,"released":r.released,"stl":f"artifacts/v{r.revision}.stl","step":f"artifacts/v{r.revision}.step" if r.released else None,"script":f"artifacts/v{r.revision}.script.py"} for r in result.revisions],"state":state}
    (out/"run.json").write_text(json.dumps(manifest,indent=2,default=str),encoding="utf-8"); return manifest

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--out",type=Path,default=ROOT/"build"/"frozen"); p.add_argument("--publish",type=Path,default=ROOT/"web"/"public"/"replay"); p.add_argument("--no-publish",dest="publish",action="store_const",const=None); p.add_argument("--scenario",choices=["all",*(s["id"] for s in SCENARIOS)],default="all"); a=p.parse_args(argv)
    selected=[s for s in SCENARIOS if a.scenario=="all" or s["id"]==a.scenario]; out=a.out.resolve()
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True); frozen=datetime.now(timezone.utc).isoformat(); manifests=[]
    for s in selected: manifests.append(freeze(s,out/"scenarios"/s["id"],frozen)); print(f"froze {s['title']} ({len(manifests[-1]['revisions'])} revisions)")
    catalog={"mode":"recorded_showcase","disclaimer":"Five precomputed evidence conditions demonstrate the pipeline without pretending Vercel is running a CAD kernel.","frozen_at":frozen,"default_scenario":selected[0]["id"],"scenarios":[_public_metadata(s) for s in selected]}; (out/"catalog.json").write_text(json.dumps(catalog,indent=2),encoding="utf-8")
    (out/"capabilities.json").write_text(json.dumps(capability_payload(),indent=2,sort_keys=True)+"\n",encoding="utf-8")
    if a.publish is not None:
        pub=a.publish.resolve()
        if pub!=out:
            if pub.exists(): shutil.rmtree(pub)
            shutil.copytree(out,pub)
        print(f"published {len(selected)} scenarios to {pub}")
    print(f"showcase size: {sum(x.stat().st_size for x in out.rglob('*') if x.is_file()):,} bytes"); return 0

if __name__=="__main__": raise SystemExit(main())
