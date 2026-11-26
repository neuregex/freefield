"""Publish the lite copies made by lab/lite_modal.py on Hugging Face, one repo per model (lite/quantize.json).

    modal run lab/hf_publish_modal.py                    # whose account the "huggingface-write" secret has (nothing changes)
    modal run lab/hf_publish_modal.py --publish          # create the repos and upload copies, cards and licenses
    modal run lab/hf_publish_modal.py --publish --only LTX-2.5,Wan2.1   # some repos (pieces of their names, comma-separated)
    modal run lab/hf_publish_modal.py --publish --cards  # only README.md and LICENSE, for a card that changed

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


def hf_token() -> str:
    """The secret's token, without the spaces or line breaks a paste can bring along."""
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise RuntimeError('the "huggingface-write" secret has an empty HF_TOKEN: create it again with a write token '
                           "(modal secret create --force huggingface-write HF_TOKEN=...)")
    return token


@app.function(image=image, secrets=[hf_write], timeout=300)
def whoami() -> dict:
    from huggingface_hub import HfApi
    info = HfApi(token=hf_token()).whoami()
    auth = info.get("auth", {}).get("accessToken", {})
    return {"name": info.get("name"), "orgs": [o.get("name") for o in info.get("orgs", [])],
            "token_role": auth.get("role"), "token_name": auth.get("displayName")}


@app.function(image=image, volumes={"/models": models_volume}, secrets=[hf_write], timeout=4 * 3600, cpu=4, memory=8192)
def upload(repo: str, files: list[dict], card: str, license_text: str, cards_only: bool = False) -> dict:
    from huggingface_hub import HfApi
    api = HfApi(token=hf_token())
    repo_id = f"{api.whoami()['name']}/{repo}"
    for f in [] if cards_only else files:
        if not (Path(MODELS_DIR) / f["dir"] / f["name"]).exists():
            raise FileNotFoundError(f"{f['dir']}/{f['name']} is not in the volume: run lab/lite_modal.py --step quantize")
    api.create_repo(repo_id, repo_type="model", exist_ok=True)
    api.upload_file(path_or_fileobj=license_text.encode("utf-8"), path_in_repo="LICENSE", repo_id=repo_id,
                    commit_message="License of the model these files come from")
    for f in [] if cards_only else files:
        print(f"uploading {f['dir']}/{f['name']} to {repo_id} ...")
        api.upload_file(path_or_fileobj=str(Path(MODELS_DIR) / f["dir"] / f["name"]), path_in_repo=f"{f['dir']}/{f['name']}",
                        repo_id=repo_id, commit_message=f"Add {f['name']}")
    api.upload_file(path_or_fileobj=card.encode("utf-8"), path_in_repo="README.md", repo_id=repo_id,
                    commit_message="Model card")
    return {"repo": repo_id, "url": f"https://huggingface.co/{repo_id}", "files": [f"{f['dir']}/{f['name']}" for f in files]}


def owners() -> dict[str, str]:
    """repo → the account lite/variants.json downloads it from (the apps' lite versions look there)."""
    variants = json.loads((ROOT / "lite" / "variants.json").read_text(encoding="utf-8"))["variants"]
    return {v["repo"].split("/", 1)[1]: v["repo"].split("/", 1)[0] for v in variants.values() if v.get("source") == "freefield"}


@app.local_entrypoint()
def main(publish: bool = False, only: str = "", cards: bool = False):
    me = whoami.remote()
    print(f"huggingface-write: account {me['name']} (orgs: {', '.join(me['orgs']) or 'none'}), "
          f"token {me['token_name']!r} with role {me['token_role']}")
    spec = json.loads((ROOT / "lite" / "quantize.json").read_text(encoding="utf-8"))
    pieces = [p.strip().lower() for p in only.split(",") if p.strip()]
    chosen = [r for r in spec["repos"] if not pieces or any(p in r.lower() for p in pieces)]
    for r in chosen:
        if spec["repos"][r].get("publish") is False:   # lite/quantize.json: a copy that did not pass
            print(f"  skipping {r}: {spec['repos'][r].get('why_not', 'publish is false in lite/quantize.json')}")
    repos = [r for r in chosen if spec["repos"][r].get("publish", True)]
    if not repos:
        raise SystemExit(f"--only {only!r} matches nothing to publish among: {', '.join(spec['repos'])}")
    elsewhere = sorted({o for r, o in owners().items() if r in repos and o != me["name"]})
    if elsewhere:
        raise SystemExit(f"lite/variants.json downloads these repos from {', '.join(elsewhere)}, but the token is "
                         f"{me['name']}'s: change the owner there, or use a token of that account")
    for repo in repos:
        files = [f for f in spec["files"] if f["repo"] == repo]
        print(f"  {me['name']}/{repo}: " + ("README.md, LICENSE" if cards else
              ", ".join(f"{f['dir']}/{f['name']}" for f in files) + ", README.md, LICENSE"))
    if not publish:
        print("nothing uploaded: add --publish to upload these")
        return
    for repo in repos:
        info = spec["repos"][repo]
        card_path = ROOT / "lite" / "cards" / f"{repo}.md"
        if not card_path.exists():
            raise SystemExit(f"{card_path.relative_to(ROOT)} is missing: write the card first")
        files = [{"dir": f["dir"], "name": f["name"]} for f in spec["files"] if f["repo"] == repo]
        lic = (ROOT / "lite" / "licenses" / info["license"]["file"]).read_text(encoding="utf-8")
        out = upload.remote(repo, files, card_path.read_text(encoding="utf-8"), lic, cards_only=cards)
        what = "card" if cards else f"{len(out['files'])} files"
        print(f"  ✓ {out['url']}  ({what})")
