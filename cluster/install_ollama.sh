#!/bin/bash
# One-off, on the UZH ScienceCluster LOGIN node (has internet):
#   bash cluster/install_ollama.sh [llm-model]
#
# Installs Ollama in user space (no root needed) and downloads the models,
# so the GPU job (cluster/llm.slurm) needs no internet.
set -euo pipefail
cd "$(dirname "$0")/.."
LLM_MODEL="${1:-qwen2.5:14b}"
OLLAMA_DIR="$PWD/.ollama"
export OLLAMA_MODELS="$OLLAMA_DIR/models"
mkdir -p "$OLLAMA_DIR" "$OLLAMA_MODELS"

if [ ! -x "$OLLAMA_DIR/bin/ollama" ]; then
  echo "== downloading Ollama (Linux amd64, includes CUDA libs)"
  # If this URL changes, see https://github.com/ollama/ollama/releases
  curl -fL https://ollama.com/download/ollama-linux-amd64.tgz | tar -xz -C "$OLLAMA_DIR"
fi
"$OLLAMA_DIR/bin/ollama" --version || true

# Short-lived server on the login node, only to pull model weights.
export OLLAMA_HOST=127.0.0.1:$((20000 + RANDOM % 20000))
"$OLLAMA_DIR/bin/ollama" serve > "$OLLAMA_DIR/pull.log" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT
for i in $(seq 1 30); do "$OLLAMA_DIR/bin/ollama" list >/dev/null 2>&1 && break; sleep 1; done

echo "== pulling bge-m3 (embeddings) and $LLM_MODEL (summaries)"
"$OLLAMA_DIR/bin/ollama" pull bge-m3
"$OLLAMA_DIR/bin/ollama" pull "$LLM_MODEL"
"$OLLAMA_DIR/bin/ollama" list
echo "Done. Models are in $OLLAMA_MODELS"
