"""Rich terminal dashboard for Crypto Quant Alpha Scanner results."""

import math

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def render_results(results: pd.DataFrame, console: Console | None = None) -> None:
    """Render screening results as a color-coded rich table.

    Columns:
        Rank | Symbol | Name | Market Cap | 24h Volume |
        Beta | Correlation | Kelly % | Circ. Supply %

    Color rules:
        Beta:        > 2.0 -> bold green, 1.5-2.0 -> yellow
        Correlation: > 0.85 -> bold green, 0.7-0.85 -> yellow
        Kelly:       > 0.15 -> bold green, > 0 -> yellow, 0 -> dim
    """
    if console is None:
        console = Console()

    table = Table(title="Crypto Quant Alpha Scanner Results")

    table.add_column("Rank", justify="right", style="bold")
    table.add_column("Symbol", style="cyan")
    table.add_column("Name")
    table.add_column("Market Cap", justify="right")
    table.add_column("24h Volume", justify="right")
    table.add_column("Beta", justify="right")
    table.add_column("Correlation", justify="right")
    table.add_column("Kelly %", justify="right")
    table.add_column("Amihud", justify="right")
    table.add_column("Circ. Supply %", justify="right")

    for rank, (_, row) in enumerate(results.iterrows(), start=1):
        # Format market cap and volume
        market_cap_str = f"${row['market_cap']:,.0f}"
        volume_str = f"${row['volume_24h']:,.0f}"

        # Format beta with color
        beta_val = row["beta"]
        beta_str = f"{beta_val:.2f}"
        if beta_val > 2.0:
            beta_style = "bold green"
        elif beta_val >= 1.5:
            beta_style = "yellow"
        else:
            beta_style = ""

        # Format correlation with color
        corr_val = row["correlation"]
        corr_str = f"{corr_val:.2f}"
        if corr_val > 0.85:
            corr_style = "bold green"
        elif corr_val >= 0.7:
            corr_style = "yellow"
        else:
            corr_style = ""

        # Format kelly as percentage with color
        kelly_val = row["kelly_fraction"]
        kelly_pct = kelly_val * 100
        kelly_str = f"{kelly_pct:.1f}%"
        if kelly_val > 0.15:
            kelly_style = "bold green"
        elif kelly_val > 0:
            kelly_style = "yellow"
        else:
            kelly_style = "dim"

        # Format Amihud illiquidity with color
        amihud_val = row.get("amihud")
        if pd.isna(amihud_val) or amihud_val is None:
            amihud_str = "N/A"
            amihud_style = ""
        else:
            amihud_str = f"{amihud_val:.1e}"
            amihud_style = "yellow" if amihud_val > 1e-7 else ""

        # Format circulating supply percentage
        circ_val = row["circulating_pct"]
        if pd.isna(circ_val) or (isinstance(circ_val, float) and math.isnan(circ_val)):
            circ_str = "N/A"
        else:
            circ_str = f"{circ_val * 100:.1f}%"

        table.add_row(
            str(rank),
            row["symbol"],
            row["name"],
            market_cap_str,
            volume_str,
            f"[{beta_style}]{beta_str}[/{beta_style}]" if beta_style else beta_str,
            f"[{corr_style}]{corr_str}[/{corr_style}]" if corr_style else corr_str,
            f"[{kelly_style}]{kelly_str}[/{kelly_style}]" if kelly_style else kelly_str,
            f"[{amihud_style}]{amihud_str}[/{amihud_style}]" if amihud_style else amihud_str,
            circ_str,
        )

    console.print(table)


def render_no_results(console: Console | None = None) -> None:
    """Display a message when no coins pass the screen."""
    if console is None:
        console = Console()

    panel = Panel(
        "No coins matched the screening criteria.",
        title="Crypto Quant Alpha Scanner",
        style="yellow",
    )
    console.print(panel)
