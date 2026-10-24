# Import a ComfyUI workflow as an app

`tools/import_workflow.py` turns a ComfyUI workflow into a draft Freefield app: `apps/<id>/app.json` and
`apps/<id>/workflow.api.json`. The draft passes `npm run validate`; you check what it guessed, then mark it ready.

```sh
python tools/import_workflow.py my_workflow.json --id my-app --name "My App"
python tools/import_workflow.py ui_workflow.json --id my-app --object-info object_info.json   # a UI workflow
```

The file can be in API format (*Export (API)* in ComfyUI) or a UI workflow with nodes and links. A UI workflow is
converted with `tools/ui2api.py`; when it uses a node that `tools/object_info.json` does not list, pass
`--object-info` with `GET /object_info` from a ComfyUI that has that node. `--section` (image, video, audio,
utility), `--out` (another folder) and `--force` (overwrite) are optional.

## What it reads from the graph

| In the workflow | In app.json |
|---|---|
| `LoadImage`, `LoadVideo`, `LoadAudio` | a required image, video or audio input |
| the words of a text encoder that reach a `positive` input, or the `PrimitiveString` node that feeds it | `prompt` |
| the same for `negative`, when it has words | `negative` |
| `seed` / `noise_seed` on samplers and noise nodes | one `seed` input that writes all of them |
| `steps` on samplers and schedulers | a slider from half to twice the value |
| literal `width`, `height`, `length` on an `Empty…Latent…` node | selects (768–1536) and a frames slider |
| `ResolutionSelector` | an aspect-ratio select with the node's options |
| `PrimitiveInt`, `PrimitiveFloat`, `PrimitiveBoolean` with a title | a slider or toggle labelled with the title |
| `Save…` nodes (`PreviewImage` becomes `SaveImage`) | outputs, saved under `freefield/<id>` |
| every loader value that ends in `.safetensors`, `.ckpt`, `.pt`, `.pth`, `.gguf`, `.bin` | models |

A model file that one of `packs/*.json` already lists gets its repo, path, size, folder, license and gate from
there, and its phase from the apps that use it. The pack is the existing one that holds every model; otherwise the
app gets a new pack named after its id. A file no pack lists gets `"repo": "TODO/unknown"` and a size of 0.001 GB,
and the report names it.

## Example

The official FLUX 3 Klein edit template, in UI format:

```
ui-test: 7 inputs, 1 outputs, 4 models → apps/ui-test
  inputs:
    - image (image) → 11.image
    - prompt (textarea) → 48.value
    - prompt2 (textarea) → 49.prompt
    - steps (slider) → 7.steps
    - width (select) → 44.width
    - height (select) → 44.height
    - seed (seed) → 7.seed
  outputs:
    - image ← 9 (SaveImage)
  models matched in packs/:
    - flux3-image-klein-int8-convrot.safetensors  black-forest-labs/flux-3-image-klein-comfy  5.83 GB  (denoise)
    - qwen3vl_4b_int8_convrot.safetensors  black-forest-labs/flux-3-image-klein-comfy  4.86 GB  (encode)
    - flux2-vae.safetensors  black-forest-labs/flux-3-image-klein-comfy  0.34 GB  (decode)
  models Freefield does not know:
    - qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors  (loaded by CLIPLoader 46.clip_name; folder guessed as text_encoders)
  check by hand:
    - converted from the UI format with object_info.json
  pack: ui-test (new: no existing pack holds every model)
  validator: 0 errors, 0 warnings
```

It exits 1 when the app does not validate, 2 on a bad id or an existing folder without `--force`.

## What it cannot know

- Which values a user should change. Every titled primitive becomes an input, frame rates and switches included;
  delete the ones that are internal.
- Which seed matters. All seed fields get the same input; a two-stage graph often wants only one of them.
- Prompts that are not literal text: words assembled by `StringConcatenate`, or a prompt-enhancer's own
  instructions, which show up as a second prompt (`prompt2` above).
- Where an unknown model comes from. Find the file on Hugging Face, fill `repo`, `file` and `gb`, then run
  `python tools/catalog.py all`; until then the new pack lists a TODO repo.
- Presets, gallery selects, templates around `{input}` values, credits and a showcase lab case: those are written
  by hand, as in the other apps.

Tests: `python test/import_workflow_test.py` imports `z-image`, `remove-bg`, `edit` and `video` and compares the
result with their hand-written app.json.
