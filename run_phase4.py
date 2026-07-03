"""Standalone execution script for Phase 4 (Google Docs MCP Delivery)."""

import os
import sys
import click
from pulse.cli import deliver_doc

if __name__ == "__main__":
    print("=" * 60)
    print("[*] WEEKLY PRODUCT REVIEW PULSE -- PHASE 4 RUNNER")
    print("=" * 60)
    
    # Check if doc_id was passed as argument or env var
    doc_id = os.environ.get("GOOGLE_DOC_ID")
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        doc_id = sys.argv[1]
        
    if not doc_id:
        print("[!] Tip: You can run this script with a target Google Doc ID:")
        print("    python run_phase4.py YOUR_GOOGLE_DOC_ID\n")
        
    # Invoke CLI command
    try:
        deliver_doc.main(args=sys.argv[1:] if len(sys.argv) > 1 else [], standalone_mode=False)
    except Exception as e:
        print(f"\nExecution finished: {e}")
