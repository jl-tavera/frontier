"""A hand-made `cache.sqlite` in the Appendix G §4.5 schema, typed the way the paging acquirer stores rows
(dates ISO, amounts int, NITs text). Entity ids are app-map node ids, so `synth` must find them by headers."""
import json
import sqlite3
from pathlib import Path

CLIENTES = ["Código", "NIT", "Razón social o nombre", "Ciudad", "Teléfono"]
FACTURAS = ["Código", "Cliente", "Fecha", "Vence", "Valor", "Estado"]
PEDIDOS = ["Código", "Cliente", "Fecha", "Total", "Estado"]
BITACORA = ["Hora", "Usuario", "Pantalla", "Registro", "Campo", "Antes", "Después", "Acción"]

ROWS = {
    "comercial-maestros-clientes": (CLIENTES, [
        ("CL-0001", "900123456-7", "Ferretería Ruiz", "Bogotá", "3001234567"),
        ("CL-0002", "800555111-2", "Distribuciones El Faro", "Cali", "3109876543"),
        ("CL-0003", "52345678", "Ana Torres", "Medellín", "3014440000"),
        ("CL-0004", "1019876543", "Ana Torres", "Bogotá", "3205551212"),
        ("CL-0005", "901777888-1", "Almacén Díaz", "Pereira", "3157770000"),  # no facturas, no pedidos
        ("CL-0006", "860222333-4", "Comercial Ruiz", "Barranquilla", "3123334455"),
        ("CL-0007", "830444555-6", "Depósito Hernández", "Cali", "3186660000"),
    ]),
    "cartera-facturas": (FACTURAS, [
        ("FV-10001", "Ferretería Ruiz", "2026-09-12", "2026-10-13", 450000, "Vencida"),
        ("FV-10002", "Ferretería Ruiz", "2026-09-13", "2026-10-13", 1250000, "Vencida"),
        ("FV-10003", "Ferretería Ruiz", "2026-08-01", "2026-08-31", 990000, "Pagada"),
        ("FV-10009", "Ferretería Ruiz", "2026-07-05", "2026-08-04", 820000, "Vencida"),
        ("FV-10004", "Distribuciones El Faro", "2026-09-01", "2026-10-01", 3210000, "Vencida"),
        ("FV-10005", "Distribuciones El Faro", "2026-09-15", "2026-10-15", 1600000, "Pendiente"),
        ("FV-10006", "Comercial Ruiz", "2026-09-16", "2026-10-16", 2380000, "Pendiente"),
        ("FV-10007", "Comercial Ruiz", "2026-08-20", "2026-09-19", 700000, "Pagada"),
        ("FV-10008", "Ana Torres", "2026-09-10", "2026-10-10", 500000, "Vencida"),
        ("FV-10010", "Depósito Hernández", "2026-09-20", "2026-10-20", 310000, "Pagada"),
    ]),
    "comercial-ventas-pedidos": (PEDIDOS, [
        ("PD-2001", "Ferretería Ruiz", "2026-09-03", 1200000, "Entregado"),
        ("PD-2002", "Distribuciones El Faro", "2026-09-18", 860000, "Entregado"),
        ("PD-2006", "Depósito Hernández", "2026-09-25", 150000, "Entregado"),
        ("PD-2003", "Ferretería Ruiz", "2026-10-02", 540000, "Confirmado"),
        ("PD-2004", "Comercial Ruiz", "2026-10-05", 300000, "Confirmado"),
        ("PD-2005", "Distribuciones El Faro", "2026-10-08", 450000, "Confirmado"),
        ("PD-2007", "Comercial Ruiz", "2026-09-28", 210000, "Confirmado"),
    ]),
    "herramientas-bitacora": (BITACORA, [
        ("13/10/2026 10:05", "operador2", "pedidos/PD-0010", "Pedido PD-0010", "Estado", "Borrador", "Confirmado", "Edición"),
        ("10/10/2026 15:42", "operador2", "clientes/CL-0031", "Cliente CL-0031", "Ciudad", "Pereira", "Cali", "Edición"),
    ]),
}

SCHEMA = """CREATE TABLE rows (app_id TEXT NOT NULL, entity TEXT NOT NULL, natural_key TEXT NOT NULL,
  data_json TEXT NOT NULL, row_hash TEXT NOT NULL, acquired_at TEXT NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY (app_id, entity, natural_key))"""


def build(path: Path) -> Path:
    db = sqlite3.connect(path)
    db.execute(SCHEMA)
    for entity, (headers, rows) in ROWS.items():
        for i, r in enumerate(rows):
            data = json.dumps({**dict(zip(headers, r)), "_unparsed": []}, ensure_ascii=False)
            db.execute("INSERT INTO rows VALUES ('sigecom', ?, ?, ?, ?, '2026-10-14T08:00:00', 'ocr')",
                       (entity, str(i), data, f"h{i}"))
    db.commit()
    db.close()
    return path
