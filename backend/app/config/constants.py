APP_NAME = "dodge"
APP_VERSION = "0.1.0"
API_PREFIX = "/api/v1"

# Neo4j
NEO4J_MAX_CONNECTION_POOL_SIZE = 50
NEO4J_CONNECTION_TIMEOUT = 30  # seconds

# Ingestion
JSONL_EXTENSION = ".jsonl"
BATCH_SIZE = 500

# LLM
MAX_QUERY_LENGTH = 1000
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

# Guardrails
BLOCKED_CYPHER_KEYWORDS = [
    "DELETE",
    "DETACH DELETE",
    "DROP",
    "CREATE INDEX",
    "CREATE CONSTRAINT",
    "CALL dbms",
    "LOAD CSV",
]

# ---------------------------------------------------------------------------
# Entity classification
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Schema inference toggle — only use curated schema unless explicitly enabled
# ---------------------------------------------------------------------------
USE_SCHEMA_INFERENCE = False

# ---------------------------------------------------------------------------
# Field alias normalization
# Maps variant column names to canonical field names used in node identity
# ---------------------------------------------------------------------------
FIELD_ALIASES: dict[str, str] = {
    "material": "product",
    "soldToParty": "businessPartner",
    "productionPlant": "plant",
    "referenceSdDocument": "deliveryDocument",
}

# ---------------------------------------------------------------------------
# Preferred DISTINCT fields per node label
# Used when the LLM picks an ID field or provides no property for DISTINCT
# ---------------------------------------------------------------------------
PREFERRED_DISTINCT_FIELDS: dict[str, list[str]] = {
    "Plant": ["plantName", "plantCategory"],
    "Product": ["productGroup", "industrySector"],
    "Customer": ["industry", "businessPartnerCategory"],
    "SalesOrder": ["salesOrderType"],
    "Invoice": ["billingDocumentType"],
    "Delivery": ["shippingPoint"],
}

# ---------------------------------------------------------------------------
# Alternate identifier fields per node label
# Maps label → list of alternate fields users might query with (besides PK)
# Used by templates and entity resolution to match user input against any ID
# ---------------------------------------------------------------------------
ALTERNATE_ID_FIELDS: dict[str, list[str]] = {
    "Product": ["productOldId"],
    "Customer": ["customer", "businessPartnerFullName", "businessPartnerName"],
    "Invoice": ["accountingDocument"],
    "JournalEntry": ["referenceDocument"],
    "Payment": ["invoiceReference"],
}
