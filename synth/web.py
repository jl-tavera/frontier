"""`/evals` on the service: every stored eval report as one page, newest first (S4)."""
import io
import os
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import ValidationError
from pydantic_evals.reporting import EvaluationReportAdapter
from rich.console import Console

from synth.eval import pct, rates, reports_dir

RUN_NAME = re.compile(r"\w[\w.-]*")
STAMP = re.compile(r"\d{8}-\d{4}")  # the CLI's default run name, `<fake|live>-<YYYYMMDD-HHMM>`
router = APIRouter()


def bearer(authorization: str = Header("")) -> None:
    """A's check from app/main.py, copied: importing it would be circular once main includes this router."""
    if not secrets.compare_digest(authorization.encode(), f"Bearer {os.environ['TEAM_TOKEN']}".encode()):
        raise HTTPException(401, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"})


def _when(path) -> datetime:
    """The stamp in the run name, else the file's mtime: the report itself carries no time."""
    # lazy: a custom name without a stamp orders by mtime, which in the image is the checkout time
    m = STAMP.search(path.stem)
    return datetime.strptime(m[0], "%Y%m%d-%H%M") if m else datetime.fromtimestamp(path.stat().st_mtime)


@router.get("/evals", response_class=HTMLResponse)
def page():
    paths = sorted(reports_dir().glob("*.json"), key=lambda p: (_when(p), p.name), reverse=True)
    runs = [(p, EvaluationReportAdapter.validate_json(p.read_bytes())) for p in paths]
    console = Console(record=True, width=200, file=io.StringIO())
    for p, r in runs:
        console.print(f"{r.name}  {_when(p):%Y-%m-%d %H:%M}  "
                      + "  ".join(f"{c} {pct(ok)}%" for c, ok in rates(r).items()), markup=False, highlight=False)
    if len(runs) > 1:
        runs[0][1].print(baseline=runs[1][1], console=console, include_averages=True)
    for _, r in runs:
        r.print(console=console, include_averages=True)
    return console.export_html(inline_styles=True)


@router.get("/evals/{run}.json")
def stored(run: str):
    path = reports_dir() / f"{run}.json"
    if not RUN_NAME.fullmatch(run) or not path.is_file():
        raise HTTPException(404, "unknown run")
    return FileResponse(path, media_type="application/json")


@router.post("/evals", status_code=201, dependencies=[Depends(bearer)])
async def store(request: Request):
    body = await request.body()
    try:
        report = EvaluationReportAdapter.validate_json(body)
    except ValidationError as e:
        raise HTTPException(422, str(e))
    if not RUN_NAME.fullmatch(report.name):
        raise HTTPException(422, f"bad run name: {report.name!r}")
    reports_dir().mkdir(parents=True, exist_ok=True)
    (reports_dir() / f"{report.name}.json").write_bytes(body)
    return {"name": report.name}
