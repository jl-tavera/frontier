from app.agent.parse import Plan, Query, parse_task
from tests.fakes.llm import FakeLLM

ENTITIES = [
    {"id": "facturas", "name": "Facturas", "columns": ["Número", "Cliente", "Estado", "Total"]},
    {"id": "pedidos", "name": "Pedidos", "columns": ["Número", "Cliente", "Fecha"]},
]
PROCEDURES = [("create", "pedidos")]


async def test_lookup_parses_to_one_count_read_on_the_facturas_node():
    llm = FakeLLM({"queries": [{"op": "read", "entity": "facturas", "where": {"Estado": "Vencida"}, "aggregate": "count"}],
                   "confidence": 0.95})

    plan = await parse_task("¿Cuántas facturas vencidas hay?", ENTITIES, PROCEDURES, llm=llm)

    assert plan.queries == [Query("read", "facturas", where={"Estado": "Vencida"}, aggregate="count")]
    assert plan.confidence == 0.95
    [call] = llm.calls
    assert call["model"] == "test/fast"
    assert call["response_format"] == {"type": "json_object"}
    prompt = str(call["messages"])
    assert "facturas" in prompt and "Estado" in prompt and "pedidos" in prompt


async def test_create_task_parses_to_one_create_with_fields():
    llm = FakeLLM({"queries": [{"op": "create", "entity": "pedidos", "fields": {"Cliente": "Ruiz"}}], "confidence": 0.9})

    plan = await parse_task("Crea un pedido para Ruiz", ENTITIES, PROCEDURES, llm=llm)

    assert plan.queries == [Query("create", "pedidos", fields={"Cliente": "Ruiz"})]
    assert plan.confidence >= 0.8


async def test_gibberish_is_unsure():
    llm = FakeLLM({"queries": [], "confidence": 0.95})

    plan = await parse_task("asdkj qwe zzz", ENTITIES, PROCEDURES, llm=llm)

    assert plan.confidence < 0.8


async def test_a_query_on_an_entity_the_app_lacks_is_unsure_even_when_the_model_is_sure():
    llm = FakeLLM({"queries": [{"op": "read", "entity": "naves", "aggregate": "count"}], "confidence": 0.99})

    plan = await parse_task("¿Cuántas naves hay?", ENTITIES, PROCEDURES, llm=llm)

    assert plan.confidence < 0.8


async def test_output_that_is_not_json_is_unsure_not_a_crash():
    plan = await parse_task("¿Cuántas facturas vencidas hay?", ENTITIES, PROCEDURES, llm=FakeLLM("lo siento, no puedo"))

    assert plan == Plan([], 0.0)
