"""
Summary test runner that executes all query tests and generates a report
"""
import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    # Run all agent query tests
    exit_code = pytest.main([
        "tests/test_agent_queries.py",
        "-v",
        "--tb=short",
        "--durations=10",
    ])
    sys.exit(exit_code)

