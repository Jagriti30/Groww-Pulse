"""Standalone execution script for Phase 6 (End-to-End Orchestrator, CLI & Ledger)."""

import sys
from pulse.cli import run

if __name__ == "__main__":
    print("=" * 60)
    print("[*] WEEKLY PRODUCT REVIEW PULSE -- PHASE 6 RUNNER")
    print("=" * 60)
    print("[!] Tip: You can run this script with custom options:")
    print("    python run_phase6.py --product groww --iso-week 2026-W27\n")
        
    # Invoke CLI command defaulting to --product groww if no args provided
    try:
        args = sys.argv[1:] if len(sys.argv) > 1 else ["--product", "groww"]
        run.main(args=args, standalone_mode=False)
    except Exception as e:
        print(f"\nExecution finished: {e}")
