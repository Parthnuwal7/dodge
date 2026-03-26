# Plan: Fix Data Modeling & Graph Construction in DODGE

## Context

The DODGE system (FastAPI + Neo4j + LLM pipeline) loads SAP Order-to-Cash JSONL data from 19 folders, builds a graph in Neo4j, and supports natural language queries. The current graph has critical structural problems:

- **Star clusters**: Wrong node identity (e.g., one node connected to hundreds)
- **Linear chains**: Item tables modeled as nodes create `Header → Item → Product` chains
- **Disconnected components**: Missing or incorrect relationships from Jaccard-based inference
- **Query failures**: No DISTINCT intent; multi-hop queries unreliable

**Root cause**: Bridge/item tables (SalesOrderItems, DeliveryItems, InvoiceItems) are modeled as separate nodes with composite keys, and relationships are inferred via value overlap heuristics instead of explicit FK→PK mappings.

---

## Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `backend/app/config/constants.py` | Entity classification, field aliases, USE_SCHEMA_INFERENCE flag, preferred DISTINCT fields |
| 2 | `backend/app/modeling/graph_schema.py` | Extend EdgeSchema with bridge fields |
| 3 | `backend/app/graph/graph_builder.py` | Bridge-table edges, rel properties, field alias normalization, post-build sanity checks |
| 4 | `backend/app/modeling/relationship_mapper.py` | FK-only edges, bridge config loading, FK validation, cardinality checks |
| 5 | `backend/app/ingestion/schema_inference.py` | No structural changes (disabled by default via flag) |
| 6 | `backend/graph_schema_curated.json` | Rewrite: 8 nodes (single-field IDs), bridge-based edges |
| 7 | `backend/bridge_tables.json` | NEW: externalized bridge table configuration |
| 8 | `backend/app/llm/intent_extractor.py` | Add "distinct" to valid intents |
| 9 | `backend/app/llm/prompt_manager.py` | Update intent prompt (distinct + fix rank example) |
| 10 | `backend/templates/cypher/distinct.cypher` | NEW: distinct query template |
| 11 | `backend/templates/cypher/flow_gaps.cypher` | Update for new graph model |
| 12 | `backend/app/query/query_router.py` | Distinct param mapping, auto-redirect guard, force DISTINCT over list_neighbors |
| 13 | `backend/app/query/response_formatter.py` | Distinct formatting with smart property fallback |
| 14 | `backend/app/query/query_validator.py` | Property-level validation (soft) |

---

## Step 1: Entity Classification & Constants (`constants.py`)

Add to `backend/app/config/constants.py`:

```python
# --- Entity Classification ---
CORE_ENTITIES = {
    "business_partners",
    "sales_order_headers",
    "products",
    "plants",
    "billing_document_headers",
    "payments_accounts_receivable",
    "outbound_delivery_headers",
    "journal_entry_items_accounts_receivable",
}

BRIDGE_TABLES = {
    "sales_order_items",
    "outbound_delivery_items",
    "billing_document_items",
}

IGNORE_TABLES = {
    "product_descriptions",
    "business_partner_addresses",
    "customer_company_assignments",
    "customer_sales_area_assignments",
    "product_plants",
    "product_storage_locations",
    "sales_order_schedule_lines",
    "billing_document_cancellations",
}

# --- Schema Inference Toggle (Amendment #5) ---
USE_SCHEMA_INFERENCE = False  # Only use curated schema unless explicitly enabled

# --- Field Alias Normalization (Amendment #2) ---
# Maps variant column names to canonical field names used in node identity
FIELD_ALIASES = {
    "material": "product",
    "soldToParty": "businessPartner",
    "productionPlant": "plant",
    "referenceSdDocument": "deliveryDocument",  # in billing items context
    # Add more as discovered
}

# --- Preferred DISTINCT Fields per Node Label (Amendment #3) ---
PREFERRED_DISTINCT_FIELDS = {
    "Plant": ["plantName", "plantCategory"],
    "Product": ["productGroup", "industrySector"],
    "Customer": ["industry", "businessPartnerCategory"],
    "SalesOrder": ["salesOrderType"],
    "Invoice": ["billingDocumentType"],
    "Delivery": ["shippingPoint"],
}
```

**Confirmed**: Delivery and JournalEntry added as core entities (8 total). Address moved to IGNORE.

---

## Step 2: Extend EdgeSchema (`graph_schema.py`)

Add three optional fields to `EdgeSchema`:

```python
class EdgeSchema(BaseModel):
    type: str
    from_node: str
    to_node: str
    join_on: tuple[str, str]              # (source_field, target_id_field)
    source_entity: str | None = None      # bridge table name (reads data from this DF)
    rel_properties: list[str] | None = None  # columns to copy as relationship properties
    bridge_target_field: str | None = None   # bridge column for target match (when ≠ target id)
```

- `source_entity`: When set, GraphBuilder reads from this DataFrame instead of from_node's.
- `bridge_target_field`: When bridge column name differs from target node's id_field (e.g., `material` in bridge → `product` in Product node).
- All default to `None` → backward compatible with existing JSON schemas.

Also update `edge_descriptions()` to include rel_properties hints for LLM context.

---

## Step 3: Update GraphBuilder (`graph_builder.py`)

Rewrite `merge_edges()` to handle bridge-table edges:

**Key logic change:**
1. When `edge.source_entity` is set → read from bridge table DataFrame
2. Source node matched by its `id_field` (column exists in bridge DF with same name)
3. Target node matched by `tgt_field` (target's id), value read from `bridge_target_field` column
4. When `edge.rel_properties` is set → add `SET r.prop = row.prop` for each property

**Cypher output example** (SalesOrderItems bridge):
```cypher
UNWIND $rows AS row
MATCH (a:`SalesOrder` {`salesOrder`: row.`salesOrder`})
MATCH (b:`Product` {`product`: row.`material`})
MERGE (a)-[r:`CONTAINS`]->(b)
SET r.`requestedQuantity` = row.`requestedQuantity`, r.`netAmount` = row.`netAmount`
```

**For non-bridge edges (direct FK)**: Behavior unchanged — reads from from_node's DataFrame, no relationship properties.

### 3b. Field Alias Normalization (Amendment #2)

Add `_normalize_field(value, field_name)` helper to `GraphBuilder`:
- Before creating edges, apply `FIELD_ALIASES` to normalize column values
- E.g., when matching `material` against `Product.product`, the alias ensures consistent lookup
- Applied in `_df_to_records()` or as a pre-processing step on the bridge DataFrame

### 3c. FK Validation Before Edge Creation (Amendment #4)

In `merge_edges()`, before building the Cypher query:
1. Validate source column exists in DataFrame
2. Validate target column exists (via schema lookup)
3. Validate non-zero overlap: sample bridge values against target node values
4. Skip edge with warning if validation fails

### 3d. Post-Build Sanity Checks (Amendment #10)

Add `_run_sanity_checks()` method called at end of `build_all()`:

```python
def _run_sanity_checks(self, report: BuildReport) -> None:
    # 1. Check for duplicate nodes per label
    for node in self.schema.nodes:
        id_str = ", ".join(f"n.`{f}`" for f in node.id_fields)
        query = f"MATCH (n:`{node.label}`) RETURN {id_str}, count(*) AS cnt ORDER BY cnt DESC LIMIT 5"
        results = self.client.execute(query)
        dupes = [r for r in results if r.get("cnt", 1) > 1]
        if dupes:
            report.errors.append(f"Duplicate nodes in {node.label}: {dupes}")

    # 2. Check for extreme high-degree nodes (star anomaly)
    query = "MATCH (n) WITH n, size([(n)--() | 1]) AS degree WHERE degree > 200 RETURN labels(n)[0] AS label, count(n) AS cnt"
    results = self.client.execute(query)
    if results:
        report.errors.append(f"Star anomaly detected: {results}")

    # 3. Check connected components (warn if > 50% isolated)
    query = "MATCH (n) WHERE NOT (n)--() RETURN labels(n)[0] AS label, count(n) AS cnt"
    results = self.client.execute(query)
    if results:
        for r in results:
            logger.warning("Isolated nodes: %s = %s", r.get("label"), r.get("cnt"))
```

---

## Step 4: Replace Jaccard Edge Building (`relationship_mapper.py`)

### 4a. Filter nodes by CORE_ENTITIES in `build_schema()`

```python
for entity_name, df in dataframes.items():
    if entity_name not in CORE_ENTITIES:
        continue
    # ... build node schema
```

### 4b. Respect `USE_SCHEMA_INFERENCE` flag (Amendment #5)

In `build_schema()`: if `USE_SCHEMA_INFERENCE` is False, skip `_build_fk_edges()` entirely (no Jaccard candidates). Only use bridge edges and curated schema.

When `USE_SCHEMA_INFERENCE` is True (explicit override): use `_build_fk_edges()` with same logic as current `_build_edges()` but both entities must be in CORE_ENTITIES.

### 4c. Load Bridge Edges from Config (Amendment #6)

Replace hardcoded `_build_bridge_edges()` with `_load_bridge_config()`:
- Load from `backend/bridge_tables.json`
- Parse into EdgeSchema objects with `source_entity`, `bridge_target_field`, `rel_properties`

### 4d. Bridge Table Config File (`backend/bridge_tables.json` - NEW)

```json
{
  "sales_order_items": [
    {
      "type": "CONTAINS",
      "from_node": "SalesOrder",
      "to_node": "Product",
      "join_on": ["salesOrder", "product"],
      "bridge_target_field": "material",
      "rel_properties": ["salesOrderItem", "requestedQuantity", "requestedQuantityUnit", "netAmount", "materialGroup"]
    },
    {
      "type": "PRODUCED_AT",
      "from_node": "SalesOrder",
      "to_node": "Plant",
      "join_on": ["salesOrder", "plant"],
      "bridge_target_field": "productionPlant",
      "rel_properties": ["storageLocation"]
    }
  ],
  "outbound_delivery_items": [
    {
      "type": "FULFILLS",
      "from_node": "Delivery",
      "to_node": "SalesOrder",
      "join_on": ["deliveryDocument", "salesOrder"],
      "bridge_target_field": "referenceSdDocument",
      "rel_properties": ["deliveryDocumentItem", "actualDeliveryQuantity", "deliveryQuantityUnit"]
    },
    {
      "type": "SHIPS_FROM",
      "from_node": "Delivery",
      "to_node": "Plant",
      "join_on": ["deliveryDocument", "plant"],
      "bridge_target_field": "plant",
      "rel_properties": ["storageLocation"]
    }
  ],
  "billing_document_items": [
    {
      "type": "INVOICES",
      "from_node": "Invoice",
      "to_node": "Product",
      "join_on": ["billingDocument", "product"],
      "bridge_target_field": "material",
      "rel_properties": ["billingDocumentItem", "billingQuantity", "billingQuantityUnit", "netAmount"]
    },
    {
      "type": "BILLS",
      "from_node": "Invoice",
      "to_node": "Delivery",
      "join_on": ["billingDocument", "deliveryDocument"],
      "bridge_target_field": "referenceSdDocument",
      "rel_properties": ["billingDocumentItem"]
    }
  ]
}
```

### 4e. Cardinality Validation (Amendment #7)

Add `_validate_cardinality()` to `RelationshipMapper`:
- Before accepting an edge, compare unique value counts in source vs target columns
- Warn if `max(src_count, tgt_count) / min(src_count, tgt_count) > 100` (star anomaly risk)
- Log warning but don't block — allow manual override via curated schema

### 4f. Edge Direction Enforcement (Amendment #8)

All edges follow business O2C flow direction:
```
Customer → SalesOrder → Delivery → Invoice → JournalEntry → Payment
              ↓              ↓          ↓
           Product         Plant      Product
```

Validate in `_build_bridge_edges()` that from_node → to_node follows this convention.

---

## Step 5: Update Curated Schema (`graph_schema_curated.json`)

### New Node List (8 core entities, no item nodes):

| Label | source_entity | id_field |
|---|---|---|
| Customer | business_partners | businessPartner |
| SalesOrder | sales_order_headers | salesOrder |
| Product | products | product |
| Plant | plants | plant |
| Delivery | outbound_delivery_headers | deliveryDocument |
| Invoice | billing_document_headers | billingDocument |
| JournalEntry | journal_entry_items_accounts_receivable | accountingDocument |
| Payment | payments_accounts_receivable | accountingDocument |

**Amendment #1**: JournalEntry and Payment now use single-field `accountingDocument` as id_field (not composite). Other fields (companyCode, fiscalYear, accountingDocumentItem) remain as properties. This fixes Cypher matching issues and prevents duplicate nodes from composite key confusion.

**Removed**: SalesOrderItem, DeliveryItem, InvoiceItem, Address

### New Edge List:

**Direct FK edges** (no bridge):
1. `Customer -[PLACED_ORDER]-> SalesOrder` (businessPartner → soldToParty) **Confirmed: use PK businessPartner**
2. `Invoice -[BILLED_TO]-> Customer` (soldToParty → businessPartner)
3. `Invoice -[GENERATES]-> JournalEntry` (accountingDocument → accountingDocument)
4. `JournalEntry -[CLEARED_BY]-> Payment` (clearingAccountingDocument → accountingDocument)
5. `Payment -[PAID_BY]-> Customer` (customer → businessPartner)

**Bridge-table edges** (with source_entity + rel_properties):
6-11. See table in Step 4c above.

---

## Step 6: Verify Node-Edge Separation

`build_all()` already runs nodes-first, edges-second. **No code change needed.** Just verify during testing.

---

## Step 7: Add DISTINCT Intent (6 sub-changes)

### 7a. `intent_extractor.py`
Add `"distinct"` to `VALID_INTENT_TYPES` set.

### 7b. `prompt_manager.py`
Add to intent_extraction prompt:
- `distinct` in the intent_type list
- New bullet: `"- distinct: List unique/distinct values of a property. Trigger: 'types', 'kinds', 'different', 'unique', 'categories'. Set filters.property_name."`
- Fix rank example to reference new graph model (no InvoiceItem)

### 7c. `templates/cypher/distinct.cypher` (NEW FILE)
```cypher
-- name: distinct
-- description: List distinct values of a specific property on nodes of a given label
-- params: label, property_name
MATCH (n:`${label}`)
WHERE n.`${property_name}` IS NOT NULL
RETURN DISTINCT n.`${property_name}` AS value, count(*) AS occurrences
ORDER BY occurrences DESC
LIMIT 100
```

### 7d. `query_router.py`
- Add `_DISTINCT_KEYWORDS = {"types", "kinds", "different", "unique", "categories", "distinct"}`
- **Amendment #9 (Query Guard)**: If query contains distinct keywords, FORCE `distinct` intent. Do NOT allow `list_neighbors` or `find_node` fallback for these queries.
- Add `elif template.name == "distinct"` in `_map_parameters()`:
  ```python
  params["label"] = entities[0] if entities else ""
  params["property_name"] = str(filters.get("property_name", ""))
  ```

### 7e. Smart Property Selection for DISTINCT (Amendment #3)

In `_map_parameters()` for `distinct`, after setting `property_name`:
- If `property_name` is empty or is an ID field → use `PREFERRED_DISTINCT_FIELDS` from constants
- If label has preferred fields → use first available one
- Fallback: scan node properties for first low-cardinality string field (exclude IDs, dates, booleans)

```python
if not params["property_name"] or params["property_name"] in node.id_fields:
    from app.config.constants import PREFERRED_DISTINCT_FIELDS
    preferred = PREFERRED_DISTINCT_FIELDS.get(params["label"], [])
    node = self.schema.get_node(params["label"])
    if node:
        for field in preferred:
            if field in node.properties:
                params["property_name"] = field
                break
```

### 7f. `response_formatter.py`
Add distinct handling in both `_build_answer()` and `_build_explanation()`:
- **Answer**: Compute values in backend: `"Found {count} distinct {prop} values: {val1}, {val2}, ..."`
- **Explanation**: `"Listing distinct values of {prop} across all {label} nodes."`
- Do NOT rely on LLM for counting — use `len(data)` directly.

### 7g. No change to `query_validator.py` for distinct (labels already validated).

---

## Step 8: Fix Response Formatting for DISTINCT

Covered in Step 7e. Key requirement: the `_build_answer()` path (not LLM) must handle distinct results by extracting values from the `data` list and computing count programmatically.

---

## Step 9: Property Validation (`query_validator.py`)

Add `_extract_variable_labels()` helper to map Cypher variables to node labels. Then in `validate()`:
- Extract `(variable, property)` pairs from Cypher
- Look up variable → label binding
- Check property exists in node's schema
- **Soft warning only** (logger.debug), NOT hard error — relationship properties and Cypher functions can look like property access

---

## Step 10: Rebuild Graph (Operational)

After all code changes:
1. `DELETE /api/v1/graph/clear`
2. `POST /api/v1/graph/build` with updated curated schema, `clear_existing: true`
3. Verify with `GET /api/v1/graph/status`
4. Visual verification with `GET /api/v1/graph/explore`

---

## Step 11: Update flow_gaps.cypher Template

Rewrite to use new direct relationships (no item node hops):

```cypher
MATCH (so:`SalesOrder`)
OPTIONAL MATCH (so)<-[:FULFILLS]-(d:`Delivery`)
OPTIONAL MATCH (inv:`Invoice`)-[:BILLS]->(d)
OPTIONAL MATCH (inv)-[:GENERATES]->(je:`JournalEntry`)
OPTIONAL MATCH (je)-[:CLEARED_BY]->(pay:`Payment`)
WITH so,
     count(DISTINCT d) > 0 AS has_delivery,
     count(DISTINCT inv) > 0 AS has_invoice,
     count(DISTINCT je) > 0 AS has_journal_entry,
     count(DISTINCT pay) > 0 AS has_payment
WHERE NOT (has_delivery AND has_invoice AND has_journal_entry AND has_payment)
RETURN so.`salesOrder` AS sales_order, has_delivery, has_invoice, has_journal_entry, has_payment,
  CASE
    WHEN NOT has_delivery THEN 'No delivery'
    WHEN has_delivery AND NOT has_invoice THEN 'Delivered but not billed'
    WHEN has_invoice AND NOT has_journal_entry THEN 'Billed but no journal entry'
    WHEN has_journal_entry AND NOT has_payment THEN 'No payment'
    ELSE 'Incomplete flow'
  END AS gap_type
ORDER BY gap_type
LIMIT 50
```

---

## Verification Plan

1. **Schema validation**: Load updated curated JSON → verify 8 nodes, 11 edges, no item nodes
2. **Graph build**: Run full ingestion → verify node counts (no SalesOrderItem/DeliveryItem/InvoiceItem nodes)
3. **Sanity checks pass**: Post-build checks report no duplicate nodes, no star anomalies (Amendment #10)
4. **Graph structure**: `GET /api/v1/graph/explore` → verify no star clusters, no long chains
5. **Bridge relationships**: Verify CONTAINS edges have properties (qty, price)
6. **JournalEntry/Payment single ID**: Verify nodes deduplicated correctly with `accountingDocument` (Amendment #1)
7. **Distinct query**: Ask "Show different types of plants" → verify DISTINCT template used, correct results
8. **Distinct fallback**: Ask "Show types of plants" with no property → verify `plantName` selected via preferred fields (Amendment #3)
9. **Distinct guard**: Ask "What are the different kinds of products" → verify NOT routed to list_neighbors (Amendment #9)
10. **Multi-hop query**: Ask "Which customer has the most orders" → verify traversal works
11. **Flow gaps**: Ask "Show incomplete flows" → verify updated template returns results
12. **Negative test**: Ask about a non-existent label → verify rejection
13. **Schema inference disabled**: Verify auto-inference not triggered unless `USE_SCHEMA_INFERENCE=True` (Amendment #5)

## Amendments Integrated

| # | Amendment | Where Applied |
|---|-----------|---------------|
| 1 | JournalEntry/Payment single-field ID | Step 5 (curated schema) |
| 2 | Field alias normalization | Step 1 (constants), Step 3b (graph_builder) |
| 3 | Smart DISTINCT property selection | Step 1 (constants), Step 7e (query_router) |
| 4 | Strict FK validation before edges | Step 3c (graph_builder) |
| 5 | Disable schema inference by default | Step 1 (constants), Step 4b (relationship_mapper) |
| 6 | Externalize bridge table mapping | Step 4c-4d (bridge_tables.json) |
| 7 | Cardinality validation | Step 4e (relationship_mapper) |
| 8 | Consistent edge direction | Step 4f (relationship_mapper) |
| 9 | DISTINCT query guard | Step 7d (query_router) |
| 10 | Post-build sanity checks | Step 3d (graph_builder) |
| 11 | Maintain existing constraints | All steps (no FastAPI/LLM/pipeline changes) |
