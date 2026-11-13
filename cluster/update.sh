#!/bin/bash
# Monthly update on the UZH ScienceCluster, run on the LOGIN node (has internet):
#   cd /path/to/duebendorf-gr-rag && bash cluster/update.sh
#
# 1. fetches new meetings, their audio and documents (login node)
# 2. submits the GPU job that transcribes everything still missing
# Afterwards copy data/ back to the app server and run there:
#   gr-rag update --only index summaries
set -euo pipefail
cd "$(dirname "$0")/.."
export GR_RAG_ROOT="$PWD"
export HF_HOME="$PWD/.hf_cache"

module load mamba 2>/dev/null || module load anaconda3 2>/dev/null || true
eval "$(conda shell.bash hook)"
conda activate gr-rag

gr-rag update --only scrape audio documents

missing=$(python - <<'PY'
import json
r = json.load(open("data/last_update.json"))
print(len(r.get("still_untranscribed", [])))
PY
)
if [ "$missing" -gt 0 ]; then
  gr-rag prefetch-model
  jobid=$(sbatch --parsable cluster/transcribe.slurm)
  echo "GPU-Job $jobid gestartet für $missing Sitzung(en). Fortschritt: tail -f logs/gr-whisper-$jobid.out"
else
  echo "Alle Sitzungen sind bereits transkribiert."
fi
