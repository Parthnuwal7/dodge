# Entity Resolution Layer - Amendments

This document defines required changes to handle multiple identifiers for entities in the graph system.

The goal is to fix query failures caused by mismatches between user-provided identifiers and stored primary keys.

---

## 🔍 Problem Summary

Observed issue:

Query:
MATCH (p:Product {product: 'ABC-WEB-994'}) RETURN p

Result:
No records

---

### Root Cause

The graph stores:

- `product` → internal system ID (e.g., S8907367013082)
- `productOldId` → external / legacy ID (e.g., ABC-WEB-977)

User queries often use:
- external identifiers (productOldId)

System assumes:
- all user inputs map to PRIMARY KEY

This mismatch causes:
- valid queries returning zero results
- broken multi-hop queries
- unreliable system behavior

---

## 🧠 Key Insight

Entities may have **multiple identifiers**:

| Field | Meaning |
|------|--------|
| product | Primary key (internal ID) |
| productOldId | Alternate / external ID |

User input may match ANY of these fields.

---

## ✅ Required Changes

---

## 1. Add Identifier Resolution Layer

### Change

Before generating Cypher:

Resolve input value against multiple identifier fields.

---

### Implementation Logic

Instead of:

MATCH (p:Product {product: $value})

Use:

MATCH (p:Product)
WHERE p.product = $value
   OR p.productOldId = $value

---

### Why

- Supports multiple identifier types
- Prevents query failures
- Improves robustness

---

## 2. Update LLM Prompt Rules

### Add to Prompt

IMPORTANT:

Entities may have multiple identifier fields.

For Product:
- Primary key: product
- Alternate identifier: productOldId

When matching user input:
- Try PRIMARY KEY first
- If value does not match format, use alternate fields

---

### Example

User query:
"Find product ABC-WEB-977"

Correct query:

MATCH (p:`Product`)
WHERE p.productOldId = 'ABC-WEB-977'
RETURN p

---

## 3. Add Heuristic-Based Identifier Selection

### Change

Introduce simple rules:
If value starts with "ABC-" → use productOldId
If value starts with "S" or numeric → use product


---

### Why

- Faster query generation
- Reduces need for OR conditions
- Improves efficiency

---

## 4. Update Cypher Templates

### Change

Replace strict matching:

MATCH (p:Product {product: $value})

With:

MATCH (p:Product)
WHERE p.product = $value
   OR p.productOldId = $value

---

### Why

- Ensures coverage of all identifier types
- Avoids silent failures

---

## 5. Extend to Other Entities (Generalization)

Apply same logic to:

- Customer
- SalesOrder
- Invoice
- Delivery

Each may have:
- internal ID
- external/reference ID

---

## 6. Optional Optimization

### Hybrid Strategy

Use:

1. Heuristic matching (fast path)
2. Fallback to OR matching (safe path)

---

## 🎯 Expected Outcome

After applying changes:

- Queries using external IDs will succeed
- Multi-hop queries will work reliably
- System becomes resilient to identifier variations

---

## 🚨 Important Constraints

- Do NOT modify graph schema
- Do NOT change primary key definitions
- Do NOT alter backend architecture
- Only enhance matching logic

---

## Summary

Current system assumes:

❌ User input → PRIMARY KEY

Updated system supports:

✅ User input → ANY valid identifier

This change introduces a lightweight **Entity Resolution Layer**, significantly improving system reliability and correctness.