#!/bin/bash
# One-off setup on the UZH ScienceCluster LOGIN node (has internet).
#   cd /path/to/duebendorf-gr-rag && bash cluster/setup.sh
#
# Does: conda env -> install package + CUDA libs -> scrape -> download audio
#       -> prefetch Whisper weights, so the GPU job itself needs no internet.
set -euo pipefail
cd "$(dirname "$0")/.."
export GR_RAG_ROOT="$PWD"
export HF_HOME="$PWD/.hf_cache"          # keep the ~3 GB model cache out of $HOME (small quota)

module load mamba 2>/dev/null || module load anaconda3 2>/dev/null || true
eval "$(conda shell.bash hook)"

if ! conda env list | grep -q "^gr-rag "; then
  conda create -y -n gr-rag python=3.11
fi
conda activate gr-rag

pip install -q --upgrade pip
pip install -q -e ".[transcribe,convert]"
# CTranslate2 (faster-whisper) GPU wheels need these CUDA 12 / cuDNN 9 libraries
pip install -q nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"

echo "== scrape meeting list (≈5 min, polite delays)"
[ -f data/meetings.json ] || gr-rag scrape --since 2023-01-01

echo "== download audio (~30 MB per meeting-hour)"
gr-rag download-audio || echo "!! YouTube download failed here - download on your Mac and copy data/audio/ over (see README)"

echo "== prefetch Whisper weights into $HF_HOME"
gr-rag prefetch-model

gr-rag status
echo
echo "Setup done. Submit the GPU job with:   sbatch cluster/transcribe.slurm"
