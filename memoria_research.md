# Memoria del sistema — Research de industria y mapeo a principios

> **Propósito**: research de best practices y standards de industria para una capa de Memoria multi-tenant que almacene datos heterogéneos (estructurado tipo ERP + documental + vectorial + event log + knowledge graph), aplicada a la **capa 1 (Memoria del sistema)** de los principios de arquitectura del Agentic Stack.
>
> **Prioridad declarada**: (1) aislamiento multi-tenant, (2) memoria agéntica/semántica, (3) ingesta heterogénea, (4) arquitectura de capas.
>
> **Naturaleza**: informativo. No introduce ni modifica principios. Su rol es alimentar futuras propuestas arquitectónicas con vocabulario y patrones consolidados de la industria, y señalar las zonas grises donde **el consenso no existe**.

---

## 0. Resumen ejecutivo — lo que la industria considera "estado del arte" en 2026

| Sub-sistema de Memoria | Patrón dominante 2026 | Tensiones abiertas |
|---|---|---|
| **Storage estructurado multi-tenant** | Shared-DB + RLS por defecto; silo (DB-per-tenant) para clientes regulados/enterprise; bridge (schema-per-tenant) como middle ground | RLS + ORM popular (Prisma, etc.) sigue siendo fricción operativa |
| **Storage documental** | Object storage (S3-compat) para contenido + DB OLTP para metadata; separación obligatoria por características de workload | Pre-signed URLs vs proxy-through-app para entrega de contenido |
| **Vector store** | **Tenant-per-shard** (Weaviate) gana al patrón "tenant_id en filtro" para multi-tenancy real; pgvector con tenant_id sufre **degradación de recall** con HNSW filtrado | pgvector vs especializado sigue siendo decisión de "infra ya disponible vs performance" |
| **Event log append-only** | Outbox pattern para atomicidad write-DB + write-bus; event sourcing completo solo cuando la auditoría/replay justifica complejidad | Event sourcing puro vs CDC desde DB convencional |
| **Knowledge graph** | Property graphs (Neo4j) para enterprise; **temporal KG** (Graphiti/Zep) emergiendo como state-of-the-art para memoria agéntica con dimensión temporal | KG-only vs KG + vector (dual-store Mem0) — sin ganador claro |
| **Memoria agéntica** | Jerarquía cognitiva (working / episódica / semántica / procedural); **extracción asíncrona LLM-driven** del flujo a memoria estructurada | Heurísticas fijas vs políticas aprendidas (AgeMem, papers 2026) |
| **Ingesta multi-fuente** | **Medallion architecture** (bronze/silver/gold) como organización lógica; **CDC log-based** (Debezium) como mecanismo de captura | Streaming vs micro-batch; lakehouse vs operational store |

**Insight transversal**: la industria converge en que la Memoria **no es una pieza única** sino un conjunto de sub-sistemas con perfiles de workload muy distintos (OLTP, OLAP, vector, graph, blob). El error caro y recurrente es intentar resolver todo con una sola tecnología.

---

## 1. Aislamiento multi-tenant — el espectro silo / bridge / pool

### 1.1 Los tres patrones canónicos

La industria converge en tres patrones, con nomenclatura ligeramente distinta según el vendor:

| Patrón | Sinónimos | Aislamiento | Coste | Cuándo usarlo |
|---|---|---|---|---|
| **Silo** (DB-per-tenant) | Database isolation, dedicated database | Físico | Alto | Clientes regulados (HIPAA, GDPR estricto), high-ACV enterprise |
| **Bridge** (schema-per-tenant) | Schema isolation | Lógico fuerte | Medio | Tenants medianos, customizaciones por tenant |
| **Pool** (shared-DB + RLS) | Shared schema, row-level | Lógico (depende de policies) | Bajo | High-scale, low-margin SaaS, muchos tenants pequeños |

Tenant SaaS isolation isn't one-size-fits-all. Database, schema, and row-level security strategies each have trade-offs in cost, performance, and security. Large, regulated tenants often require database isolation, mid-sized tenants fit schema-level isolation, and small tenants benefit from RLS. Hybrid approaches often give SaaS platforms the flexibility to balance these factors.

Patrones híbridos son comunes en producción: tenants enterprise en silo, resto en pool, con un router de tenancy que decide a qué BD ir. Esto **rompe la regla simple de "una sola BD"** y añade complejidad operativa pero permite servir el rango completo del mercado.

### 1.2 RLS en PostgreSQL — el patrón canónico para el pool

PostgreSQL RLS es la implementación de referencia. Shared schema is the most common starting point. The danger is a missing WHERE tenant_id = ? leaking data across tenants. PostgreSQL's Row-Level Security (RLS) eliminates that risk at the database level.

Patrón estándar (replicable):

```sql
-- Activar RLS en cada tabla multi-tenant
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

-- Policy que filtra por session variable
CREATE POLICY tenant_isolation ON orders
  USING (tenant_id = current_setting('app.current_tenant')::uuid);

-- Forzar RLS incluso para owners de la tabla
ALTER TABLE orders FORCE ROW LEVEL SECURITY;
```

Y al entrar a cada request:
```python
SET LOCAL app.current_tenant = '<tenant_uuid>';
```

**Mapeo a tu arquitectura**: tu P18 ya declara este patrón explícitamente ("BD compartida con RLS, `tenant_id` en todas las tablas multi-tenant"). Y tu glosario del MCP/API server de capa lo materializa: "acceso directo psycopg pool con `SET LOCAL app.current_tenant_id`". **Estás alineado con el patrón canónico**.

### 1.3 Anti-patrones documentados

Tres errores recurrentes:

- Schema-per-tenant migrations lock tables. Run them during maintenance windows or use zero-downtime migration techniques (add column, backfill, swap). Schema-per-tenant escala mal en operaciones porque migrar N esquemas se vuelve N veces más caro.
- Hardcoding tenant resolution. Subdomain extraction works until it doesn't (custom domains, API keys, JWTs). Build tenant resolution as a pluggable strategy from day one. Hardcodear el método de resolución de tenant (sólo subdomain, sólo JWT claim, etc.) crea deuda. Mejor un middleware desacoplado.
- In a Pool model, restoring data for just one tenant requires complex 'point-in-time' recovery and data extraction, which can significantly increase your RTO — el coste oculto del pool es el restore por tenant. Sin estrategia de backup logical-per-tenant, restaurar un tenant es operacionalmente brutal.

### 1.4 Multi-tenancy en vector stores — donde se rompe la analogía con RDBMS

Aquí la industria **diverge fuertemente** y es la zona donde más errores arquitectónicos se cometen.

**El patrón "tenant_id en filtro" funciona en RDBMS, NO en vector indexes**:

For applications that manage multi-tenancy, the SQL query is always as follows: SELECT * FROM some_table WHERE tenant_id = 'tenant_01' ORDER BY embedding <=> '[0,1,0,...]'; However, my research indicates that, at least with HNSW, it will return fewer results than expected when the number of records is greater than a certain number. (Presumably I would expect this issue in IVFFlat also.) This seems to me to be a major factor discouraging the use of pgvector in multi-tenant services.

Esto es un finding crítico para tu sistema: el patrón RLS-style de "filtrar por `tenant_id`" **degrada recall** en HNSW filtrado. La industria ha respondido con tres soluciones:

**(A) Tenant-per-shard / tenant-per-namespace** — patrón dominante 2026.

Weaviate es el referente con arquitectura nativa: Before Weaviate v1.20, you had two options to model a multi-tenancy landscape. Both had considerable drawbacks which made us completely rethink multi-tenancy. From a performance perspective, you would build a giant monolithic vector index with potentially billions of vectors, yet you would only ever query a tiny fraction of it. With a median tenant storing between 1,000 and 100,000 objects, you would typically query less than 0.01% of the index. What a waste of resources.

La respuesta de Weaviate (y diseño replicable): un shard físicamente aislado por tenant, con Each tenant has a dedicated, high-performance vector index. Dedicated indexes mean faster query speeds. Instead of searching a shared index space, each tenant responds as if it was the only user on the cluster. Each tenant's data is isolated on a dedicated shard. This means that deletes are fast and do not affect other tenants.

Con tenant-state machine (ACTIVE / INACTIVE / OFFLOADED): If you are using multi-tenancy, and have tenants that are not being queried frequently, consider offloading them to cold (cloud) storage. Offloaded tenants are stored in a cloud storage bucket, and can be reloaded into Weaviate when needed. This can significantly reduce the memory and disk usage of Weaviate, and thus reduce costs.

Pinecone implementa el mismo patrón con **namespaces** dentro de un index: In Pinecone, this typically refers to storing distinct datasets in separate namespaces while being served by a single index. This architecture not only allows us to separate data from different groups of users, to ensure security and privacy, but can also reduce query latency, as queries can be directed to specific namespaces, reducing the search space.

**(B) pgvector + particionado por tenant** — solo viable hasta cierta escala.

To model your data efficiently, you may want to use partitioning to reduce the size of your indexes, especially in a multi-tenant situation. If you're using an ORM, such as Prisma, as of September 2025, they still don't fully support pgvector and partitioning without workarounds.

Trade-off: si ya tienes Postgres y los tenants son pocos / pequeños, particionado funciona; si vas a tener miles de tenants activos o tenants con millones de vectores, **se rompe**.

**(C) Cluster dedicado por tenant** — el "silo" del vector world.

Reservado para enterprise con compliance estricto. Operacionalmente caro: cada tenant es prácticamente una infraestructura.

**Recomendación destilable para tu sistema**: si vais por pgvector inicialmente (alineado con P1 simpleza + ya tenéis Postgres), preveer la **migración a vector store con tenant-per-shard nativo** (Weaviate, Qdrant, Pinecone) cuando crezcáis. La estructura de Connections (P11 + P19 Adapter pattern aplicado a vector stores) os deja esta puerta abierta sin refactor.

### 1.5 Mapeo explícito a tus principios

- **P18 (BD compartida con RLS, 1 user ↔ 1 tenant)** — alineado con el patrón pool canónico. Tu decisión de "no DB-per-tenant ni schema-per-tenant" es defendible si el target son tenants pequeños/medianos; conviene anticipar el día en que un cliente regulado pida silo y diseñar la Memoria como **plurality of stores** (al menos un store-per-tenant capability como escape hatch).
- **P12 (multi-tenant por diseño desde la capa de datos)** — encaja con el "namespace everything" de Redis y la línea industrial.
- **P7 (Capas internas mediadas)** — la mediación del `memory-mcp-server` (con `SET LOCAL app.current_tenant_id`) es exactamente el patrón canónico de "tenant context propagation".

---

## 2. Memoria agéntica — la capa específica para LLM agents

Esta sección cubre tu prioridad 2. Es la zona donde la industria **menos consenso** tiene; la mayor parte del estado del arte es de 2025-2026.

### 2.1 Taxonomía de memoria agéntica (modelo cognitivo)

La industria ha convergido en una taxonomía inspirada en cognición humana, formalizada por el framework **CoALA** y materializada en sistemas como Mem0, Zep, MemGPT, LangMem:

| Tipo de memoria | Qué guarda | Implementación típica |
|---|---|---|
| **Working memory** (corto plazo) | Contexto activo de la conversación / del Run en curso | Context window LLM + cache de sesión |
| **Episodic memory** | Eventos específicos con dimensión temporal ("Alice pidió X el martes") | Vector store + metadata temporal, o temporal KG |
| **Semantic memory** | Hechos abstraídos ("Alice prefiere comunicación por Slack") | Vector store + KG, curado |
| **Procedural memory** | Cómo hacer cosas, patrones, skills | Workflow DB, vector store de tareas similares, o archivos tipo `SKILL.md` |

Beyond short and long-term memory, production systems sometimes implement specialized memory types for specific use cases: Episodic memory captures specific past experiences with temporal detail [...] Semantic memory stores factual knowledge independent of specific experiences: customer profiles, product specs, domain expertise. Use structured databases for facts and vector databases for concept embeddings. Procedural memory captures how to perform tasks: workflow steps and decision points.

Consejo dominante: Start with short-term and long-term memory, then add other types only as operational value justifies the added complexity.

### 2.2 Los dos paradigmas de producción dominantes — Mem0 vs Zep

La industria 2026 tiene dos referencias claras, con filosofías distintas:

**Mem0 — dual-store (vector + KG opcional)**:

Mem0 uses a dual-store architecture: a vector database handles semantic search, and a knowledge graph captures entity relationships. When you add a memory, Mem0 embeds it into the vector store and extracts entities and relationships for the graph layer.

**Zep / Graphiti — temporal knowledge graph como ciudadano de primera clase**:

Zep addresses this fundamental limitation through its core component Graphiti -- a temporally-aware knowledge graph engine that dynamically synthesizes both unstructured conversational data and structured business data while maintaining historical relationships.

Arquitectura interna de Zep, replicable: In Zep, memory is powered by a temporally-aware dynamic knowledge graph G = (N, E, ϕ), where N represents nodes, E represents edges, and ϕ : E →N × N represents a formal incidence function. This graph comprises three hierarchical tiers of subgraphs: an episode subgraph, a semantic entity subgraph, and a community subgraph.

Y crucialmente: Zep implements a bi-temporal model, where timeline T represents the chronological ordering of events, and timeline T ′ represents the transactional order of Zep's data ingestion.

El modelo **bi-temporal** (cuándo ocurrió vs cuándo se ingestó) es clave para tu caso de uso de fondos PE/VC y PyMEs porque permite reconstruir "qué sabía el sistema el día X" — auditabilidad real para decisiones operativas.

**El benchmark — sin ganador claro**:

Mem0 paper reclama superioridad: our methods deliver 5%, 11%, and 7% relative improvements in single-hop, temporal, and multi-hop reasoning question types over best performing methods in re[...]

Zep paper reclama lo contrario: In this evaluation, Zep achieves substantial results with accuracy improvements of up to 18.5% while simultaneously reducing response latency by 90% compared to baseline implementations.

Evaluación independiente: An independent evaluation using the LongMemEval benchmark — which tests long-term memory retrieval across temporal, multi-hop, and knowledge-update query types — measured Mem0 at 49.0%

**Lectura honesta**: ningún sistema domina; cada uno gana en su benchmark de origen. Para tu sistema, la decisión correcta es **no acoplarse a uno**. Modelar memoria agéntica como otra capacidad consumible vía Component (P7) + posiblemente Connection (P11) permite intercambiar el backend sin refactor.

### 2.3 La pipeline de extracción a memoria — patrón canónico

Independientemente del backend, hay un patrón asíncrono compartido por Mem0, Zep, AgentCore:

When new events are stored in short-term memory, an asynchronous extraction process analyzes the conversational content to identify meaningful information. This process leverages large language models (LLMs) to understand context and extract relevant details that should be preserved in long-term memory. The extraction engine processes incoming messages alongside prior context to generate memory records in a predefined schema.

Es decir:

```
Conversación / evento del Run (working memory)
         │
         ▼
Extracción asíncrona LLM-driven (sub-Pipeline en tu arquitectura)
         │
         ├─► Embedding → vector store (semantic search)
         ├─► Entity extraction → knowledge graph (relationships)
         └─► Decisión "¿esto merece persistir?" → curated long-term memory
```

**Mapeo a tu arquitectura**: este patrón encaja perfectamente como un Pipeline declarativo en tu sistema. El extractor es un Agent (LLM-driven). Los stores (vector, KG) son Connections + Components dedicados. El Trigger es un evento del bus emitido al cierre de un Run (P6). **No es un sub-sistema especial; es una composición de tus primitivas existentes.**

### 2.4 La distinción RAG vs Agent Memory — frecuentemente confundida

It goes beyond basic RAG (Retrieval-Augmented Generation). RAG fetches external documents once; agent memory maintains evolving state, user preferences, past decisions, and learned procedures.

Para tu sistema convivirán los dos:

- **RAG** (sobre Memoria documental): los Agents consultan PDFs/contratos/emails de la firma del tenant. Stateless, "fetch external knowledge".
- **Agent memory** (sobre Memoria agéntica): los Agents acumulan experiencia, preferencias del user, contexto del proyecto. Stateful, evolutivo.

Mantenerlos **separados conceptualmente** evita el error común de tratar la memoria del agente como "más RAG". Tu glosario ya las distingue ("firm knowledge" vs "agent memories" en la entrada Security Group).

### 2.5 Mapeo a tus principios

- **P5 (Observabilidad central)** — la pipeline de extracción a memoria es un Run; debe trazarse con OpenTelemetry como cualquier otro.
- **P7 (Capas internas mediadas)** — la memoria agéntica vive detrás del `memory-mcp-server`; los agents la consumen vía Component + Connection internal.
- **P16 (Versionado inmutable)** — la memoria semántica debería ser versionada para reconstruir "qué creía el agente en T". Encaja directamente con tu modelo de versionado, aunque conviene revisarlo si aplica a payload de memoria, no sólo a Entidades declarativas.
- **P18 (security groups)** — qué partes de qué memorias ve cada user es policy del security group; el `memory-mcp-server` la enforce.

---

## 3. Ingesta heterogénea — multi-fuente tipo ERP

Esta sección cubre tu prioridad 3.

### 3.1 Medallion architecture — el patrón organizativo de referencia

Originalmente Databricks, hoy estándar de facto en lakehouse. Medallion architecture organizes your lakehouse into three layers: bronze (raw, immutable data), silver (cleaned, conformed enterprise data), and gold (curated, business-ready data products). It's a logical pattern — not a product — that prevents data lakes from becoming data swamps.

Las tres capas:

| Capa | Contenido | Quién lo usa |
|---|---|---|
| **Bronze** | Datos crudos, inmutables, tal cual llegaron | Auditoría, reprocesado, lineage |
| **Silver** | Datos validados, conformes, deduplicados, JOINeados | Data scientists, agentes en análisis |
| **Gold** | Datasets enriquecidos, business-ready, por dominio | Dashboards, agentes operacionales, BI |

This architecture guarantees atomicity, consistency, isolation, and durability as data passes through multiple layers of validations and transformations before being stored in a layout optimized for efficient analytics.

**Gotcha importante para tu caso de uso agéntico**: The pattern excels for analytics and BI but has a structural limitation for real-time automated decisions: the multi-hop data flow adds propagation delay that can't match tight decision validity windows.

Es decir: medallion es excelente para análisis y reporting, pero **no debe ser el path de datos para Agents en tiempo real** que necesitan decidir y actuar. Para eso, los agents leen del **operational store** (Postgres OLTP del tenant, KG, vector store) directamente. Medallion alimenta análisis, métricas, training de modelos, no el lazo operativo.

### 3.2 CDC — captura de cambios desde sistemas heterogéneos

Para ingestar de ERPs / CRMs / SaaS de terceros, el patrón dominante 2026 es **CDC log-based**:

Optimized for Cloud and Stream Processing: CDC efficiently moves data across wide area networks, making it ideal for cloud deployments and integrating data with stream processing solutions like Apache Kafka.

Stack típico industrial:

Debezium + Kafka Connect for open‑source log‑based CDC on various RDBMS, integrating natively with Kafka and Schema Registry. AWS DMS or cloud‑native CDC for managed captures when speed of setup and managed ops outweigh custom control. [...] Event streaming bus (Kafka/Redpanda) as the backbone for fan‑out, backpressure management, and consumer decoupling. Lakehouse/warehouse (Snowflake/BigQuery/Databricks) for curated historical views built from CDC bronze/silver/g[old layers].

Nota clave: **Debezium + Redpanda** es directamente compatible con tu bus actual (P6). Esto significa que la ingesta CDC entra como **Triggers + Components especializados**, no como una pieza arquitectónica nueva.

### 3.3 Métodos de captura — los cuatro patrones

1. **Log-based** (Debezium, GoldenGate) — lee el WAL/binlog. Mínimo impacto en source, captura todo incluso deletes, casi tiempo real. **Recomendado por defecto**.
2. **Trigger-based** — DB triggers que escriben a tabla de cambios. Más simple, mayor overhead en source.
3. **Timestamp-based** — column `last_updated`; polling. This method relies on table schemas to include a column to indicate when it was previously modified, i.e. LAST_UPDATED etc. Funciona para sistemas legacy sin acceso al log. **No captura deletes**.
4. **Snapshot diff** — full snapshot periódico + diff. Brutal, último recurso para sistemas sin nada de lo anterior.

### 3.4 Gestión de schema evolution — el problema crónico

Source schemas will change. Columns will be added, and data types will be modified. If your pipeline is brittle, these changes will break it. Use a CDC solution that integrates with a schema registry or has built-in drift detection.

Buenas prácticas:

- **Schema registry** centralizado (Confluent Schema Registry, Karapace, Apicurio). Versiona schemas; reject mensajes incompatibles.
- **Schema-on-read** para bronze (acepta cualquier shape; valida tarde) + **schema-on-write** para silver/gold (rigor).
- **Outbox pattern** desde sistemas internos en lugar de CDC raw, cuando puedas modificar el origen.

### 3.5 Mapeo a tus principios

- **P3 (Declarativo first)** — los conectores de ingesta (un conector Salesforce, un conector SAP, etc.) son **Connections external + Triggers + Components**. La definición de qué se ingesta, cómo se mapea y dónde aterriza es YAML.
- **P6 (Bus único)** — Debezium publica al bus (Redpanda) y los Pipelines de procesamiento consumen. **Encaja sin fricción.**
- **P12 (multi-tenant)** — cada evento CDC lleva `tenant_id`; las particiones de Redpanda por `tenant_id` son lo correcto.
- **P18 (RLS)** — los datos ingestados aterrizan en tablas con RLS desde el bronze. Esto es no-negociable: nunca debe haber un "raw bucket sin tenant_id".
- **Capacidad futura señalada en §8.5 (telemetría en endpoints)** — el patrón CDC aquí investigado es directamente el mecanismo para esa capacidad cuando llegue.

---

## 4. Arquitectura de capas — storage / access / API / cache / search

Esta sección cubre tu prioridad 4. Lo trato más breve porque tu doc ya está muy maduro aquí.

### 4.1 La separación obligatoria de workloads

El patrón canónico que la industria ha consolidado: **separar storage por características de workload**, no por tipo de dato.

When a user searches for "all employment contracts for customer X," the system must wade through both the searchable attributes and the heavyweight file content, even though the search only needs the metadata. I realized that these two types of data have completely different performance characteristics. Metadata operations are classic Online Transaction Processing (OLTP) workloads: frequent, small, latency-sensitive transactions. Content operations are the opposite: infrequent, large, bandwidth-intensive transfers that can tolerate higher latency.

Esto se traduce en un stack de stores especializados:

| Workload | Store típico | Tu caso |
|---|---|---|
| Metadata OLTP de documentos | Postgres (con RLS) | metadata de PDFs, contratos, emails |
| Contenido binario | S3-compatible (MinIO en POC, S3 en cloud) | PDFs, attachments, exports |
| Vector search | pgvector inicial → Weaviate/Qdrant escala | embeddings de chunks |
| Full-text search | Postgres `tsvector` inicial → Elasticsearch/OpenSearch | búsqueda léxica de docs |
| Graph traversal | Neo4j / Memgraph / FalkorDB | knowledge graph |
| Event log | `event_log` Postgres (tu P5) + Redpanda | append-only auditable |
| OLAP / analytics | DuckDB embebido → BigQuery/Snowflake escala | dashboards, reporting |

The reference architecture for 2026 production RAG: Document Processing: Apache Tika or Unstructured.io for parsing PDFs, DOCX, HTML · Chunking: Semantic chunking with LangChain or LlamaIndex text splitters · Embeddings: Self-hosted BGE or GTE-Qwen2 for sensitive data, OpenAI text-embedding-3-small for convenience · Vector Store: Qdrant (self-hosted) or Pinecone (managed) with hybrid search enabled · Retrieval: Reciprocal rank fusion combining dense and sparse results, reranking with Cohere rerank-v3

### 4.2 Hybrid search + reranking — pattern dominante 2026 para RAG

Hybrid search beats pure semantic: BM25 + dense retrieval outperforms either alone · Reranking is essential: Cross-encoders improve precision significantly · Query transformation matters: HyDE, multi-query, and decomposition address query-document mismatch

La pipeline de retrieval canónica:

```
Query del Agent
   │
   ├─► Dense retrieval (embeddings) → candidatos_A
   └─► Sparse retrieval (BM25)      → candidatos_B
                  │
                  ▼
       Reciprocal Rank Fusion (RRF)
                  │
                  ▼
          Reranker (cross-encoder)
                  │
                  ▼
            Top-K final → LLM context
```

**Mapeo a tu arquitectura**: esta pipeline es un Pipeline declarativo en tu sistema (P3 + P9). Cada paso es un Component reutilizable. **No es un sub-sistema único** "RAG service"; es composición.

### 4.3 Cache — la capa que casi nadie diseña bien

Casi todas las arquitecturas que vi mencionan cache "más tarde". Para tu sistema:

- **Cache de embeddings** (input hash → embedding) — evita recomputar embeddings de chunks que no cambiaron. Postgres + columna hash o Redis. Coste vs. ahorro suele ser claro.
- **Cache de retrieval** (query hash → top-K) — controvertido para agentes, porque la query ligeramente cambia pero el contexto puede ser idéntico. Usar con TTL corto y por scope (`tenant_id`).
- **Cache de respuestas LLM** (prompt hash → completion) — la industria está dividida. Anthropic ofrece prompt caching nativo; menos relevante para tu agnosticismo (P19), pero el Adapter de cada provider puede exponerlo cuando aplique.

### 4.4 Mapeo a tus principios

- **P7 (Capas internas mediadas)** — todos estos stores están detrás del `memory-mcp-server`; ningún Component los toca directamente.
- **P11 (Connection internal)** — cada uno de los stores (Postgres, pgvector, S3, Neo4j) es una Connection con `ámbito: internal` y `scope: system`.
- **P19 (LLM-agnóstico)** — el patrón "adapter por provider" aplica también a los stores: un Adapter para pgvector, otro para Weaviate, etc. Tu memoria queda **store-agnóstica** desde día 1.

---

## 5. Knowledge graph — sub-sistema con perfil propio

### 5.1 Tipos de graph stores — qué elegir cuándo

| Tipo | Ejemplos | Cuándo |
|---|---|---|
| **Property graph** | Neo4j, Memgraph, FalkorDB, Kuzu | Mainstream para enterprise; queries Cypher; bueno para entidades-y-relaciones |
| **Triple store / RDF** | GraphDB, Stardog, Amazon Neptune (RDF) | Ontologías formales, web semántica, SPARQL, inferencia |
| **Temporal KG** | Graphiti (Zep), embebido en Neo4j/FalkorDB | Memoria agéntica, dimensión temporal explícita |

Enterprise knowledge graphs use specialized graph databases (like Neo4j, a property graph database) or triple stores (such as GraphDB, Stardog, or Amazon Neptune configured for RDF) as their backend storage engines.

### 5.2 Ontology design — el paso que más gente salta y rompe todo

A knowledge graph is not just a database — it is a semantic representation of meaning. Before creating nodes or writing Cypher, you need an ontology — a formal description of [...]

Pasos canónicos:

1. **Identificar entidades del dominio** (Company, Person, Deal, Document, Process, Run, …)
2. **Identificar relaciones** (EMPLOYS, OWNS, SIGNED, PARTICIPATED_IN, …)
3. **Atributos de cada entidad y relación**
4. **Validar con instance model pequeño** antes de cargar producción
5. **Indexes y constraints early** — sin esto, el grafo no escala

Para tu caso de uso (PE/VC + PyMEs), una ontología razonable de partida tendría: Tenant, User, Deal, Company (participada), Person, Document, Process, Run, ProcessOutcome, Communication. Las relaciones temporales (PARTICIPATED_IN_DEAL with bi-temporal stamps) son donde Graphiti destaca.

### 5.3 Entity resolution — el problema crónico

Knowledge graphs without entity resolution often suffer from duplicate nodes (synonyms). These duplicate nodes in the graph limit the analytic potential (e.g., is it six customers, or actually just one customer with six facts?) Duplicate nodes can also make visualizations exceptionally noisy, obfuscating important patterns.

Para tu caso: "Acme Corp", "ACME Corp.", "acme-corp" llegan de tres fuentes distintas y son la misma compañía. Sin entity resolution explícita, el grafo se convierte en ruido.

Patrones:

- **Deterministic ER** — reglas exactas (mismo email + mismo NIF → mismo person). Rápido, brittle.
- **Probabilistic ER** — scoring por similitud (nombre, dirección, NIF parcial). Más robusto, requiere tuning.
- **ML ER** — embedding de entidades + clustering. Mejor recall, opaco.
- **LLM-driven ER** — preguntar a un LLM si dos entidades son la misma. Caro pero potente para casos complejos. Es lo que hacen Mem0/Zep.

### 5.4 Multi-tenancy en KG — zona gris

Esta es la zona donde la industria tiene **menos consenso**. Tres patrones observados:

1. **Graph-per-tenant** (Neo4j Aura, FalkorDB managed) — clean, caro.
2. **Tenant-aware properties** — cada nodo y relación lleva `tenant_id`; queries filtran. Equivalente al RLS, con los mismos riesgos de leak por bug en query.
3. **Sub-graph isolation** — un único graph físico con namespaces lógicos enforcement por capa de acceso.

Sin patrón ganador. Para tu sistema, la decisión razonable inicial es **tenant-aware properties + enforcement en el `memory-mcp-server`** (que añade el filtro `tenant_id` a toda query Cypher antes de mandarla al graph). Esto preserva tu disciplina (P18) sin requerir un Neo4j per tenant.

---

## 6. Event log — outbox y event sourcing

### 6.1 Tu modelo actual — outbox + Redpanda

Tu P5 + P6 + glosario describen exactamente el patrón canónico: CQRS can also be paired with the Outbox Pattern [...] An advantage with this design is there is still strong consistency within the application database but eventual consistency with the CQRS projections.

El **outbox pattern** resuelve atomicidad write-DB + write-bus:

```
BEGIN TRANSACTION
  INSERT INTO orders (...) VALUES (...);
  INSERT INTO event_log (event_type, payload) VALUES ('OrderCreated', ...);
COMMIT;

-- Proceso aparte: lee event_log, publica al bus, marca como entregado
```

Esto es **exactamente** tu D1 (outbox garantiza atomicidad write-storage + write-event) según el glosario.

### 6.2 Event sourcing vs CDC — cuándo cada uno

The Outbox table and the Event Sourcing journal have essentially the same data format. The major diffe[rence] — la diferencia es **intención**:

- **Outbox + projections** — la BD operativa tiene el estado canónico; el log se usa para notificar.
- **Event sourcing puro** — el log es el estado canónico; la BD se reconstruye del log.
- **CDC** — la BD es canónica; un proceso externo (Debezium) genera el log.

Para tu sistema: **outbox para eventos internos** (Run started, Trigger fired, etc.) + **CDC para ingestar fuentes externas** (Salesforce, ERPs del tenant). No event sourcing puro — la complejidad operacional de reconstruir estado desde log raramente vale la pena en sistemas SaaS modernos. It is a different and unfamiliar style of programming and so there is a learning curve. The event store is difficult to query since it requires typical queries to reconstruct the state of the business entities.

### 6.3 Replay-ability — tu requisito clave

Tu P5 declara "El bus es subset replay-able de la observabilidad — los eventos del bus persisten en `event_log` Postgres y permiten reconstruir el historial de Unidades Lógicas."

Esto es **event sourcing aplicado a las Unidades Lógicas** (no a las entidades de negocio). Decisión arquitectónica fina: tienes auditabilidad sin pagar el coste de event sourcing puro. **Mantén esta línea**.

---

## 7. Acceso desde Agents al `memory-mcp-server` — el patrón MCP-as-control-plane

Cierre relevante para tu P7 + P18:

### 7.1 Authorization en MCP servers — fine-grained, no all-or-nothing

Early MCP examples often use a single token that, if valid, grants access to the entire toolset. Such coarse-grained access control is convenient but dangerous. Using one broad token or API key as the gate means the agent either has no access or full access - there's no in-between.

La industria 2025-2026 ha consolidado:

MCP security operates through layered controls that protect each stage of AI agent interactions with enterprise systems. Centralized Gateway Architecture: A centralized gateway proxy applies consistent policies, monitors behavior, and enforces guardrails. The gateway enforces allowlisting of approved MCP servers, centralizes access control and identification, and inspects all tool invocations.

Pero también es claro que el **gateway no debe hacer fine-grained authorization**:

Capability Negotiation Phase: During initialization, the gateway inspects server capabilities against policy rules, blocking servers requesting excessive permissions. Fine-grained access controls map specific user roles to specific tool capabilities.

Esto es **exactamente** tu P20 (Gateway sin semántica de capa) + P18 (permission inheritance del invoking user, enforcement en el server de capa).

### 7.2 Patrón canónico de propagación de contexto

Cuando un Agent llama al `memory-mcp-server` para leer firm knowledge:

```
Agent Run (context: tenant_id=T, invoking_user_id=U)
   │
   ▼
Component memory-search (declara connection: internal/memory-mcp)
   │
   ▼
Llama memory-mcp-server con headers: {tenant_id, invoking_user_id, security_groups}
   │
   ▼
memory-mcp-server:
   1. Valida invoking_user_id pertenece a tenant_id (P18)
   2. Calcula effective_permissions = ∪(security_groups del user)
   3. SET LOCAL app.current_tenant_id = T  (RLS)
   4. Ejecuta query con filtros adicionales por permissions
   5. Devuelve sólo lo que el user puede ver
```

Esto es: tenant context propagation + permission filtering en la capa de servicio, no en el Agent ni en el Gateway.

### 7.3 Mapeo a tus principios

- **P7 (Capas internas mediadas)** — implementación canónica.
- **P11 (Connection internal)** — el Component `memory-search` declara conexión internal al memory-mcp-server; el Orchestrator inyecta service account / mTLS.
- **P18 (security groups + permission inheritance)** — enforcement vive en el server de capa, alineado con el patrón industrial.
- **P20 (Gateway sin semántica de capa)** — tu separación entre Gateway (auth básica + ruteo) y server de capa (RBAC fino) está alineada con OWASP MCP Top 10 y guidance industrial.

---

## 8. Síntesis — diseño de la Memoria del sistema en seis sub-sistemas

Destilo el research a un diseño concreto que respeta tus principios y se alinea con la industria:

```
┌─────────────────────────────────────────────────────────────────┐
│                        memory-mcp-server                        │
│  (MCP + REST sobre service layer único; auth + RLS + RBAC)      │
└──┬────────┬─────────┬───────────┬──────────┬─────────┬──────────┘
   │        │         │           │          │         │
   ▼        ▼         ▼           ▼          ▼         ▼
┌─────┐ ┌──────┐ ┌─────────┐ ┌──────────┐ ┌─────┐ ┌─────────┐
│Rel. │ │Object│ │ Vector  │ │Knowledge │ │Event│ │Agentic  │
│DB   │ │store │ │ store   │ │ Graph    │ │log  │ │memory   │
│(PG  │ │(S3-  │ │(pgvec→  │ │(Neo4j /  │ │(PG  │ │(curated │
│ RLS)│ │compat│ │ Weaviate│ │ FalkorDB)│ │ apnd│ │ on top  │
│     │ │ )    │ │ at scale│ │          │ │ only)│ │ of vec+ │
│     │ │      │ │ )       │ │          │ │     │ │ KG)     │
└──┬──┘ └──┬───┘ └────┬────┘ └────┬─────┘ └──┬──┘ └────┬────┘
   │       │          │           │          │         │
   └───────┴──────────┴───────────┴──────────┴─────────┘
                        │
            Ingesta: Debezium / Triggers / Components
                        │
                  Bus (Redpanda)
                        │
        ┌───────────────┴──────────────┐
        │                              │
   Bronze layer                  Operational stores
   (raw multi-source)            (alimentados desde silver)
        │
   Silver / Gold (analytics)
```

**Seis sub-sistemas con responsabilidad única**:

1. **Relational store (Postgres)** — tabular operacional + metadata + `event_log` + catálogo de Entidades. RLS no-negociable. Postgres es ciudadano de primera, no de segunda.

2. **Object store (S3-compatible: MinIO en POC, S3 en cloud)** — contenido binario de docs. Metadata en relational store con referencia al path/URI. Lifecycle policies (hot → cold → archive) declarativas.

3. **Vector store** — para embeddings. Empieza en pgvector con `tenant_id` particionado; migración a Weaviate/Qdrant con tenant-per-shard cuando el volumen lo justifique (esto deberá ser una decisión basada en métricas, no en intuición).

4. **Knowledge graph** — Neo4j o alternativa property-graph. Ontología explícita versionada (los `.cypher` con schema constraints son artefactos declarativos = encaja con P3). Entity resolution como sub-pipeline.

5. **Event log append-only** — ya cubierto por tu P5 + outbox D1. No requiere sub-sistema nuevo.

6. **Agentic memory layer** — **no es un store nuevo**; es una **vista curada** sobre vector + KG, gestionada por una pipeline de extracción asíncrona. Inspirado en Mem0/Zep, sin acoplarse a ninguno.

**Patrón de ingesta unificado** (P3 + P6):

- Fuentes externas → Connection external + Component conector → emite eventos al bus con shape estándar (`tenant_id`, `source_id`, `payload`, `timestamp`).
- Pipelines de procesamiento consumen → escriben a bronze → pipelines silver/gold → operational stores.
- Cada paso es un Run (durable, observable, versionado).

---

## 9. Zonas grises — donde la industria no tiene respuesta clara

Honestidad obligatoria sobre lo que no se sabe en 2026:

1. **Vector multi-tenancy a escala mediana (1K-10K tenants)** — pgvector se queda corto, Weaviate/Qdrant son overkill para POC. Zona muerta de tooling.

2. **Mem0 vs Zep vs roll-your-own** — los dos sistemas reclaman supremacía con benchmarks contradictorios. Sin ganador.

3. **Knowledge graph multi-tenant** — sin patrón estándar; cada implementación inventa el suyo.

4. **Cache de retrieval en sistemas agénticos** — la industria está dividida entre "siempre fresco" y "cache agresivo". Caso por caso.

5. **Memoria semántica curada vs raw** — ¿la memoria del agente guarda hechos extraídos por LLM (curado, lossy) o conversaciones enteras (raw, exhaustivo)? Sin consenso. Hybrid es la apuesta pragmática.

6. **Cuándo migrar de lakehouse / medallion a operational store** — los agentes en tiempo real NO deben leer del gold layer (latencia), pero el silver y el operational store divergen y mantenerlos sincronizados es caro. Diseño abierto.

7. **Schema evolution con datos ya vectorizados** — si re-defines la ontología o cambias el modelo de embeddings, la migración de un corpus de 10M chunks es costosa. Patrones de "blue-green embeddings" existen pero son inmaduros.

Estas zonas grises son **candidatas para entrar como temas abiertos** en tu §6 "Temas abiertos para discusión separada" del doc de principios cuando sea relevante.

---

## 10. Apéndice — checklist de validación contra tus principios

Antes de tomar cualquier decisión técnica sobre Memoria, validar contra:

- [ ] **P1 Simpleza** — ¿es el diseño más simple que cumple los requisitos? ¿Puedo justificar cada sub-sistema o estoy añadiendo por costumbre?
- [ ] **P2 Seis capas** — ¿la decisión vive limpiamente en capa 1 (Memoria) o cruza a otras?
- [ ] **P3 Declarativo first** — ¿lo configurable es YAML? ¿Hay código sólo en Components/Connections?
- [ ] **P5 Observabilidad** — ¿cada operación de memoria emite spans? ¿Coste y latencia visibles?
- [ ] **P7 Capas internas mediadas** — ¿los Agents acceden vía Component declarado + Connection internal al `memory-mcp-server`? ¿O hay acceso directo prohibido?
- [ ] **P11 Connections con scope + ámbito** — ¿internal vs external explícito? ¿Scope `system`/`tenant`/`user` correcto?
- [ ] **P12 Multi-tenant + RLS + dev/prod parity** — ¿tenant_id en toda tabla? ¿RLS forzado? ¿Funciona igual en docker compose y en k8s?
- [ ] **P16 Versionado inmutable** — si la decisión introduce schema, ¿tiene mecanismo de versión? ¿Pinning por Run?
- [ ] **P17 Stateless ready** — ¿el sub-sistema sobrevive a crash del proceso? ¿No depende de filesystem local?
- [ ] **P18 Tenancy y permisos** — ¿enforcement de security groups en el `memory-mcp-server`? ¿Permission inheritance del invoking user?
- [ ] **P19 LLM-agnóstico** — si involucra LLM (extracción, embeddings), ¿está detrás de un Adapter? ¿Hay formato neutro?
- [ ] **P20 Gateway sin semántica** — el Gateway sólo enruta; toda lógica de Memoria vive en el `memory-mcp-server`.
- [ ] **§8 Propósito** — la decisión preserva el carácter horizontal del sistema; no se especializa por vertical PE/PyME.

---

## Fuentes consultadas (selección)

- Weaviate — Multi-tenancy native architecture, tenant-per-shard, Tenant Controller (docs.weaviate.io)
- Pinecone — Namespaces y multitenancy patterns (docs.pinecone.io)
- pgvector — Issue #479 sobre HNSW + tenant_id filter degradation (github.com/pgvector/pgvector)
- PostgreSQL RLS — Patrones canónicos (Microsoft Learn, Redis blog, varios)
- Zep — Temporal Knowledge Graph paper (arxiv.org/abs/2501.13956), Graphiti
- Mem0 — Production-ready AI agents paper (arxiv.org/abs/2504.19413)
- Memory Survey — Memory in the Age of AI Agents (github.com/Shichun-Liu/Agent-Memory-Paper-List)
- AWS AgentCore — Long-term memory deep dive (aws.amazon.com/blogs)
- Databricks — Medallion architecture (docs.databricks.com/lakehouse/medallion)
- Debezium — Event Sourcing vs CDC (debezium.io/blog)
- Microservices.io — Event sourcing pattern (microservices.io)
- Neo4j — Entity resolution + ontology design (neo4j.com)
- Cerbos / Kong / SentinelOne — MCP authorization, RBAC, gateway patterns
- AgentBound — Access control framework for MCP (arxiv.org/pdf/2510.21236)
- StackAI / Applied-AI / Premai — RAG production architecture guides 2026

**Nota sobre fuentes**: la mayor parte del estado del arte de memoria agéntica es de 2025-2026 y vive en arxiv + blogs técnicos, no en libros consolidados. Cualquier afirmación específica de este doc debería re-verificarse cuando se acerque una decisión arquitectónica concreta — el campo se mueve mes a mes.
