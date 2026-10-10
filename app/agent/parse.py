"""Task → typed queries: one MODEL_FAST call in JSON mode (F §4.1 step 1)."""
import json
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from app.agent.llm import chat_json

Op = Literal["read", "create", "update", "delete", "explore"]
OPS = set(get_args(Op))


@dataclass
class Query:
    op: Op
    entity: str  # app-map node id
    where: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)
    aggregate: str | None = None  # count | sum:<col> | avg:<col> | min:<col> | max:<col>
    key: str | None = None  # the record's identifying value, for update / delete


@dataclass
class Plan:
    queries: list[Query]
    confidence: float


SYSTEM = """You turn a task for a desktop business app into typed queries. Reply with JSON only:
{"queries": [{"op": "read|create|update|delete|explore", "entity": "<entity id>", "where": {"<column>": <value>},
"fields": {"<column>": <value>}, "aggregate": "count|sum:<column>|avg:<column>|min:<column>|max:<column>|null",
"key": "<record id or null>"}], "confidence": <0..1>}
- entity is always one of the entity ids given; where/fields use that entity's columns.
- read: where filters, aggregate when the task asks for a number. create: fields. update: key + fields. delete: key.
- procedures are the [op, entity] pairs the app already knows how to do; prefer queries that match one.
- explore when the task names something outside the entities.
- confidence is how sure you are the queries capture the whole task; below 0.5 when the task is unclear."""


async def parse_task(text: str, entities: list[dict], procedures: list[tuple[str, str]], llm=None) -> Plan:
    """`entities`: [{id, name, columns}] from the cache; `procedures`: stored (op, entity) pairs.
    Unparseable output, no queries or a query off the given ops/entities gives confidence 0, so the caller hands off."""
    user = json.dumps({"task": text, "entities": entities, "procedures": procedures}, ensure_ascii=False)
    try:
        out = await chat_json("fast", [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], llm)
        known = {e["id"] for e in entities}
        queries = [Query(q["op"], q["entity"], q.get("where") or {}, q.get("fields") or {}, q.get("aggregate"), q.get("key"))
                   for q in out["queries"]]
        confidence = float(out["confidence"])
    except (ValueError, KeyError, TypeError):
        return Plan([], 0.0)
    if not queries or any(q.op not in OPS or (q.entity not in known and q.op != "explore") for q in queries):
        return Plan(queries, 0.0)
    return Plan(queries, confidence)
