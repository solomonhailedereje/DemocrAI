#!/bin/bash
# GPU transcription job for the UZH ScienceCluster.
#   sbatch cluster/transcribe.slurm        (from the project folder)
#   squeue -u $USER                        (check it's running)
#   tail -f logs/gr-whisper-<jobid>.out    (watch progress)
#
# ~80-100 h of audio at ~20-40x realtime on one GPU = roughly 3-5 h.
# The job is resumable: if it hits the time limit, just sbatch it again.
#
#SBATCH --job-name=gr-whisper
#SBATCH --gpus=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x-%j.out
# Optional: pin a GPU type if the default queue is slow, e.g.
# #SBATCH --constraint=A100

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
mkdir -p logs
export GR_RAG_ROOT="$PWD"
export HF_HOME="$PWD/.hf_cache"
export HF_HUB_OFFLINE=1                 # compute nodes may lack internet; weights were prefetched

module load gpu 2>/dev/null || true
module load mamba 2>/dev/null || module load anaconda3 2>/dev/null || true
eval "$(conda shell.bash hook)"
conda activate gr-rag

# Make the pip-installed cuBLAS / cuDNN visible to CTranslate2
NV=$(python -c "import nvidia, os; print(os.path.dirname(nvidia.__path__[0]))")/nvidia
export LD_LIBRARY_PATH="${NV}/cublas/lib:${NV}/cudnn/lib:${LD_LIBRARY_PATH:-}"

nvidia-smi --query-gpu=name,memory.total --format=csv
python -c "import ctranslate2; print('CUDA devices visible to CTranslate2:', ctranslate2.get_cuda_device_count())"

gr-rag convert-model          # one-off, skipped when models/ already exists
gr-rag transcribe             # device/compute_type 'auto' -> cuda + float16
gr-rag status
