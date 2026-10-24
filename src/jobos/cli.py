"""CLI estrita: flag desconhecida falha (código 3) e nunca cai em modo normal por engano (T32).

Códigos: 0 concluído, 2 parcial, 3 falha impeditiva, 4 sobreposição, 5 configuração necessária.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import platform
import socket
import sys
from pathlib import Path

from jobos import __version__

EXIT_OK, EXIT_PARTIAL, EXIT_FAILED, EXIT_OVERLAP, EXIT_CONFIG = 0, 2, 3, 4, 5

log = logging.getLogger("jobos.cli")


class StrictParser(argparse.ArgumentParser):
    def error(self, message):  # argparse usa 2 por padrão, que aqui significa "parcial"
        self.print_usage(sys.stderr)
        print(f"erro: {message}", file=sys.stderr)
        raise SystemExit(EXIT_FAILED)


def _parser() -> StrictParser:
    p = StrictParser(prog="python -m jobos", description="JOBOS local", allow_abbrev=False)
    p.add_argument("--version", action="version", version=f"jobos-local {__version__}")
    p.add_argument("--json", action="store_true", help="saída JSON")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=StrictParser)

    sub.add_parser("doctor", help="diagnóstico de ambiente, caminhos, banco, fontes e integrações", allow_abbrev=False)
    sp = sub.add_parser("import-legacy", help="importa histórico legado", allow_abbrev=False)
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true", help="somente relatório, sem gravar")
    g.add_argument("--apply", action="store_true", help="importa com backup e idempotência")
    sp.add_argument("--sqlite", type=Path, help="caminho do jobs.db legado (padrão: app.yaml)")
    sp.add_argument("--portal", type=Path, help="caminho do jobs.json do portal (padrão: app.yaml)")

    sub.add_parser("status", help="estado do engine (mesmo conteúdo de /api/status)", allow_abbrev=False)
    sb = sub.add_parser("backup", help="snapshot consistente + verificação de restauração", allow_abbrev=False)
    sb.add_argument("--label", default="manual")

    sc = sub.add_parser("cycle", help="executa um ciclo único", allow_abbrev=False)
    sc.add_argument("--dry-run", action="store_true", help="banco temporário; nada real é alterado ou enviado")
    sc.add_argument("--fixtures", action="store_true", help="offline com fixtures rotuladas (exige --dry-run)")
    sc.add_argument("--mode", choices=["manual", "scheduler"], default="manual")
    sc.add_argument("--no-notify", action="store_true", help="não enfileira resumo")

    sco = sub.add_parser("collect", help="coleta uma fonte", allow_abbrev=False)
    sco.add_argument("--source", required=True)
    sco.add_argument("--dry-run", action="store_true")

    sa = sub.add_parser("analyze", help="analisa vagas (determinístico)", allow_abbrev=False)
    ga = sa.add_mutually_exclusive_group(required=True)
    ga.add_argument("--job")
    ga.add_argument("--pending", action="store_true", help="vagas sem análise para a versão atual")

    scv = sub.add_parser("cv", help="kit de CV por vaga (local, sem IA, não marca envio)", allow_abbrev=False)
    scvsub = scv.add_subparsers(dest="cvcmd", required=True, parser_class=StrictParser)
    scvb = scvsub.add_parser("build", help="gera ou reaproveita o pacote da versão atual da vaga", allow_abbrev=False)
    scvb.add_argument("--job", required=True, help="id da vaga ou prefixo de 8+")
    scvb.add_argument("--headline", default=None, help="id do headline quando o preparo indica empate")

    ss = sub.add_parser("serve", help="API e painel local", allow_abbrev=False)
    ss.add_argument("--host", default=None)
    ss.add_argument("--port", type=int, default=None)
    ss.add_argument("--no-worker", action="store_true", help="não processa a fila (somente leitura e enfileiramento)")

    sw = sub.add_parser("work", help="processa a fila de trabalho uma vez", allow_abbrev=False)
    sw.add_argument("--once", action="store_true", required=True)

    sn = sub.add_parser("notifications", help="outbox", allow_abbrev=False)
    snsub = sn.add_subparsers(dest="ncmd", required=True, parser_class=StrictParser)
    snp = snsub.add_parser("preview", help="gera texto/HTML/.eml do último resumo, sem envio", allow_abbrev=False)
    snp.add_argument("--run")
    snsub.add_parser("list", help="itens da outbox", allow_abbrev=False)
    snr = snsub.add_parser("retry", help="envia itens elegíveis (exige configuração)", allow_abbrev=False)
    snr.add_argument("--dry-run", action="store_true", help="transporte simulado")

    sap = sub.add_parser("application", help="candidaturas", allow_abbrev=False)
    sasub = sap.add_subparsers(dest="acmd", required=True, parser_class=StrictParser)
    sasub.add_parser("list", allow_abbrev=False)
    sac = sasub.add_parser("confirm", help="registro manual de envio (user_asserted)", allow_abbrev=False)
    sac.add_argument("--job", required=True)
    sac.add_argument("--date", required=True, help="AAAA-MM-DD")
    sac.add_argument("--note")
    sas = sasub.add_parser("set-state", allow_abbrev=False)
    sas.add_argument("--job", required=True)
    sas.add_argument("--state", required=True)
    sas.add_argument("--reason", required=True)
    sal = sasub.add_parser("confirm-legacy-manual", help="marcações manuais originais do legado viram 'Aplicado'",
                           allow_abbrev=False)
    sal.add_argument("--apply", action="store_true", help="sem isto, só relatório")
    sast = sasub.add_parser("stage", allow_abbrev=False)
    sast.add_argument("--job", required=True)
    sast.add_argument("--stage", required=True)
    sast.add_argument("--reason")

    ssrc = sub.add_parser("source", help="manutenção de fontes", allow_abbrev=False)
    ssub = ssrc.add_subparsers(dest="scmd", required=True, parser_class=StrictParser)
    sret = ssub.add_parser("retire", help="anúncios de uma fonte desativada deixam de contar como ativos", allow_abbrev=False)
    sret.add_argument("--source", required=True)
    sret.add_argument("--reason", required=True)
    sret.add_argument("--apply", action="store_true", help="sem isto, só relatório")

    sbx = sub.add_parser("import-browser-export", help="importa marcações exportadas do localStorage", allow_abbrev=False)
    sbx.add_argument("--file", type=Path, required=True)
    sbx.add_argument("--apply", action="store_true", help="sem isto, só relatório")

    se = sub.add_parser("export-portal", help="gera jobs.json compatível em data/exports (não público)", allow_abbrev=False)
    se.add_argument("--out", type=Path)
    # `--json` aceito antes ou depois do subcomando (`jobos status --json`)
    stack = list(sub.choices.values())
    while stack:
        sp_ = stack.pop()
        sp_.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="saída JSON")
        for action in sp_._actions:
            if isinstance(action, argparse._SubParsersAction):
                stack.extend(action.choices.values())
    return p


def _emit(args, payload, text: str | None = None) -> None:
    if args.json or text is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(text)


def _setup_logging(paths) -> None:
    """Log diário do engine (logger "jobos" e filhos). Um único FileHandler por arquivo-alvo: trocar de dia ou de
    raiz substitui o anterior, sem empilhar handlers nem duplicar linhas."""
    paths.logs.mkdir(parents=True, exist_ok=True)
    from jobos.timeutil import brt_date
    target = os.path.abspath(paths.logs / f"jobos-{brt_date().isoformat()}.log")  # FileHandler guarda o mesmo abspath
    root = logging.getLogger("jobos")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler):
            if h.baseFilename == target:
                return
            root.removeHandler(h)
            h.close()
    handler = logging.FileHandler(target, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # logs do Agendador/pipes em UTF-8
    args = _parser().parse_args(argv)
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print("interrompido", file=sys.stderr)
        return EXIT_FAILED


def _dispatch(args) -> int:
    from jobos.paths import RootError, get_paths
    from jobos.settings import ConfigError
    try:
        paths = get_paths()
    except RootError as e:
        print(f"erro: {e}", file=sys.stderr)
        return EXIT_CONFIG
    _setup_logging(paths)
    try:
        handler = HANDLERS[args.cmd]
        log.info("comando %s iniciado (pid=%s)", args.cmd, os.getpid())
        code = handler(args)
        log.info("comando %s encerrado: código=%s", args.cmd, code)
        return code
    except ConfigError as e:
        log.error("configuração inválida: %s", e)
        print(f"configuração inválida: {e}", file=sys.stderr)
        return EXIT_CONFIG
    except Exception:
        log.exception("comando %s falhou", args.cmd)
        raise


# --------------------------------------------------------------------------- comandos

def cmd_doctor(args) -> int:
    from jobos.context import open_context
    from jobos.storage.db import integrity
    from jobos.timeutil import BRT, utcnow
    checks = []

    def add(name, ok, detail, level="error"):
        checks.append({"check": name, "ok": bool(ok), "level": "ok" if ok else level, "detail": detail})

    add("python", sys.version_info >= (3, 12), f"{platform.python_version()} em {sys.executable}")
    add("venv_proprio", ".venv" in sys.executable.replace("\\", "/"), sys.executable, "warning")
    try:
        import zoneinfo
        zoneinfo.ZoneInfo("America/Sao_Paulo")
        add("tzdata", True, f"agora em Brasília: {utcnow().astimezone(BRT).strftime('%d/%m/%Y %H:%M')}")
    except Exception as e:  # noqa: BLE001
        add("tzdata", False, str(e))
    ok_fuso, detalhe_fuso = _fuso_windows()
    add("fuso_windows", ok_fuso, detalhe_fuso, "warning")  # só diagnóstico: nunca falha o doctor
    ctx = open_context()
    try:
        p = ctx.paths
        add("raiz", (p.root / "pyproject.toml").is_file(), str(p.root))
        add("cwd_independente", True, f"cwd={os.getcwd()}")
        integ = integrity(ctx.con)
        add("banco", integ["integrity_check"] == "ok" and integ["foreign_key_violations"] == 0,
            f"{p.db} {integ}")
        jm = ctx.con.execute("PRAGMA journal_mode").fetchone()[0]
        add("banco_wal", jm == "wal", f"journal_mode={jm}", "warning")
        add("perfil", ctx.profile_state.get("file_valid"), ctx.profile_state)
        imports = ctx.con.execute("SELECT COUNT(*) FROM imports WHERE status='complete'").fetchone()[0]
        add("historico_importado", imports > 0, f"{imports} importação(ões) concluída(s); use import-legacy --apply",
            "warning")
        runnable = ctx.registry.runnable()
        add("fontes", True, f"{len(ctx.registry.sources)} cadastradas, {len(runnable)} com leitor ativo")
        for key in ("sqlite", "portal_json", "profile_json"):
            lp = ctx.settings.legacy_path(key)
            add(f"legado_{key}", lp.is_file(), str(lp), "warning")
        notif = ctx.settings.notifications
        add("smtp", True, "envio desligado (preview apenas)" if not notif.get("enabled") else
            f"habilitado para {'destinatário configurado' if notif.get('recipient') else 'SEM destinatário'}")
        add("ia", True, "desligada (análise determinística)" if not (ctx.settings.matching.get("ai") or {}).get("enabled")
            else "habilitada")
        srv = ctx.settings.app.get("server") or {}
        host, port = srv.get("host", "127.0.0.1"), int(srv.get("port", 8776))
        add("bind_loopback", host in ("127.0.0.1", "localhost"), host)
        add("porta_painel", _port_free(host, port), f"{host}:{port} {'livre' if _port_free(host, port) else 'ocupada'}",
            "warning")
        add("cv_builder", False, "bloqueado: código/esquema do CV Builder não encontrado no workspace (P6)", "blocked")
        lock_owner = None
        from jobos.lock import CycleLock, LockBusy
        lk = CycleLock(p.lock_file)
        try:
            lk.acquire({"run_id": "doctor"})
            lk.release()
            add("trava_ciclo", True, "livre")
        except LockBusy as b:
            lock_owner = b.owner
            add("trava_ciclo", True, f"ciclo em execução: {lock_owner}", "warning")
    finally:
        ctx.close()
    failed = [c for c in checks if c["level"] == "error"]
    if args.json:
        _emit(args, {"checks": checks, "ok": not failed})
    else:
        for c in checks:
            mark = {"ok": "OK  ", "warning": "AVISO", "error": "ERRO", "blocked": "BLOQ"}[c["level"]]
            print(f"[{mark}] {c['check']}: {c['detail']}")
    return EXIT_OK if not failed else EXIT_FAILED


def _fmt_utc(td: dt.timedelta) -> str:
    minutos = int(td.total_seconds()) // 60
    h, m = divmod(abs(minutos), 60)
    return f"UTC{'+' if minutos >= 0 else '-'}{h:02d}:{m:02d}"


def _fuso_windows(os_offset: dt.timedelta | None = None) -> tuple[bool, str]:
    """Compara o deslocamento UTC do SO agora com o de America/Sao_Paulo. Só diagnostica; nunca altera o fuso do PC."""
    from jobos.timeutil import BRT
    agora = dt.datetime.now().astimezone()
    local = os_offset if os_offset is not None else agora.utcoffset()
    brasilia = agora.astimezone(BRT).utcoffset()
    detalhe = f"SO {_fmt_utc(local)} | America/Sao_Paulo {_fmt_utc(brasilia)}"
    if local == brasilia:
        return True, detalhe
    return False, f"{detalhe}: fuso do Windows difere de Brasília; horários do Agendador podem ficar deslocados"


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def cmd_import_legacy(args) -> int:
    from jobos.legacy import importer
    from jobos.context import open_context
    from jobos.paths import get_paths
    from jobos.settings import load_settings
    paths = get_paths()
    settings = load_settings(paths)
    sqlite_path = (args.sqlite or settings.legacy_path("sqlite")).resolve()
    portal_path = (args.portal or settings.legacy_path("portal_json")).resolve()
    if args.plan:
        out = {"mode": "plan", "sqlite": importer.plan_sqlite(sqlite_path) if sqlite_path.is_file() else "ausente",
               "portal": importer.plan_portal(portal_path) if portal_path.is_file() else "ausente",
               "note": "nada foi gravado"}
        _emit(args, out)
        return EXIT_OK
    ctx = open_context()
    try:
        from jobos.backup import make_backup
        pre = make_backup(ctx, label="pre-import") if ctx.con.execute("SELECT COUNT(*) FROM job_records").fetchone()[0] else None
        res = {"mode": "apply", "backup_before": pre["path"] if pre else "banco vazio, sem backup prévio necessário"}
        if sqlite_path.is_file():
            res["sqlite"] = importer.apply_sqlite(ctx.con, ctx.settings, ctx.registry, sqlite_path)
        if portal_path.is_file():
            res["portal"] = importer.apply_portal(ctx.con, ctx.settings, ctx.registry, portal_path)
        from jobos.storage.db import integrity
        res["integrity"] = integrity(ctx.con)
        _emit(args, res)
        return EXIT_OK if res["integrity"]["integrity_check"] == "ok" else EXIT_FAILED
    finally:
        ctx.close()


def cmd_status(args) -> int:
    from jobos.context import open_context
    from jobos.status import build_status
    ctx = open_context()
    try:
        st = build_status(ctx.con, ctx.settings, ctx.registry)
    finally:
        ctx.close()
    if args.json:
        _emit(args, st)
        return EXIT_OK
    j, a, r = st["jobs"], st["applications"], st["runs"]
    last = r["last"]
    lines = [
        f"Banco: {st['database']} (schema v{st['schema_version']})",
        f"Vagas: {j['total']} | por estado: {j['by_listing_state']} | banco de talentos: {j['talent_pool']}",
        f"Novas alertáveis 24h: {j['alertable_new_24h']} | alteradas 24h: {j['alertable_changed_24h']}",
        f"Candidaturas: {a['by_prep_state']} | enviadas comprovadas/afirmadas: {a['proven_submitted']} | "
        f"legado a revisar: {a['legacy_needs_review']}",
        f"Último ciclo: {last['run_id'] + ' ' + last['status'] + ' em ' + last['started_brt'] if last else 'nunca'}",
        f"Próximo horário agendado (Brasília): {r['next_scheduled_brt']} | atrasado: {'sim' if r['late'] else 'não'}",
        f"Fontes: {st['sources']['by_last_status']}",
        f"Outbox: {st['outbox']['by_status']} | envio habilitado: {st['outbox']['sending_enabled']}",
        f"Perfil ativo: {(st['profile']['active_profile_id'] or 'nenhum')[:16]}",
    ]
    print("\n".join(lines))
    return EXIT_OK


def cmd_backup(args) -> int:
    from jobos.backup import make_backup
    from jobos.context import open_context
    ctx = open_context()
    try:
        res = make_backup(ctx, label=args.label)
    finally:
        ctx.close()
    ok = res["database"]["integrity_check"] == "ok" and res["restore_check"].get("ok")
    _emit(args, {"path": res["path"], "database": res["database"], "restore_check_ok": res["restore_check"].get("ok"),
                 "mismatch": res["restore_check"].get("mismatch")},
          f"Backup: {res['path']}\nintegridade={res['database']['integrity_check']} "
          f"restauração verificada={'sim' if res['restore_check'].get('ok') else 'NÃO'}")
    return EXIT_OK if ok else EXIT_FAILED


def cmd_cycle(args) -> int:
    from jobos.context import open_context
    from jobos.pipeline import run_cycle
    if args.fixtures and not args.dry_run:
        print("erro: --fixtures exige --dry-run (fixture não entra no banco real)", file=sys.stderr)
        return EXIT_FAILED
    ctx = open_context(dry_run=args.dry_run)
    try:
        res = run_cycle(ctx, trigger=args.mode, fixtures=args.fixtures, notify=not args.no_notify)
        if args.dry_run:
            from jobos.storage.db import table_counts
            res.stages["dry_run_db_counts"] = table_counts(ctx.con, ["job_records", "job_versions", "notification_outbox"])
    finally:
        ctx.close()
    _print_cycle(args, res)
    return res.exit_code


def _print_cycle(args, res) -> None:
    log.info("ciclo run_id=%s modo=%s gatilho=%s status=%s código=%s", res.run_id, res.mode, res.trigger, res.status,
             res.exit_code)
    for s in res.sources:
        log.info("fonte %s status=%s vagas=%s novas=%s alteradas=%s ausentes=%s encerradas=%s erro=%s", s["source_id"],
                 s["status"], s["jobs"], s["new"], s["changed"], s["missing"], s["closed"], s.get("error") or "-")
    if args.json:
        _emit(args, res.as_dict())
        return
    print(f"run_id={res.run_id} modo={res.mode} status={res.status} código={res.exit_code}")
    if res.lock_owner:
        print(f"  trava ocupada por: {res.lock_owner}")
    for s in res.sources:
        extra = f" erro={s['error']}" if s.get("error") else ""
        print(f"  {s['source_id']:<22} {s['status']:<12} vagas={s['jobs']:<4} novas={s['new']:<3} alteradas={s['changed']:<3}"
              f" ausentes={s['missing']} encerradas={s['closed']} ausência={s['absence']}{extra}")
    print(f"  totais={res.counts} etapas={ {k: v for k, v in res.stages.items() if k != 'dry_run_db_counts'} }")
    if "dry_run_db_counts" in res.stages:
        print(f"  (dry run) contagens no banco temporário: {res.stages['dry_run_db_counts']}")


def cmd_collect(args) -> int:
    from jobos.context import open_context
    from jobos.pipeline import run_cycle
    ctx = open_context(dry_run=args.dry_run)
    try:
        ctx.registry.get(args.source)
        res = run_cycle(ctx, trigger="manual", only_sources=[args.source], notify=False)
    finally:
        ctx.close()
    _print_cycle(args, res)
    return res.exit_code


def cmd_analyze(args) -> int:
    from jobos.applications.service import resolve_job_id
    from jobos.context import open_context
    from jobos.matching.analyze import analyze_job, analyze_pending
    ctx = open_context()
    try:
        if args.job:
            out = analyze_job(ctx, resolve_job_id(ctx.con, args.job), force=True)
        else:
            out = analyze_pending(ctx)
    finally:
        ctx.close()
    _emit(args, out)
    return EXIT_OK


def cmd_cv(args) -> int:
    """`cv build`: pacote em data/artifacts/<vaga>/<hash12>/. Gerar CV nunca significa candidatura enviada."""
    from jobos.applications.service import resolve_job_id
    from jobos.context import open_context
    from jobos.matching.cv_packet import PacketError, build_packet
    ctx = open_context()
    try:
        try:
            res = build_packet(ctx, resolve_job_id(ctx.con, args.job), headline_id=args.headline)
        except (PacketError, LookupError, ValueError) as e:
            print(f"erro: {e}", file=sys.stderr)
            return EXIT_FAILED
    finally:
        ctx.close()
    payload = {"job_id": res.job_id, "input_hash": res.input_hash, "directory": str(res.directory),
               "reused": res.reused, "kept": res.kept, "dropped": res.dropped, "registered": res.registered,
               "artifact_ids": res.artifact_ids, "warnings": res.warnings, "files": res.files}
    _emit(args, payload, "\n".join([
        f"pacote {'reaproveitado' if res.reused else 'gerado'}: {res.directory}",
        f"linhas mantidas={res.kept} descartadas={res.dropped} registrado={'sim' if res.registered else 'não'}",
        *(f"aviso: {w}" for w in res.warnings),
        "abra cv.html no navegador e salve como PDF; isto não marca a candidatura como enviada.",
    ]))
    return EXIT_OK


def cmd_serve(args) -> int:
    import uvicorn
    from jobos.api.app import create_app
    from jobos.paths import get_paths
    from jobos.settings import load_settings
    settings = load_settings(get_paths())
    srv = settings.app.get("server") or {}
    host = args.host or srv.get("host", "127.0.0.1")
    port = args.port or int(srv.get("port", 8776))
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("erro: o painel só escuta em loopback (127.0.0.1)", file=sys.stderr)
        return EXIT_CONFIG
    if not _port_free(host, port):
        print(f"erro: porta {port} ocupada em {host}; use --port com outra porta (nenhum processo foi encerrado)",
              file=sys.stderr)
        return EXIT_CONFIG
    app = create_app(port=port, worker=not args.no_worker)
    print(f"JOBOS painel em http://{host}:{port}/painel/  (portal em http://{host}:{port}/)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return EXIT_OK


def cmd_work(args) -> int:
    from jobos.api.worker import process_queue_once
    from jobos.context import open_context
    ctx = open_context()
    try:
        out = process_queue_once(ctx, owner=f"cli-{os.getpid()}")
    finally:
        ctx.close()
    _emit(args, out)
    return out.get("exit_code", EXIT_OK)


def cmd_notifications(args) -> int:
    from jobos.context import open_context
    from jobos.notifications import outbox
    # retry --dry-run usa banco temporário: transporte simulado nunca marca item real como enviado
    ctx = open_context(dry_run=bool(args.ncmd == "retry" and args.dry_run))
    try:
        if args.ncmd == "preview":
            out = outbox.preview(ctx, run_id=args.run)
            _emit(args, out, f"Preview gerado em {out.get('dir')} ({out.get('subject')})" if out.get("dir") else
                  "Nada para pré-visualizar (nenhum item na outbox)")
            return EXIT_OK
        if args.ncmd == "list":
            _emit(args, outbox.list_items(ctx))
            return EXIT_OK
        if args.ncmd == "retry":
            out = outbox.process(ctx, simulate=args.dry_run)
            _emit(args, out)
            return out.get("exit_code", EXIT_OK)
    finally:
        ctx.close()
    return EXIT_FAILED


def cmd_application(args) -> int:
    from jobos.applications import service
    from jobos.context import open_context
    from jobos.domain.states import TransitionError
    ctx = open_context()
    try:
        if args.acmd == "list":
            items = service.list_applications(ctx.con)
            if args.json:
                _emit(args, items)
            else:
                for a in items:
                    print(f"{a['job_id'][:8]} {a['tag']['label']:<24} {a['selection_stage']:<10} {a['company_name']} | "
                          f"{a['title']} | {a['tag']['hint']}")
                print(f"{len(items)} candidatura(s); enviadas afirmadas/comprovadas: "
                      f"{sum(1 for a in items if a['counts_as_submitted'])}")
            return EXIT_OK
        if args.acmd == "confirm-legacy-manual":
            from jobos.timeutil import brt_date
            out = service.confirm_legacy_manual_marks(ctx.con, apply=args.apply, confirmed_on=brt_date().isoformat())
        elif args.acmd == "confirm":
            out = service.confirm_manual(ctx.con, args.job, args.date, args.note)
        elif args.acmd == "set-state":
            out = service.transition(ctx.con, args.job, args.state, origin="user_asserted", reason=args.reason)
        else:
            out = service.set_stage(ctx.con, args.job, args.stage, reason=args.reason)
        _emit(args, out)
        return EXIT_OK
    except (TransitionError, service.NotFound, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return EXIT_FAILED
    finally:
        ctx.close()


def cmd_import_browser_export(args) -> int:
    from jobos.context import open_context
    from jobos.legacy.browser_export import import_export
    ctx = open_context()
    try:
        out = import_export(ctx, args.file, apply=args.apply)
    finally:
        ctx.close()
    _emit(args, out)
    return EXIT_OK


def cmd_export_portal(args) -> int:
    from jobos.context import open_context
    from jobos.exports.portal import build_book
    ctx = open_context()
    try:
        book = build_book(ctx)
    finally:
        ctx.close()
    out = args.out or (ctx.paths.exports / "jobs.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    _emit(args, {"path": str(out), "companies": len(book["companies"]),
                 "jobs": sum(len(c["jobs"]) for c in book["companies"])})
    return EXIT_OK


def cmd_source(args) -> int:
    from jobos.context import open_context
    from jobos.persistence import retire_source
    ctx = open_context()
    try:
        src = ctx.registry.get(args.source)
        if src.enabled:
            print("erro: desative a fonte em config/sources.yaml (enabled: false) antes de aposentá-la", file=sys.stderr)
            return EXIT_FAILED
        out = retire_source(ctx.con, args.source, args.reason, apply=args.apply)
    finally:
        ctx.close()
    _emit(args, out)
    return EXIT_OK


HANDLERS = {
    "doctor": cmd_doctor, "import-legacy": cmd_import_legacy, "status": cmd_status, "backup": cmd_backup,
    "cycle": cmd_cycle, "collect": cmd_collect, "analyze": cmd_analyze, "cv": cmd_cv, "serve": cmd_serve, "work": cmd_work,
    "notifications": cmd_notifications, "application": cmd_application,
    "import-browser-export": cmd_import_browser_export, "export-portal": cmd_export_portal, "source": cmd_source,
}
