# Amendments to Graph Modeling Plan

These amendments refine the existing plan to fix critical issues in graph modeling, relationship mapping, and query correctness.

The goal is NOT to redesign the system, but to correct specific flaws while preserving current architecture.

---

## 1. Fix Node Identity for JournalEntry and Payment

### Change

Replace composite keys with single-field identifiers:

- JournalEntry → `accountingDocument`
- Payment → `accountingDocument`

Keep other fields as node properties.

### Why

- Composite keys break matching in Cypher
- Increase risk of duplicate nodes
- Complicate relationship creation and multi-hop queries

---

## 2. Introduce Field Alias Normalization

### Change

Add a normalization layer before node/edge creation:

Example mapping:

- `material` → `product`
- `product_id` → `product`
- `soldToParty` → `businessPartner`
- `plant` → `plant`

Apply before:
- node creation
- relationship matching

### Why

- Column names vary across tables
- Prevents silent join failures
- Ensures consistent graph construction

---

## 3. Improve DISTINCT Query Handling

### Change

Enhance property selection logic:

If property is missing or invalid:

Use preferred fields:

- Plant → `plantName`, `plantCategory`
- Product → `productCategory`, `productGroup`
- Customer → `customerGroup`

Fallback:
- first low-cardinality string field

### Why

- LLM may select incorrect property (e.g., ID)
- Ensures meaningful aggregation results

---

## 4. Enforce Strict FK-Based Relationship Validation

### Change

Before creating relationships:

- Validate source column exists
- Validate target column exists
- Validate type compatibility
- Validate non-zero overlap

Skip relationship if validation fails.

### Why

- Prevents incorrect joins
- Replaces removed Jaccard-based inference safely
- Avoids graph corruption

---

## 5. Disable Schema Inference by Default

### Change

Add flag:


USE_SCHEMA_INFERENCE = False


Only use curated schema unless explicitly enabled.

### Why

- Schema inference caused incorrect edges
- Reduces noise and instability
- Ensures deterministic graph

---

## 6. Externalize Bridge Table Mapping

### Change

Move bridge table logic into configuration:

Example:

```json
{
  "sales_order_items": {
    "relation": "CONTAINS",
    "source": "SalesOrder",
    "target": "Product",
    "target_field": "material",
    "properties": ["requestedQuantity", "netAmount"]
  }
}
Why
Avoids hardcoding logic
Improves maintainability
Easier debugging and extension
7. Add Cardinality Validation
Change

Add check during relationship mapping:

Compare unique values in source vs target

Warn if:

large mismatch in cardinality
Why
Detects incorrect joins early
Prevents star-shaped graph issues
8. Enforce Consistent Edge Direction
Change

Ensure relationships follow business flow:

Customer → Order → Delivery → Invoice → JournalEntry → Payment
Why
Improves traversal consistency
Enhances query reliability
Aligns with business semantics
9. Add Query Guard for DISTINCT Intent
Change

If query contains:

"types"
"kinds"
"different"
"unique"

Then:

Force DISTINCT intent
Do NOT allow list_neighbors template
Why
Prevents incorrect query routing
Fixes semantic mismatch in query handling
10. Add Graph Sanity Checks After Build
Change

After graph construction:

Verify no duplicate nodes:

count(n) == count(distinct id)
Check degree distribution:
No extreme high-degree nodes (star anomaly)
Check connected components:
Avoid excessive fragmentation
Why
Detects structural issues early
Prevents silent graph failures
11. Maintain Existing Constraints
Do NOT change:
FastAPI architecture
LLM integration approach
Query pipeline structure
Template-based Cypher generation
Summary

These changes ensure:

Correct entity modeling
Accurate relationship construction
Reliable multi-hop queries
Stable and interpretable graph structure