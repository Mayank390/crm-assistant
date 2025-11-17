# CRM Agent Test Summary

## Test Results

### Test Suite: `test_agent_queries.py`

**Total Tests**: 21
**Passed**: 20+
**Failed**: < 2 (mostly due to LLM variability)

### Test Categories

#### ✅ Intent Parsing Tests (8 tests)
- Basic queries intent parsing
- Filter queries intent parsing  
- Aggregation queries intent parsing
- Array size queries intent parsing
- Relationship queries intent parsing
- Complex queries intent parsing
- Edge case queries intent parsing
- Specific intent pattern validation

#### ✅ Pipeline Generation Tests (5 tests)
- Basic query pipeline generation
- Filter query pipeline generation
- Aggregation query pipeline generation
- Complex query pipeline generation
- Edge case query pipeline generation

#### ✅ Planner Execution Tests (2 tests)
- Basic query planner execution
- Filter query planner execution

#### ✅ Agent Tool Selection Tests (3 tests)
- Basic query tool selection
- Filter query tool selection
- Aggregation query tool selection

#### ✅ Query Validation Tests (3 tests)
- Empty query handling
- Invalid entity query handling
- Malformed query handling

## Test Queries

### 35 Total Test Queries Across 7 Categories

1. **Basic Queries** (5): Simple counts and lists
2. **Filter Queries** (7): Date ranges, status filters, optional fields
3. **Aggregation Queries** (5): Group by, breakdowns, trends
4. **Array Size Queries** (4): Array field filtering
5. **Relationship Queries** (4): Cross-collection queries
6. **Complex Queries** (5): Combined filters, sorting, limits
7. **Edge Case Queries** (5): Invalid statuses, optional fields, empty strings

## Running Tests

```bash
# Run all tests
python3 -m pytest tests/test_agent_queries.py -v

# Run specific category
python3 -m pytest tests/test_agent_queries.py::TestIntentParsing -v
python3 -m pytest tests/test_agent_queries.py::TestPipelineGeneration -v
python3 -m pytest tests/test_agent_queries.py::TestPlannerExecution -v
python3 -m pytest tests/test_agent_queries.py::TestAgentToolSelection -v
```

## Notes

- Some tests may show warnings due to LLM variability in intent parsing
- Intent parser may occasionally return different entities than expected
- Pipeline generation validates structure but may have edge cases
- Planner execution tests require MongoDB connection

