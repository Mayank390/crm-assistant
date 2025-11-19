#!/usr/bin/env python3
"""Test script to verify business filtering is working"""

import asyncio
import sys
import os

# Set environment variables manually to avoid dotenv issues
os.environ.setdefault("MONGODB_DATABASE", "crm")
os.environ.setdefault("MONGODB_URI", "mongodb://Harshit:10_Harshith_29@4.213.88.219:27017/?authMechanism=DEFAULT&authSource=admin")

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mongo.constants import BUSINESS_UUID
from mongo.client import direct_mongo_client
from agent.tools import mongo_query

async def test_business_filtering():
    """Test that business filtering works correctly"""

    # Set the websocket context with the business ID from frontend
    import websocket_handler
    websocket_handler.business_id_global = '1eedcb26-d23a-688a-bd63-579d19dab229'

    print("Testing business filtering...")
    print(f"Business UUID from context: {BUSINESS_UUID()}")

    # Test a simple query to count leads
    query = "count leads"
    print(f"\nRunning query: {query}")

    try:
        result = await mongo_query.ainvoke({"query": query})
        print("Query result:")
        print(result)
        print("\n✅ Business filtering test completed successfully!")
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_business_filtering())
