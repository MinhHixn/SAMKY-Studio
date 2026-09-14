#!/bin/bash
#SBATCH --job-name=mirofish-hpc
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:4
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH --partition=gpu
#SBATCH --output=logs/hpc/%j.out
#SBATCH --error=logs/hpc/%j.err

# ==============================================================================
# MIROFISH HPC EXECUTION SCRIPT (GLiCID Optimized)
# Supports: vLLM, User-Space Neo4j, Local NVMe Scratch
# ==============================================================================

# 1. Environment Setup
MODEL_TAG=${1:-"default-model"}
AGENT_COUNT=${2:-60}
ROUND_COUNT=${3:-60}
INJECTION_STEP=$((ROUND_COUNT / 2))

SCRATCH_DIR="/scratch/local/$SLURM_JOB_ID"
mkdir -p "$SCRATCH_DIR/neo4j" "$SCRATCH_DIR/sqlite" "$SCRATCH_DIR/vllm"

echo "[HPC] Initializing job $SLURM_JOB_ID on $(hostname)"
echo "[HPC] Model: $MODEL_TAG | Agents: $AGENT_COUNT | Rounds: $ROUND_COUNT"

# 2. Boot Neo4j (User-Space)
NEO4J_HOME="/scratch/$USER/ecnbench/bin/neo4j-community-5.15.0"
export NEO4J_CONF="$SCRATCH_DIR/neo4j/conf"
mkdir -p "$NEO4J_CONF"
cp -r "$NEO4J_HOME/conf/"* "$NEO4J_CONF/"

# Apply Pagecache and Heap optimizations
sed -i "s/#server.memory.heap.initial_size=512m/server.memory.heap.initial_size=16G/" "$NEO4J_CONF/neo4j.conf"
sed -i "s/#server.memory.heap.max_size=512m/server.memory.heap.max_size=16G/" "$NEO4J_CONF/neo4j.conf"
sed -i "s/#server.memory.pagecache.size=10g/server.memory.pagecache.size=16G/" "$NEO4J_CONF/neo4j.conf"
echo "dbms.directories.data=$SCRATCH_DIR/neo4j/data" >> "$NEO4J_CONF/neo4j.conf"
echo "dbms.directories.logs=$SCRATCH_DIR/neo4j/logs" >> "$NEO4J_CONF/neo4j.conf"

echo "[HPC] Starting Neo4j..."
"$NEO4J_HOME/bin/neo4j" start

# 3. Boot vLLM (Zero-Copy Weights)
MODEL_PATH="/scratch/$USER/ecnbench/models/$MODEL_TAG"
echo "[HPC] Starting vLLM on $MODEL_PATH..."
apptainer exec --nv ecnbench.sif python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --tensor-parallel-size 4 \
    --max-model-len 1000000 \
    --port 8000 &
VLLM_PID=$!

# 4. Health Check Loop
echo "[HPC] Waiting for services to be ready..."
until curl -s http://localhost:8000/v1/models > /dev/null; do sleep 5; done
echo "[HPC] vLLM Ready."
until "$NEO4J_HOME/bin/neo4j" status > /dev/null; do sleep 2; done
echo "[HPC] Neo4j Ready."

# 5. Execute Simulation
export OPENROUTER_BASE_URL="http://localhost:8000/v1"
export NEO4J_URI="bolt://localhost:7687"
export OASIS_DB_DIR="$SCRATCH_DIR/sqlite"

echo "[HPC] Starting Simulation Protocol..."
apptainer exec --nv ecnbench.sif python3 scripts/run_ecnbench_protocol.py \
    --seeds-dir ../../data/seeds \
    --events-raw ../../data/events_raw.json \
    --output-dir "logs/benchmark_runs" \
    --model-tag "$MODEL_TAG" \
    --event-ids C9 \
    --repeats 1

# 6. Cleanup & Data Sync
echo "[HPC] Simulation finished. Cleaning up..."

# Ensure Python/SQLite finishes all WAL checkpoints
sleep 10 

# Stop Services
"$NEO4J_HOME/bin/neo4j" stop
kill $VLLM_PID

# Transfer results from NVMe to Project Storage
FINAL_DEST="/scratch/$USER/ecnbench/results/$MODEL_TAG/$SLURM_JOB_ID"
mkdir -p "$FINAL_DEST"
rsync -av "$SCRATCH_DIR/sqlite/" "$FINAL_DEST/sqlite/"
rsync -av "logs/benchmark_runs/$MODEL_TAG/" "$FINAL_DEST/reports/"

echo "[HPC] Job $SLURM_JOB_ID completed. Results synced to $FINAL_DEST"
