#!/usr/bin/env python3
"""
Fetch leads from MongoDB for a specific business and output as JSON.
"""

import json
import os
import sys
from pymongo import MongoClient
from bson.binary import Binary, UuidRepresentation
import uuid

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# MongoDB configuration
MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://Harshit:10_Harshith_29@4.213.88.219:27017/?authMechanism=DEFAULT&authSource=admin"
)
DATABASE_NAME = os.getenv("MONGODB_DATABASE", "crm")
BUSINESS_ID = "1eff7f64-09ef-670e-8c7c-2b9676f8dbb6"


def uuid_str_to_mongo_binary(uuid_str: str) -> Binary:
    """Convert canonical UUID string to Mongo Binary subtype 3 (legacy UUID)."""
    u = uuid.UUID(uuid_str)
    return Binary.from_uuid(u, uuid_representation=UuidRepresentation.JAVA_LEGACY)


def mongo_binary_to_uuid_str(binary: Binary) -> str:
    """Convert MongoDB Binary UUID (subtype 3) back to UUID string."""
    if isinstance(binary, Binary) and binary.subtype in (3, 4) and len(binary) == 16:
        try:
            uuid_obj = binary.as_uuid(uuid_representation=UuidRepresentation.JAVA_LEGACY)
            return str(uuid_obj)
        except Exception:
            pass
    return str(binary)


def fetch_leads():
    """Fetch all leads for the business from MongoDB."""
    client = MongoClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    
    # Convert business ID to binary for query
    business_binary = uuid_str_to_mongo_binary(BUSINESS_ID)
    
    # Query leads for this business
    lead_collection = db["Lead"]
    
    # Try different query approaches
    query = {"businessId": business_binary}
    
    leads = []
    cursor = lead_collection.find(query).limit(50)
    
    for doc in cursor:
        # Extract lead ID
        lead_id = doc.get("_id")
        if isinstance(lead_id, Binary):
            lead_id_str = mongo_binary_to_uuid_str(lead_id)
        else:
            lead_id_str = str(lead_id)
        
        # Extract personal info
        personal_info = doc.get("personalInfo", {})
        name = personal_info.get("name", "Unknown")
        email = personal_info.get("email", "")
        
        # Extract status
        status = doc.get("leadStatus", "UNKNOWN")
        
        leads.append({
            "leadId": lead_id_str,
            "name": name,
            "email": email,
            "status": status
        })
    
    client.close()
    return leads


def main():
    print(f"Fetching leads for business: {BUSINESS_ID}")
    print(f"MongoDB URI: {MONGODB_URI[:50]}...")
    print(f"Database: {DATABASE_NAME}")
    print()
    
    leads = fetch_leads()
    
    print(f"Found {len(leads)} leads")
    print()
    
    # Output as JSON
    output = json.dumps(leads, indent=2)
    print(output)
    
    # Also write to file
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "sidechat-plugin/public/business_leads.json"
    )
    with open(output_path, "w") as f:
        f.write(output)
    
    print(f"\nWritten to: {output_path}")


if __name__ == "__main__":
    main()
