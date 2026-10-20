"""Verify complete pinned public inputs and recovery after a cancelled request.

Only metadata is saved. Raw inputs/responses never leave the isolated local run.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from docker_scanner import docker, image_identity, write_private
from ru_llm_scanner.upstream import load_runtime_lock

FILES = {
    "authors.txt": "67b09ec1002aef944fec0a4c6ab76d5662e0f596f289e1c7b280c24cbb749678",
    "test_requests.py.txt": "4508b22c1aa65417427fe7e51ea1f4e3a3d43d3021acdeb5a5260720a1b367a1",
    "requests-logo.svg": "b1e7fd86516c1e925191a41ee1efdb2489654548c7756881c311f50b79233af0",
}

PROGRAM = r"""
import collections,hashlib,httpx,json,sys,time
p=json.load(sys.stdin);records=[]
with httpx.Client(trust_env=False,timeout=600) as client:
 for _ in range(1200):
  try:
   h=client.get('http://127.0.0.1:5001/api/v1/health',timeout=2)
   if h.status_code==200 and h.json().get('ner_state')=='ready':break
  except httpx.HTTPError:pass
  time.sleep(.1)
 else:raise RuntimeError('not_ready')
 assert h.json()['analysis_signature']==p['signature']
 for name in (() if p['cancel_only'] else ('authors.txt','test_requests.py.txt')):
  text=p['inputs'][name];started=time.monotonic()
  q=client.post('http://127.0.0.1:5001/api/v1/analyze',json={'text':text,'language':'ru','entities':None,'score_threshold':.35})
  if q.status_code!=200:
   detail=q.json().get('detail',{});raise RuntimeError('input_failed:'+name+':'+str({k:detail.get(k) for k in ('code','phase','failure_class')}))
  body=q.json();assert body['text']==text
  assert all(0<=e['start']<e['end']<=len(text) and text[e['start']:e['end']]==e['text'] for e in body['entities'])
  records.append({'input':name,'http_status':200,'seconds':round(time.monotonic()-started,3),'characters':len(text),'response_sha256':hashlib.sha256(q.content).hexdigest(),'findings':len(body['entities']),'categories':dict(collections.Counter(e['entity_type'] for e in body['entities'])),'full_echo_and_coordinates_verified':True})
 try:
  client.post('http://127.0.0.1:5001/api/v1/analyze',json={'text':p['inputs']['requests-logo.svg'],'language':'ru','entities':None,'score_threshold':.35},timeout=p['cancel_after'])
 except httpx.TimeoutException:pass
 else:raise RuntimeError('cancellation_not_exercised')
 started=time.monotonic();statuses=[];ready_states=[];rejections=[]
 while time.monotonic()-started<60:
  h=client.get('http://127.0.0.1:5001/api/v1/health',timeout=3)
  ready_states.append(h.json().get('ner_state'))
  assert h.status_code==200 and h.json()['analysis_signature']==p['signature']
  try:
   q=client.post('http://127.0.0.1:5001/api/v1/analyze',json={'text':'ordinary build notes','language':'ru','entities':None,'score_threshold':.35},timeout=3)
   statuses.append(q.status_code)
   if q.status_code==200:break
   assert q.status_code==503
   detail=q.json().get('detail',{});assert isinstance(detail,dict)
   rejections.append({k:detail.get(k) for k in ('code','reason')})
  except httpx.TimeoutException:statuses.append('client_timeout')
  time.sleep(.1)
 else:raise RuntimeError('capacity_did_not_recover')
 print(json.dumps({'inputs':records,'cancelled_svg_not_claimed_analyzed':True,'cancellation_timeout_seconds':p['cancel_after'],'subsequent_small_request_statuses':statuses,'capacity_rejections':rejections,'observed_ner_states':ready_states,'recovered_seconds':round(time.monotonic()-started,3),'final_health_ready':True}),flush=True)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--inputs-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpus", choices=("2", "8"), default="2")
    parser.add_argument("--cancel-only", action="store_true")
    parser.add_argument(
        "--cancel-after-seconds", type=float, choices=(0.1, 5.0), default=5.0
    )
    args = parser.parse_args()
    runtime = load_runtime_lock(args.runtime_lock, args.source_lock)
    assert (
        image_identity(runtime["image_reference_id"], runtime["platform"])
        == runtime["image_id"]
    )
    inputs = {}
    for name, expected in FILES.items():
        raw = (args.inputs_dir / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        inputs[name] = raw.decode("utf-8")
    owner = "rullmscan-inputs-" + uuid.uuid4().hex
    result = docker(
        "run",
        "--rm",
        "-d",
        "--name",
        owner,
        "--pull",
        "never",
        "--platform",
        runtime["platform"],
        "--network",
        "none",
        "--read-only",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--log-driver",
        "none",
        "--memory",
        "2g",
        "--cpus",
        args.cpus,
        "--tmpfs",
        "/tmp:rw,size=1g,mode=1777",
        runtime["image_reference_id"],
    )
    container = result.stdout.decode().strip()
    try:
        completed = subprocess.run(
            ["docker", "exec", "-i", container, "python", "-c", PROGRAM],
            input=json.dumps(
                {
                    "inputs": inputs,
                    "signature": runtime["runtime"]["analysis_signature"],
                    "cancel_only": args.cancel_only,
                    "cancel_after": args.cancel_after_seconds,
                }
            ).encode(),
            capture_output=True,
            timeout=1500,
        )
        if completed.returncode:
            raise RuntimeError(
                "pinned_input_verification_failed: "
                + completed.stderr.decode(errors="replace")[-1800:]
            )
        report = json.loads(completed.stdout)
        report.update(
            {
                "images": {k: runtime[k] for k in ("image_id", "image_reference_id")},
                "input_hashes": FILES,
                "network": "none",
                "analyzer_cpus": args.cpus,
                "values_published": False,
                "script_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
            }
        )
        write_private(args.output, report)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "complete_inputs": len(report["inputs"]),
                    "small_request_recovered": True,
                }
            )
        )
    finally:
        docker("rm", "-f", container, check=False)


if __name__ == "__main__":
    main()
