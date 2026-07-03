"""Command-line interface for Weekly Product Review Pulse."""

import click


@click.group()
@click.version_option()
def cli():
    """Weekly Product Review Pulse CLI."""
    pass


@cli.command()
@click.option("--product", required=True, help="Product slug (e.g. groww)")
@click.option("--iso-week", help="ISO week string (e.g. 2026-W23)")
@click.option("--email-mode", default="draft", help="Email mode: 'draft' or 'send'")
def run(product: str, iso_week: str, email_mode: str):
    """Run pipeline for current or specified ISO week."""
    from pulse.agent.orchestrator import run_pulse
    click.echo(f"[*] Executing pulse run for product={product}, week={iso_week or 'current'}...")
    try:
        res = run_pulse(product=product, iso_week=iso_week, dry_run=False, email_mode=email_mode)
        if res.get("status") == "already_completed":
            click.secho(f"\n[!] Idempotent run already completed for {product} ({res['iso_week']}).", fg="yellow")
            click.echo(f"Run ID: {res.get('run_id')}")
            for d in res.get("deliveries", []):
                click.echo(f"  -> [{d['channel']}] {d['url']}")
        else:
            click.secho(f"\n[+] Pulse run completed successfully!", fg="green")
            click.echo(f"Run ID: {res.get('run_id')} | Reviews: {res.get('review_count')}")
            for d in res.get("deliveries", []):
                click.echo(f"  -> [{d['channel']}] {d['url']}")
    except Exception as e:
        click.secho(f"\n[-] Pulse run failed: {e}", fg="red")
        raise click.Abort()


@cli.command()
@click.option("--product", required=True, help="Product slug (e.g. groww)")
@click.option("--from", "from_week", required=True, help="Start ISO week (e.g. 2026-W01)")
@click.option("--to", "to_week", required=True, help="End ISO week (e.g. 2026-W20)")
@click.option("--email-mode", default="draft", help="Email mode: 'draft' or 'send'")
def backfill(product: str, from_week: str, to_week: str, email_mode: str):
    """Sequential backfill with idempotency."""
    from pulse.agent.orchestrator import run_pulse
    click.echo(f"[*] Backfilling pulse for product={product} from {from_week} to {to_week}...")
    try:
        y1, w1 = map(int, from_week.split("-W"))
        y2, w2 = map(int, to_week.split("-W"))
        weeks = []
        for y in range(y1, y2 + 1):
            start_w = w1 if y == y1 else 1
            end_w = w2 if y == y2 else 52
            for w in range(start_w, end_w + 1):
                weeks.append(f"{y}-W{w:02d}")

        success_count = 0
        skip_count = 0
        for wk in weeks:
            click.echo(f"\n---> Processing week {wk}...")
            res = run_pulse(product=product, iso_week=wk, dry_run=False, email_mode=email_mode)
            if res.get("status") == "already_completed":
                click.secho(f"[!] Week {wk} already completed (skipped).", fg="yellow")
                skip_count += 1
            else:
                click.secho(f"[+] Week {wk} completed successfully!", fg="green")
                success_count += 1
        click.secho(f"\n[+] Backfill summary: {success_count} completed, {skip_count} skipped.", fg="green")
    except Exception as e:
        click.secho(f"\n[-] Backfill aborted due to error: {e}", fg="red")
        raise click.Abort()


@cli.command("dry-run")
@click.option("--product", required=True, help="Product slug (e.g. groww)")
@click.option("--iso-week", help="ISO week string (e.g. 2026-W23)")
def dry_run(product: str, iso_week: str):
    """Full pipeline except MCP writes."""
    from pulse.agent.orchestrator import run_pulse
    click.echo(f"[*] Running dry-run for product: {product}...")
    try:
        res = run_pulse(product=product, iso_week=iso_week, dry_run=True)
        click.secho(f"\n[+] Dry-run pipeline completed successfully (no MCP writes performed)!", fg="green")
        click.echo(f"Run ID: {res.get('run_id')} | Week: {res.get('iso_week')} | Reviews analyzed: {res.get('review_count')}")
        click.echo(f"Doc Section Anchor: {res.get('doc_section_anchor')}")
        click.echo(f"Email Subject: {res.get('email_subject')}")
    except Exception as e:
        click.secho(f"\n[-] Dry-run failed: {e}", fg="red")
        raise click.Abort()


@cli.command()
@click.option("--product", required=True, help="Product slug (e.g. groww)")
@click.option("--iso-week", help="ISO week string (e.g. 2026-W23)")
def status(product: str, iso_week: str):
    """Show ledger and delivery status."""
    from pulse.ledger.store import LedgerStore
    store = LedgerStore()
    runs = store.get_runs(product=product, iso_week=iso_week)
    if not runs:
        click.echo(f"No ledger records found for product={product}" + (f", week={iso_week}" if iso_week else "."))
        return

    click.echo(f"\n=== Audit Ledger Status for Product: {product} ===")
    for r in runs:
        color = "green" if r.status == "completed" else "red" if r.status == "failed" else "yellow"
        click.secho(f"\nRun ID: {r.run_id} | Week: {r.iso_week} | Status: [{r.status.upper()}]", fg=color, bold=True)
        click.echo(f"Started: {r.started_at} | Completed: {r.completed_at or 'N/A'} | Reviews: {r.review_count}")
        if r.error_message:
            click.secho(f"Error: {r.error_message}", fg="red")
        deliveries = store.get_deliveries(r.run_id)
        if deliveries:
            click.echo("Deliveries:")
            for d in deliveries:
                click.echo(f"  -> [{d.channel}] ID: {d.external_id} | URL: {d.url}")


@cli.command("deliver-doc")
@click.option("--product", default="groww", help="Product slug (e.g. groww)")
@click.option("--iso-week", default="2026-W23", help="ISO week string (e.g. 2026-W23)")
@click.option("--doc-id", help="Override target Google Doc ID")
def deliver_doc(product: str, iso_week: str, doc_id: str):
    """Run Phase 4 (Google Docs MCP Delivery) for weekly pulse report."""
    import os
    import yaml
    from dotenv import load_dotenv
    from pulse.ingestion.models import RunContext
    from pulse.pipeline.quote_validator import ActionIdea, Theme, PulseReport
    from pulse.render import build_doc_section
    from pulse.agent.mcp_client import MCPClient, MCPClientError

    load_dotenv()

    click.echo(f"[*] Starting Phase 4 (Google Docs MCP Delivery) for {product} ({iso_week})...")

    # Load doc_id from config if not overridden
    if not doc_id:
        doc_id = os.environ.get("GOOGLE_DOC_ID")
        if not doc_id:
            config_path = f"config/products/{product}.yaml"
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    doc_id = cfg.get("delivery", {}).get("google_doc_id", "<SHARED_DOC_ID>")
            else:
                doc_id = "<SHARED_DOC_ID>"

    doc_id = MCPClient._sanitize_doc_id(doc_id)

    if doc_id == "<SHARED_DOC_ID>":
        click.secho("\n[!] Notice: google_doc_id is set to placeholder '<SHARED_DOC_ID>'.", fg="yellow")
        click.secho("To perform a real append against Google Docs, please provide a valid Google Doc ID via --doc-id or GOOGLE_DOC_ID environment variable.", fg="yellow")
        click.echo("Attempting delivery against MCP client in test/validation mode...\n")

    themes = [
        Theme(
            theme_name="App performance & bugs",
            summary="Lag, crashes during trading hours; login/session timeouts.",
            quotes=[
                "The app freezes exactly when the market opens, very frustrating.",
                "Session logged out automatically during peak trading.",
            ],
            action_ideas=[
                ActionIdea(
                    title="Stabilize peak-time performance",
                    detail="Scale infra during market hours; improve crash visibility.",
                )
            ],
            cluster_size=120,
            avg_rating=1.4,
        ),
        Theme(
            theme_name="Customer support friction",
            summary="Slow responses; unresolved tickets.",
            quotes=[
                "Support takes days to reply and doesn't solve the issue.",
            ],
            action_ideas=[
                ActionIdea(
                    title="Improve support SLA visibility",
                    detail="Expected response time in-app; ticket status tracking.",
                )
            ],
            cluster_size=80,
            avg_rating=1.8,
        ),
    ]
    report = PulseReport(
        product=product,
        iso_week=iso_week,
        window_weeks=10,
        review_count=1250,
        themes=themes,
        generated_at="2026-06-08T10:30:00Z",
    )
    context = RunContext(product=product, iso_week=iso_week, window_weeks=10, dry_run=False, email_mode="draft")

    click.echo("[*] Rendering Google Doc section (Phase 3 output)...")
    section = build_doc_section(report, context)
    click.echo(f"[+] Rendered section anchor: {section.anchor}")

    server_url = os.environ.get("MCP_SERVER_URL", "https://web-production-af4fc.up.railway.app")
    api_key = os.environ.get("MCP_API_KEY")
    click.echo(f"[*] Connecting to MCP Server at: {server_url} ...")
    client = MCPClient(server_url=server_url, api_key=api_key)

    try:
        result = client.append_section(doc_id=doc_id, anchor=section.anchor, content=section.content)
        click.secho(f"\n[+] Phase 4 Delivery Completed!", fg="green")
        click.echo(f"Status: {result.get('status')}")
        if result.get('docUrl'):
            click.echo(f"Doc URL: {result.get('docUrl')}")
    except MCPClientError as e:
        click.secho(f"\n[-] Phase 4 Delivery Failed (MCPClientError): {e}", fg="red")
        if doc_id == "<SHARED_DOC_ID>":
            click.secho("Note: The failure occurred because '<SHARED_DOC_ID>' was sent to Google Docs API. Pass a valid --doc-id to append to a real document!", fg="yellow")


@cli.command("deliver-email")
@click.option("--product", default="groww", help="Product slug (e.g. groww)")
@click.option("--iso-week", default="2026-W23", help="ISO week string (e.g. 2026-W23)")
@click.option("--email-mode", default="draft", help="Email delivery mode: 'draft' or 'send'")
@click.option("--doc-url", help="Target canonical Google Doc URL")
def deliver_email(product: str, iso_week: str, email_mode: str, doc_url: str):
    """Run Phase 5 (Gmail MCP Delivery) for weekly pulse report."""
    import os
    import yaml
    from dotenv import load_dotenv
    from pulse.ingestion.models import RunContext
    from pulse.pipeline.quote_validator import ActionIdea, Theme, PulseReport
    from pulse.render import build_email_teaser
    from pulse.agent.mcp_client import MCPClient, MCPClientError

    load_dotenv()

    click.echo(f"[*] Starting Phase 5 (Gmail MCP Delivery) for {product} ({iso_week}) in mode: {email_mode}...")

    # Load config for recipients and default doc url if not overridden
    cfg = {}
    config_path = f"config/products/{product}.yaml"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    if not doc_url:
        doc_id = os.environ.get("GOOGLE_DOC_ID")
        if not doc_id:
            doc_id = cfg.get("delivery", {}).get("google_doc_id", "1n-S9qT-R_YaBhQi07o7lRYurF9ulzUX5Iz1pGOITIRU")
        doc_id = MCPClient._sanitize_doc_id(doc_id)
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    themes = [
        Theme(
            theme_name="App performance & bugs",
            summary="Lag, crashes during trading hours; login/session timeouts.",
            quotes=[
                "The app freezes exactly when the market opens, very frustrating.",
                "Session logged out automatically during peak trading.",
            ],
            action_ideas=[
                ActionIdea(
                    title="Stabilize peak-time performance",
                    detail="Scale infra during market hours; improve crash visibility.",
                )
            ],
            cluster_size=120,
            avg_rating=1.4,
        ),
        Theme(
            theme_name="Customer support friction",
            summary="Slow responses; unresolved tickets.",
            quotes=[
                "Support takes days to reply and doesn't solve the issue.",
            ],
            action_ideas=[
                ActionIdea(
                    title="Improve support SLA visibility",
                    detail="Expected response time in-app; ticket status tracking.",
                )
            ],
            cluster_size=80,
            avg_rating=1.8,
        ),
    ]
    report = PulseReport(
        product=product,
        iso_week=iso_week,
        window_weeks=10,
        review_count=1250,
        themes=themes,
        generated_at="2026-06-08T10:30:00Z",
    )
    context = RunContext(product=product, iso_week=iso_week, window_weeks=10, dry_run=False, email_mode=email_mode)

    click.echo("[*] Rendering Gmail teaser (Phase 3 output)...")
    teaser = build_email_teaser(report, context, doc_url=doc_url, config=cfg)
    click.echo(f"[+] Subject: {teaser.subject}")
    click.echo(f"[+] Recipients: {', '.join(teaser.recipients)}")
    click.echo(f"[+] Idempotency Key: {teaser.idempotency_key}")
    click.echo(f"[+] Deep Link: {doc_url}")

    server_url = os.environ.get("MCP_SERVER_URL", "https://web-production-af4fc.up.railway.app")
    api_key = os.environ.get("MCP_API_KEY")
    click.echo(f"[*] Connecting to MCP Server at: {server_url} ...")
    client = MCPClient(server_url=server_url, api_key=api_key)

    try:
        if email_mode.lower() == "send":
            result = client.send_email(to=teaser.recipients, subject=teaser.subject, body=teaser.text_body, html_body=teaser.html_body, text_body=teaser.text_body)
        else:
            result = client.create_email_draft(to=teaser.recipients, subject=teaser.subject, body=teaser.text_body, html_body=teaser.html_body, text_body=teaser.text_body)
            
        click.secho(f"\n[+] Phase 5 Gmail Delivery Completed!", fg="green")
        click.echo(f"Status: {result.get('status', 'success')}")
        if result.get('draft_id'):
            click.echo(f"Draft ID: {result.get('draft_id')}")
        if result.get('message_id'):
            click.echo(f"Message ID: {result.get('message_id')}")
    except MCPClientError as e:
        click.secho(f"\n[-] Phase 5 Gmail Delivery Failed (MCPClientError): {e}", fg="red")


if __name__ == "__main__":
    cli()
