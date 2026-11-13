#!/bin/bash
# GPU job: search index + summaries with Ollama on the UZH ScienceCluster.
#   sbatch cluster/llm.slurm                         (default model qwen2.5:14b)
#   sbatch --export=ALL,LLM_MODEL=qwen2.5:32b cluster/llm.slurm
#   after transcription:  sbatch --dependency=afterok:<transcribe-jobid> cluster/llm.slurm
#
# Needs: bash cluster/install_ollama.sh (once, login node) with the same model.
# Resumable: the index only embeds new text, summaries skip finished meetings.
#
#SBATCH --job-name=gr-llm
#SBATCH --gpus=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x-%j.out

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
mkdir -p logs
export GR_RAG_ROOT="$PWD"
LLM_MODEL="${LLM_MODEL:-qwen2.5:14b}"

module load gpu 2>/dev/null || true
module load mamba 2>/dev/null || module load anaconda3 2>/dev/null || true
eval "$(conda shell.bash hook)"
conda activate gr-rag

# Ollama on a per-job port (compute nodes are shared with other users)
OLLAMA_DIR="$PWD/.ollama"
export OLLAMA_MODELS="$OLLAMA_DIR/models"
PORT=$((20000 + SLURM_JOB_ID % 20000))
export OLLAMA_HOST="127.0.0.1:$PORT"
"$OLLAMA_DIR/bin/ollama" serve > "logs/ollama-$SLURM_JOB_ID.log" 2>&1 &
OLLAMA_PID=$!
trap 'kill $OLLAMA_PID 2>/dev/null || true' EXIT
for i in $(seq 1 60); do curl -sf "http://$OLLAMA_HOST/api/tags" >/dev/null && break; sleep 2; done
nvidia-smi --query-gpu=name,memory.total --format=csv

# Point this cluster copy's config at the job's Ollama and the bigger model.
# (Backup in config.yaml.bak; only the cluster copy is changed.)
[ -f config.yaml.bak ] || cp config.yaml config.yaml.bak
python - "$PORT" "$LLM_MODEL" <<'PY'
import sys, yaml
port, model = sys.argv[1], sys.argv[2]
cfg = yaml.safe_load(open("config.yaml.bak"))
cfg["retrieval"]["ollama_url"] = f"http://127.0.0.1:{port}"
cfg["llm"]["model"] = model
yaml.safe_dump(cfg, open("config.yaml", "w"), allow_unicode=True, sort_keys=False)
print("ollama_url:", cfg["retrieval"]["ollama_url"], " llm:", model)
PY

gr-rag update --only index summaries
gr-rag status

cp config.yaml.bak config.yaml   # restore the original settings
