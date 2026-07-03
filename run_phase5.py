"""Standalone execution script for Phase 5 (Gmail MCP Delivery)."""

import os
import sys
import click
from pulse.cli import deliver_email

if __name__ == "__main__":
    print("=" * 60)
    print("[*] WEEKLY PRODUCT REVIEW PULSE -- PHASE 5 RUNNER")
    print("=" * 60)
    print("[!] Tip: You can run this script with custom options:")
    print("    python run_phase5.py --email-mode draft\n")
        
    # Invoke CLI command
    try:
        deliver_email.main(args=sys.argv[1:] if len(sys.argv) > 1 else [], standalone_mode=False)
    except Exception as e:
        print(f"\nExecution finished: {e}")
