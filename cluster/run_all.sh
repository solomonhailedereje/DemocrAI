#!/bin/bash
# Whole pipeline on the UZH ScienceCluster, from the LOGIN node:
#   bash cluster/run_all.sh
# 1. new meetings, audio, documents (login node, internet)
# 2. GPU job: Whisper transcription of everything missing
# 3. GPU job: search index + summaries (starts when 2 has finished OK)
# Then copy data/ back to your computer (see README).
set -euo pipefail
cd "$(dirname "$0")/.."
export GR_RAG_ROOT="$PWD"
export HF_HOME="$PWD/.hf_cache"
mkdir -p logs

module load mamba 2>/dev/null || module load anaconda3 2>/dev/null || true
eval "$(conda shell.bash hook)"
conda activate gr-rag

gr-rag update --only scrape audio documents

missing=$(python -c "import json; print(len(json.load(open('data/last_update.json')).get('still_untranscribed', [])))")
dep=""
if [ "$missing" -gt 0 ]; then
  gr-rag prefetch-model
  tjob=$(sbatch --parsable cluster/transcribe.slurm)
  echo "Transcription job $tjob for $missing meeting(s)."
  dep="--dependency=afterok:$tjob"
fi
ljob=$(sbatch --parsable $dep cluster/llm.slurm)
echo "Index + summaries job $ljob ${dep:+(waits for $tjob)}."
echo "Progress: squeue -u \$USER ; tail -f logs/gr-*.out"
