# CRM Agent Test Query List

This document contains all test queries used to validate the CRM Agent system.

## Query Categories

### 1. Basic Queries (5 queries)
Simple queries for basic functionality testing:

1. "How many leads are there?"
2. "Show me all leads with status New"
3. "List all tasks"
4. "Count all meetings"
5. "How many notes are in the system?"

### 2. Filter Queries (7 queries)
Queries testing various filtering capabilities:

1. "Show leads created in the last 7 days"
2. "Find high priority tasks assigned to John"
3. "Find leads with email containing @example.com"
4. "Show leads from website source"
5. "Find tasks with status COMPLETED"
6. "Show meetings scheduled for this week"
7. "Find call logs with status ANSWERED"

### 3. Aggregation Queries (5 queries)
Queries testing grouping and aggregation:

1. "Count leads by status"
2. "Break down tasks by status and priority"
3. "Show lead creation trends by month"
4. "Group meetings by meetingType"
5. "Count tasks by assignedName"

### 4. Array Size Queries (4 queries)
Queries testing array field filtering:

1. "Find leads with more than 5 field data entries"
2. "Show meetings with no participants"
3. "Find mail info with attachments"
4. "Show notes with attachments"

### 5. Relationship Queries (4 queries)
Queries testing cross-collection relationships:

1. "Show tasks with their lead names"
2. "Find all meetings for leads with status New"
3. "Show notes for leads created this month"
4. "Find call logs for leads with high score"

### 6. Complex Queries (5 queries)
Queries combining multiple features:

1. "Count tasks by priority for leads created this month"
2. "Show top 10 leads by score"
3. "Show first 5 tasks"
4. "Find leads with status New and score greater than 50"
5. "Show tasks assigned to John with high priority"

### 7. Edge Case Queries (5 queries)
Queries testing edge cases and error handling:

1. "Find leads with status INVALID"
2. "Show tasks with reminder days greater than 0"
3. "Find call logs with empty other reason"
4. "Show leads with source WEBSITE"
5. "Find tasks with assignToMailId"

## Total: 35 Test Queries

## Expected Behaviors

### Intent Parsing
- All queries should parse successfully into QueryIntent objects
- Primary entity should be correctly identified
- Filters should be extracted where applicable
- Group by fields should be identified for aggregation queries

### Pipeline Generation
- All valid intents should generate non-empty MongoDB aggregation pipelines
- Pipelines should be valid MongoDB aggregation syntax
- Filter queries should include $match stages
- Aggregation queries should include $group stages when group_by is present

### Planner Execution
- Planner should execute queries without errors
- Results should be returned in expected format
- Intent and pipeline should be included in results

### Agent Tool Selection
- Agent should select mongo_query tool for structured data queries
- Tool selection should work for all query types

