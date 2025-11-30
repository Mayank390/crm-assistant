#!/usr/bin/env python3
"""
Complete CRM data import script with leadId mapping
Creates leads first, then uses actual CRM leadIds for related data
"""

import json
import requests
import time
import os

# Read the JSON files
script_dir = os.path.dirname(os.path.abspath(__file__))
json_dir = script_dir  # JSON files are in the same directory

with open(os.path.join(json_dir, 'leads.json'), 'r') as f:
    leads = json.load(f)

with open(os.path.join(json_dir, 'meetings.json'), 'r') as f:
    meetings = json.load(f)

with open(os.path.join(json_dir, 'calls.json'), 'r') as f:
    calls = json.load(f)

with open(os.path.join(json_dir, 'tasks.json'), 'r') as f:
    tasks = json.load(f)

print(f'Loaded {len(leads)} leads, {len(meetings)} meetings, {len(calls)} calls, {len(tasks)} tasks')

# Map to store old leadId -> new leadId
lead_id_mapping = {}

# Simpo CRM Production API endpoints
BASE_URL = 'https://api.simpo.ai'
LEADS_URL = f'{BASE_URL}/crm/leads'
MEETING_URL = f'{BASE_URL}/crm/meeting/create'
CALL_URL = f'{BASE_URL}/crm/call/create'
TASK_URL = f'{BASE_URL}/crm/task/create'

# Add your authentication headers here
# For Simpo CRM Production Environment
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer YOUR_JWT_TOKEN_HERE',  # Get this from TokenService.getToken() or your CRM dashboard
}

# Create leads (special handling to capture returned leadIds)
def create_leads(leads_list):
    print(f'\nCreating Leads...')
    success_count = 0
    error_count = 0

    for i, lead in enumerate(leads_list):
        try:
            response = requests.post(LEADS_URL, json=lead, headers=headers, timeout=30)
            if response.status_code in [200, 201, 202]:
                print(f'Lead {i+1}: ✓ Success ({response.status_code})')

                # Try to extract the actual leadId from response
                try:
                    response_data = response.json()
                    # The API returns the lead ID nested under 'data.id'
                    if 'data' in response_data and 'id' in response_data['data']:
                        actual_lead_id = response_data['data']['id']
                        old_lead_id = lead['leadId']
                        lead_id_mapping[old_lead_id] = actual_lead_id
                        print(f'  Mapped leadId: {old_lead_id} -> {actual_lead_id}')
                    elif 'leadId' in response_data:
                        actual_lead_id = response_data['leadId']
                        old_lead_id = lead['leadId']
                        lead_id_mapping[old_lead_id] = actual_lead_id
                        print(f'  Mapped leadId: {old_lead_id} -> {actual_lead_id}')
                    elif 'id' in response_data:
                        actual_lead_id = response_data['id']
                        old_lead_id = lead['leadId']
                        lead_id_mapping[old_lead_id] = actual_lead_id
                        print(f'  Mapped leadId: {old_lead_id} -> {actual_lead_id}')
                    else:
                        print(f'  Could not extract leadId from response: {response_data}')
                except json.JSONDecodeError:
                    print(f'  Could not parse JSON response: {response.text[:100]}')
                except Exception as e:
                    print(f'  Error extracting leadId: {e}')

                success_count += 1
            else:
                print(f'Lead {i+1}: ✗ Error {response.status_code} - {response.text[:100]}')
                error_count += 1
        except Exception as e:
            print(f'Lead {i+1}: ✗ Exception - {str(e)}')
            error_count += 1

        time.sleep(0.5)  # Rate limiting

    print(f'Leads creation completed: {success_count} success, {error_count} errors')
    return success_count > 0

# Create data with leadId mapping
def create_data_with_mapping(endpoint, data_list, data_type):
    print(f'\nCreating {data_type}...')
    success_count = 0
    error_count = 0

    for i, item in enumerate(data_list):
        # Update leadId if it exists in the mapping
        updated_item = item.copy()
        if 'leadId' in updated_item and updated_item['leadId'] in lead_id_mapping:
            old_id = updated_item['leadId']
            new_id = lead_id_mapping[old_id]
            updated_item['leadId'] = new_id
            print(f'{data_type} {i+1}: Updated leadId {old_id} -> {new_id}')

        # Update parentId for tasks if it exists
        if 'parentId' in updated_item and updated_item['parentId'] in lead_id_mapping:
            old_id = updated_item['parentId']
            new_id = lead_id_mapping[old_id]
            updated_item['parentId'] = new_id
            print(f'{data_type} {i+1}: Updated parentId {old_id} -> {new_id}')

        # Update leadName if needed
        if 'leadName' in updated_item and 'leadId' in updated_item and updated_item['leadId'] in lead_id_mapping:
            # Keep the original leadName for now, as it should match
            pass

        try:
            response = requests.post(endpoint, json=updated_item, headers=headers, timeout=30)
            if response.status_code in [200, 201, 202]:
                print(f'{data_type} {i+1}: ✓ Success ({response.status_code})')
                success_count += 1
            else:
                print(f'{data_type} {i+1}: ✗ Error {response.status_code} - {response.text[:100]}')
                error_count += 1
        except Exception as e:
            print(f'{data_type} {i+1}: ✗ Exception - {str(e)}')
            error_count += 1

        time.sleep(0.5)  # Rate limiting

    print(f'{data_type} creation completed: {success_count} success, {error_count} errors')

# Create data in proper order with dependency handling
if create_leads(leads):
    print(f'\n📋 Lead ID mapping created: {len(lead_id_mapping)} mappings')
    create_data_with_mapping(MEETING_URL, meetings, 'Meetings')
    create_data_with_mapping(CALL_URL, calls, 'Calls')
    create_data_with_mapping(TASK_URL, tasks, 'Tasks')
else:
    print('\n❌ Lead creation failed. Cannot create dependent records (meetings, calls, tasks).')

print('\nAll data creation completed!')
