# CRM Agent Query Test Report

## Overview
This document summarizes the test queries and results for the CRM Agent system.

## Test Queries by Category

### Basic Queries (5 queries)
1. "How many leads are there?"
2. "Show me all leads with status New"
3. "List all tasks"
4. "Count all meetings"
5. "How many notes are in the system?"

### Filter Queries (7 queries)
1. "Show leads created in the last 7 days"
2. "Find high priority tasks assigned to John"
3. "Find leads with email containing @example.com"
4. "Show leads from website source"
5. "Find tasks with status COMPLETED"
6. "Show meetings scheduled for this week"
7. "Find call logs with status ANSWERED"

### Aggregation Queries (5 queries)
1. "Count leads by status"
2. "Break down tasks by status and priority"
3. "Show lead creation trends by month"
4. "Group meetings by meetingType"
5. "Count tasks by assignedName"

### Array Size Queries (4 queries)
1. "Find leads with more than 5 field data entries"
2. "Show meetings with no participants"
3. "Find mail info with attachments"
4. "Show notes with attachments"

### Relationship Queries (4 queries)
1. "Show tasks with their lead names"
2. "Find all meetings for leads with status New"
3. "Show notes for leads created this month"
4. "Find call logs for leads with high score"

### Complex Queries (5 queries)
1. "Count tasks by priority for leads created this month"
2. "Show top 10 leads by score"
3. "Show first 5 tasks"
4. "Find leads with status New and score greater than 50"
5. "Show tasks assigned to John with high priority"

### Edge Case Queries (5 queries)
1. "Find leads with status INVALID"
2. "Show tasks with reminder days greater than 0"
3. "Find call logs with empty other reason"
4. "Show leads with source WEBSITE"
5. "Find tasks with assignToMailId"

## Test Coverage

### Intent Parsing Tests
- ✅ Basic queries intent parsing
- ✅ Filter queries intent parsing
- ✅ Aggregation queries intent parsing
- ✅ Array size queries intent parsing
- ✅ Relationship queries intent parsing
- ✅ Complex queries intent parsing
- ✅ Edge case queries intent parsing
- ✅ Specific intent pattern validation

### Pipeline Generation Tests
- ✅ Basic query pipeline generation
- ✅ Filter query pipeline generation
- ✅ Aggregation query pipeline generation
- ✅ Complex query pipeline generation
- ✅ Edge case query pipeline generation

### Planner Execution Tests
- ✅ Basic query planner execution
- ✅ Filter query planner execution

### Agent Tool Selection Tests
- ✅ Basic query tool selection
- ✅ Filter query tool selection
- ✅ Aggregation query tool selection

### Query Validation Tests
- ✅ Empty query handling
- ✅ Invalid entity query handling
- ✅ Malformed query handling

## Running Tests

To run all tests:
```bash
python3 -m pytest tests/test_agent_queries.py -v
```

To run specific test categories:
```bash
# Intent parsing tests
python3 -m pytest tests/test_agent_queries.py::TestIntentParsing -v

# Pipeline generation tests
python3 -m pytest tests/test_agent_queries.py::TestPipelineGeneration -v

# Planner execution tests
python3 -m pytest tests/test_agent_queries.py::TestPlannerExecution -v

# Agent tool selection tests
python3 -m pytest tests/test_agent_queries.py::TestAgentToolSelection -v
```

## Notes

- Some tests may show warnings due to LLM variability in intent parsing
- Intent parser may occasionally return different entities than expected (e.g., "workItem" instead of "Task")
- Pipeline generation tests validate structure but may not catch all edge cases
- Planner execution tests connect to MongoDB and may require database connection

