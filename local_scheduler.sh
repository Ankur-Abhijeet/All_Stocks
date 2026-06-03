#!/usr/bin/env bash
# local_scheduler.sh
# This script simulates the GitHub Actions weekly cron schedule locally for testing.
# It runs the Phase 1 ingestion pipeline (Fetcher -> Extractor -> Cleaner -> Chunker -> Embedder -> Indexer)
# and repeats the cycle every 60 seconds (for testing purposes only).

export PYTHONPATH=src

echo "=========================================================="
echo "🚀 Starting Local Test Scheduler"
echo "=========================================================="
echo "This will run the ingestion pipeline every 60 seconds."
echo "Press Ctrl+C to stop."
echo "=========================================================="
echo ""

while true; do
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Triggering ingestion pipeline..."
    
    # Run the refresh orchestrator (Phases 1.1 through 1.6)
    python3 -m mf_faq.ingestion.phase_1_7_refresh.refresh
    
    if [ $? -eq 0 ]; then
        echo "✅ Pipeline run completed successfully!"
    else
        echo "❌ Pipeline run failed! (Check logs above for details)"
    fi
    
    echo "=========================================================="
    echo "Waiting 60 seconds before next run... (Simulating cron)"
    echo "=========================================================="
    sleep 60
done
