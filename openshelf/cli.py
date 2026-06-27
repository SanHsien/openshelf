"""OpenShelf 指令進入點：login / scan / export / status / report / doctor /
acsm-* / ebook-* / calibre-* / ui。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import acsm, calibre, playbooks, reader, service
from .config import load_config
from .manifest import Manifest
from .playbooks import EndpointNotConfigured
from .session import NotLoggedIn, SessionExpired, build_client

console = Console()


@click.group(help="枚舉並批次匯出 Google Play 圖書（無 DRM 抓 EPUB/PDF；DRM 抓 .acsm 供 ADE）。")
@click.option("--config", "config_path", default=None, help="設定檔路徑（預設專案根目錄 config.toml）。")
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)


@main.command(help="開啟瀏覽器手動登入一次，保存登入態。")
@click.option("--headless", is_flag=True, help="無頭模式（通常需先有可用 profile）。")
@click.pass_context
def login(ctx: click.Context, headless: bool) -> None:
    from .browser import login as do_login

    cfg = ctx.obj["config"]
    path = do_login(cfg, headless=headless)
    console.print(f"[green]登入態已保存：[/green]{path}")


@main.command(help="以 HTTP 枚舉書庫並分類，寫入 manifest。")
@click.pass_context
def scan(ctx: click.Context) -> None:
    cfg = ctx.obj["config"]
    try:
        result = service.scan(cfg, log=console.print)
    except (NotLoggedIn, SessionExpired) as e:
        raise click.ClickException(str(e))
    except EndpointNotConfigured as e:
        raise click.ClickException(str(e))
    _print_counts(result.manifest, cfg)


@main.command(help="以 HTTP 下載可匯出的書（EPUB/PDF 或 .acsm）。")
@click.option("--format", "fmt", type=click.Choice(["epub", "pdf"]), default=None, help="無 DRM 書偏好格式。")
@click.option("--skip-acsm", is_flag=True, help="只下載無 DRM 書，DRM 書僅記錄不抓 .acsm。")
@click.option("--only", type=click.Choice(["drm_free", "acsm"]), default=None, help="只下載某一分類（測試用）。")
@click.option("--limit", type=int, default=None, help="最多下載幾本（測試用）。")
@click.option("--refresh-acsm", is_flag=True, help="重抓已逾有效天數的 .acsm（以下載時間為準）。")
@click.option("--skip-failed", is_flag=True, help="略過已標記 failed 的書（如 Google 端不給檔者），不再重試。")
@click.pass_context
def export(
    ctx: click.Context,
    fmt: str | None,
    skip_acsm: bool,
    only: str | None,
    limit: int | None,
    refresh_acsm: bool,
    skip_failed: bool,
) -> None:
    cfg = ctx.obj["config"]
    prefer = fmt or cfg.prefer_format
    include_acsm = cfg.include_acsm and not skip_acsm

    manifest = Manifest.load(cfg.manifest_path)
    if not manifest.books:
        raise click.ClickException("manifest 為空，請先執行：openshelf scan")

    try:
        result = service.export(
            cfg,
            prefer,
            include_acsm,
            log=console.print,
            limit=limit,
            only=only,
            refresh_acsm=refresh_acsm,
            skip_failed=skip_failed,
        )
    except (NotLoggedIn, SessionExpired) as e:
        raise click.ClickException(str(e))
    except EndpointNotConfigured as e:
        raise click.ClickException(str(e))

    console.print(
        f"\n完成：下載 {result.done}、跳過 {result.skipped}、失敗 {result.failed}"
    )
    _print_counts(Manifest.load(cfg.manifest_path), cfg)


@main.command(help="顯示 manifest 統計，並更新輸出目錄的下載報表。")
@click.pass_context
def status(ctx: click.Context) -> None:
    cfg = ctx.obj["config"]
    manifest = Manifest.load(cfg.manifest_path)
    _print_counts(manifest, cfg)
    if manifest.books:
        console.print(f"報表已寫入：{service.write_report(manifest, cfg)}")


@main.command(help="在輸出目錄產生報表：txt（缺漏清單）／csv／html。")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["txt", "csv", "html", "all"]),
    default="all",
    help="報表格式（預設全部產生）。",
)
@click.pass_context
def report(ctx: click.Context, fmt: str) -> None:
    cfg = ctx.obj["config"]
    manifest = Manifest.load(cfg.manifest_path)
    if not manifest.books:
        raise click.ClickException("manifest 為空，請先執行：openshelf scan")
    paths = []
    if fmt in ("txt", "all"):
        paths.append(service.write_report(manifest, cfg))
    if fmt in ("csv", "all"):
        paths.append(service.write_csv(manifest, cfg))
    if fmt in ("html", "all"):
        paths.append(service.write_html(manifest, cfg))
    for p in paths:
        console.print(f"[green]已寫入：[/green]{p}")


@main.command("calibre-import", help="把已下載的無 DRM EPUB/PDF 匯入 Calibre 書庫。")
@click.option("--library-path", default=None, help="指定 Calibre 書庫路徑。")
@click.option("--dry-run", is_flag=True, help="只列出可匯入數量，不執行 calibredb。")
@click.pass_context
def calibre_import(
    ctx: click.Context,
    library_path: str | None,
    dry_run: bool,
) -> None:
    cfg = ctx.obj["config"]
    manifest = Manifest.load(cfg.manifest_path)
    if not manifest.books:
        raise click.ClickException("manifest 為空，請先執行：openshelf scan")

    try:
        result = calibre.import_drm_free(
            cfg,
            manifest,
            library_path=Path(library_path) if library_path else None,
            dry_run=dry_run,
        )
    except calibre.CalibreNotFound as e:
        raise click.ClickException(str(e))
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"Calibre 匯入失敗（exit {e.returncode}）。")

    report_path = calibre.write_report(manifest, cfg)
    plan = result.plan
    if dry_run:
        console.print(
            f"可匯入 {len(plan.importable)} 本、檔案遺失 {len(plan.missing)} 本、"
            f".acsm 不匯入 {len(plan.acsm)} 本。"
        )
    else:
        console.print(f"[green]已匯入 Calibre：[/green]{result.imported} 本")
    console.print(f"Calibre 交接報表已寫入：{report_path}")


@main.command("calibre-report", help="產生 Calibre 交接報表，不執行匯入。")
@click.pass_context
def calibre_report(ctx: click.Context) -> None:
    cfg = ctx.obj["config"]
    manifest = Manifest.load(cfg.manifest_path)
    if not manifest.books:
        raise click.ClickException("manifest 為空，請先執行：openshelf scan")
    path = calibre.write_report(manifest, cfg)
    console.print(f"[green]Calibre 交接報表已寫入：[/green]{path}")


@main.command("ebook-open", help="批次開啟已下載的無 DRM EPUB/PDF。")
@click.option(
    "--target",
    type=click.Choice(["ade", "default"]),
    default="ade",
    help="交接目標：ADE 或系統預設程式。",
)
@click.option("--dry-run", is_flag=True, help="只列出可交接數量，不開啟檔案。")
@click.pass_context
def ebook_open(ctx: click.Context, target: str, dry_run: bool) -> None:
    cfg = ctx.obj["config"]
    manifest = Manifest.load(cfg.manifest_path)
    if not manifest.books:
        raise click.ClickException("manifest 為空，請先執行：openshelf scan")

    try:
        result = reader.open_drm_free(cfg, manifest, target=target, dry_run=dry_run)
    except (OSError, subprocess.CalledProcessError) as e:
        raise click.ClickException(f"EPUB/PDF 交接失敗：{e}")

    report_path = reader.write_report(manifest, cfg, target=target)
    plan = result.plan
    if dry_run:
        console.print(
            f"可交接 {len(plan.openable)} 本、檔案遺失 {len(plan.missing)} 本。"
        )
    else:
        console.print(f"[green]已送出 EPUB/PDF：[/green]{result.opened} 本")
    console.print(f"EPUB/PDF 交接報表已寫入：{report_path}")


@main.command("ebook-report", help="產生 EPUB/PDF 交接報表，不開啟檔案。")
@click.option(
    "--target",
    type=click.Choice(["ade", "default"]),
    default="ade",
    help="報表中的交接目標。",
)
@click.pass_context
def ebook_report(ctx: click.Context, target: str) -> None:
    cfg = ctx.obj["config"]
    manifest = Manifest.load(cfg.manifest_path)
    if not manifest.books:
        raise click.ClickException("manifest 為空，請先執行：openshelf scan")
    path = reader.write_report(manifest, cfg, target=target)
    console.print(f"[green]EPUB/PDF 交接報表已寫入：[/green]{path}")


@main.command("acsm-open", help="批次用系統預設程式開啟已下載的 .acsm。")
@click.option("--dry-run", is_flag=True, help="只列出可交接數量，不開啟檔案。")
@click.pass_context
def acsm_open(ctx: click.Context, dry_run: bool) -> None:
    cfg = ctx.obj["config"]
    manifest = Manifest.load(cfg.manifest_path)
    if not manifest.books:
        raise click.ClickException("manifest 為空，請先執行：openshelf scan")

    try:
        result = acsm.open_acsm(cfg, manifest, dry_run=dry_run)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"ACSM 交接失敗（exit {e.returncode}）。")
    except OSError as e:
        raise click.ClickException(f"ACSM 交接失敗：{e}")

    report_path = acsm.write_report(manifest, cfg)
    plan = result.plan
    if dry_run:
        console.print(
            f"可交接 {len(plan.openable)} 本、檔案遺失 {len(plan.missing)} 本。"
        )
    else:
        console.print(f"[green]已送出 .acsm：[/green]{result.opened} 本")
    console.print(f"ACSM 交接報表已寫入：{report_path}")


@main.command("acsm-report", help="產生 ACSM 交接報表，不開啟檔案。")
@click.pass_context
def acsm_report(ctx: click.Context) -> None:
    cfg = ctx.obj["config"]
    manifest = Manifest.load(cfg.manifest_path)
    if not manifest.books:
        raise click.ClickException("manifest 為空，請先執行：openshelf scan")
    path = acsm.write_report(manifest, cfg)
    console.print(f"[green]ACSM 交接報表已寫入：[/green]{path}")


@main.command(help="端點健康檢查：確認 Google 後端回應結構仍符合預期。")
@click.pass_context
def doctor(ctx: click.Context) -> None:
    cfg = ctx.obj["config"]
    try:
        client = build_client(cfg)
    except (NotLoggedIn, SessionExpired) as e:
        raise click.ClickException(str(e))
    with client:
        ok, msg = playbooks.check_library_endpoint(client)
    if ok:
        console.print(f"[green]OK {msg}[/green]")
    else:
        console.print(f"[red]FAIL {msg}[/red]")
        raise click.ClickException("端點健康檢查未通過。")


@main.command(help="開啟桌面圖形介面（需安裝 GUI 相依：pip install -e '.[gui]'）。")
@click.pass_context
def ui(ctx: click.Context) -> None:
    try:
        from .ui.main_window import run as run_ui
    except ImportError as e:
        raise click.ClickException(
            f"無法載入 GUI（{e}）。請先安裝：pip install -e '.[gui]'"
        )
    run_ui(ctx.obj["config"])


def _print_counts(manifest: Manifest, cfg=None) -> None:
    c = manifest.counts()
    table = Table(title="OpenShelf 書庫狀態")
    table.add_column("分類")
    table.add_column("數量", justify="right")
    labels = {
        "drm_free": "無 DRM（EPUB/PDF）",
        "acsm": "DRM（.acsm，需 ADE）",
        "no_export": "無法匯出（只記錄）",
        "failed": "失敗（待重試）",
        "pending": "待下載",
    }
    for key, label in labels.items():
        table.add_row(label, str(c.get(key, 0)))
    table.add_row("[bold]總計[/bold]", f"[bold]{c.get('total', 0)}[/bold]")
    console.print(table)

    if cfg is not None:
        stale = service.count_stale_acsm(manifest, cfg)
        if stale:
            console.print(
                f"[yellow][!] {stale} 本 .acsm 已逾 {cfg.acsm_valid_days} 天"
                "（以下載時間為準），建議重抓：openshelf export --refresh-acsm[/yellow]"
            )


if __name__ == "__main__":
    main()
