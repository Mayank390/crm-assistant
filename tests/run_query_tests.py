#!/usr/bin/env python3
"""
Run all query tests and generate a summary report
"""
import subprocess
import sys
import os

def run_tests():
    """Run all agent query tests and display summary"""
    print("=" * 80)
    print("CRM Agent Query Test Suite")
    print("=" * 80)
    print()
    
    # Run pytest with verbose output
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_agent_queries.py",
            "-v",
            "--tb=short",
            "--durations=10",
        ],
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    print("=" * 80)
    print(f"Test execution completed with exit code: {result.returncode}")
    print("=" * 80)
    
    return result.returncode

if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)

