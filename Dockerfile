# Freefield in one image: ComfyUI at the pinned commit with the pinned custom nodes, comfy-api-proxy, the gateway and
# the web studio. For a GPU rented by the hour (RunPod, Vast.ai) or any Docker host with an NVIDIA GPU.
# Model weights never go in the image: infra/pod.py downloads the packs you ask for into the volume at start.
#
#   docker build -t freefield .
#   docker run --gpus all -p 3000:3000 -v freefield:/workspace -e HF_TOKEN=hf_... freefield
#
# Published as ghcr.io/neuregex/freefield by .github/workflows/image.yml. Guide: docs/cloud-gpus.md.
#
# TORCH_INDEX empty = PyTorch from PyPI, the same build Modal's image gets (CUDA 13: NVIDIA driver 580 or newer).
# CI builds a CPU image with TORCH_INDEX=https://download.pytorch.org/whl/cpu and TUNNEL=0 for its smoke test.

FROM node:22-bookworm-slim AS studio
WORKDIR /freefield
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM python:3.12-slim-bookworm
ARG TORCH_INDEX=""
ARG TUNNEL=1
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore \
    FREEFIELD_DATA=/workspace/freefield

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ffmpeg libgl1 libglib2.0-0 ca-certificates curl gnupg \
 && if [ "$TUNNEL" = "1" ]; then \
      curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg \
      && echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared bookworm main" \
         > /etc/apt/sources.list.d/cloudflared.list \
      && apt-get update && apt-get install -y --no-install-recommends cloudflared; \
    fi \
 && rm -rf /var/lib/apt/lists/*
COPY --from=studio /usr/local/bin/node /usr/local/bin/node

# PyTorch before ComfyUI's requirements, so they find it already there
RUN pip install torch torchvision torchaudio ${TORCH_INDEX:+--index-url "$TORCH_INDEX"}

# ComfyUI + custom nodes + comfy-api-proxy, exactly as tools/local_backend.py setup does on your own machine.
# Only the files that pin them are copied first, so a code change does not rebuild this layer.
COPY infra/common.py /freefield/infra/common.py
COPY packs /freefield/packs
COPY tools/local_backend.py /freefield/tools/local_backend.py
RUN python /freefield/tools/local_backend.py setup /comfyui --models /workspace/freefield/models

COPY --from=studio /freefield/node_modules /freefield/node_modules
COPY . /freefield
WORKDIR /freefield

EXPOSE 3000 8000
CMD ["python", "/freefield/infra/pod.py"]
