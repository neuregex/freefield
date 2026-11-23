"""Publish the lite copies made by lab/lite_modal.py on Hugging Face, one repo per model (lite/quantize.json).

    modal run lab/hf_publish_modal.py                    # whose account the "huggingface-write" secret has (nothing changes)
    modal run lab/hf_publish_modal.py --publish          # create the repos and upload copies, cards and licenses
    modal run lab/hf_publish_modal.py --publish --only LTX-2.5   # one repo (a piece of its name)

The token lives in a Modal secret you create, with write access to the account the repos go to:
    modal secret create huggingface-write HF_TOKEN=hf_...
Each repo gets README.md from lite/cards/<repo>.md, LICENSE from lite/licenses/ (the license of the model it comes
from) and its files under the folder ComfyUI loads them from (diffusion_models/, text_encoders/). Uploading runs on
a CPU container next to the models volume, so the files never travel through your computer.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from infra.common import MODELS_DIR, build_image, models_volume  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
app = modal.App("freefield-hf-publish")
image = build_image().add_local_python_source("infra")
hf_write = modal.Secret.from_name("huggingface-write")


@app.function(image=image, secrets=[hf_write], timeout=300)
def whoami() -> dict:
    from huggingface_hub import HfApi
    info = HfApi(token=os.environ["HF_TOKEN"]).whoami()
    auth = info.get("auth", {}).get("accessToken", {})
    return {"name": info.get("name"), "orgs": [o.get("name") for o in info.get("orgs", [])],
            "token_role": auth.get("role"), "token_name": auth.get("displayName")}


@app.function(image=image, volumes={"/models": models_volume}, secrets=[hf_write], timeout=4 * 3600, cpu=4, memory=8192)
def upload(repo: str, files: list[dict], card: str, license_text: str) -> dict:
    from huggingface_hub import HfApi
    api = HfApi(token=os.environ["HF_TOKEN"])
    repo_id = f"{api.whoami()['name']}/{repo}"
    for f in files:
        if not (Path(MODELS_DIR) / f["dir"] / f["name"]).exists():
            raise FileNotFoundError(f"{f['dir']}/{f['name']} is not in the volume: run lab/lite_modal.py --step quantize")
    api.create_repo(repo_id, repo_type="model", exist_ok=True)
    api.upload_file(path_or_fileobj=license_text.encode("utf-8"), path_in_repo="LICENSE", repo_id=repo_id,
                    commit_message="License of the model these files come from")
    for f in files:
        print(f"uploading {f['dir']}/{f['name']} to {repo_id} ...")
        api.upload_file(path_or_fileobj=str(Path(MODELS_DIR) / f["dir"] / f["name"]), path_in_repo=f"{f['dir']}/{f['name']}",
                        repo_id=repo_id, commit_message=f"Add {f['name']}")
    api.upload_file(path_or_fileobj=card.encode("utf-8"), path_in_repo="README.md", repo_id=repo_id,
                    commit_message="Model card")
    return {"repo": repo_id, "url": f"https://huggingface.co/{repo_id}", "files": [f"{f['dir']}/{f['name']}" for f in files]}


@app.local_entrypoint()
def main(publish: bool = False, only: str = ""):
    me = whoami.remote()
    print(f"huggingface-write: account {me['name']} (orgs: {', '.join(me['orgs']) or 'none'}), "
          f"token {me['token_name']!r} with role {me['token_role']}")
    if not publish:
        return
    spec = json.loads((ROOT / "lite" / "quantize.json").read_text(encoding="utf-8"))
    for repo, info in spec["repos"].items():
        if only and only.lower() not in repo.lower():
            continue
        card_path = ROOT / "lite" / "cards" / f"{repo}.md"
        if not card_path.exists():
            raise SystemExit(f"{card_path.relative_to(ROOT)} is missing: write the card first")
        files = [{"dir": f["dir"], "name": f["name"]} for f in spec["files"] if f["repo"] == repo]
        lic = (ROOT / "lite" / "licenses" / info["license"]["file"]).read_text(encoding="utf-8")
        out = upload.remote(repo, files, card_path.read_text(encoding="utf-8"), lic)
        print(f"  ✓ {out['url']}  ({len(out['files'])} files)")
