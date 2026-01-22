#!/usr/bin/env python3
"""
Download US Code XML files from uscode.house.gov.

Usage:
    python scripts/download_usc.py 42        # Download Title 42 only
    python scripts/download_usc.py 42 26 15  # Download multiple titles
    python scripts/download_usc.py --all     # Download all titles
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path
import httpx
from rich.console import Console
from rich.progress import Progress, DownloadColumn, TransferSpeedColumn, BarColumn

console = Console()

# Base URL for US Code downloads
BASE_URL = "https://uscode.house.gov/download/releasepoints/us/pl/119/69not60"

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data" / "raw" / "usc"


def download_title(title: int, output_dir: Path = DATA_DIR) -> Path | None:
    """
    Download a US Code title XML file.

    Args:
        title: Title number (1-54)
        output_dir: Directory to save the file

    Returns:
        Path to the extracted XML file, or None if failed
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # URL format: xml_usc42@119-69not60.zip
    zip_filename = f"xml_usc{title:02d}@119-69not60.zip"
    url = f"{BASE_URL}/{zip_filename}"

    zip_path = output_dir / zip_filename
    xml_filename = f"usc{title:02d}.xml"
    xml_path = output_dir / xml_filename

    # Skip if already extracted
    if xml_path.exists():
        console.print(f"[dim]Title {title} already exists at {xml_path}[/dim]")
        return xml_path

    console.print(f"[bold]Downloading Title {title}...[/bold]")
    console.print(f"[dim]URL: {url}[/dim]")

    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
            if response.status_code == 404:
                console.print(f"[yellow]Title {title} not found (404)[/yellow]")
                return None

            response.raise_for_status()

            total = int(response.headers.get("content-length", 0))

            with Progress(
                "[progress.description]{task.description}",
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(f"Title {title}", total=total)

                with open(zip_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                        progress.advance(task, len(chunk))

        # Extract the ZIP
        console.print(f"[dim]Extracting {zip_filename}...[/dim]")
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Find the XML file in the archive
            xml_files = [n for n in zf.namelist() if n.endswith(".xml")]
            if not xml_files:
                console.print(f"[red]No XML file found in {zip_filename}[/red]")
                return None

            # Extract the XML file
            xml_content = zf.read(xml_files[0])
            with open(xml_path, "wb") as f:
                f.write(xml_content)

        # Clean up ZIP
        zip_path.unlink()

        console.print(f"[green]✓[/green] Saved to {xml_path}")
        return xml_path

    except httpx.HTTPError as e:
        console.print(f"[red]HTTP error downloading Title {title}: {e}[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Error downloading Title {title}: {e}[/red]")
        return None


def download_all_titles(output_dir: Path = DATA_DIR) -> list[Path]:
    """Download all US Code titles (1-54, with some gaps)."""
    # Valid title numbers (there are some gaps in the US Code)
    valid_titles = list(range(1, 55))  # 1-54

    downloaded = []
    for title in valid_titles:
        path = download_title(title, output_dir)
        if path:
            downloaded.append(path)

    return downloaded


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--all":
        console.print("[bold]Downloading all US Code titles...[/bold]")
        paths = download_all_titles()
        console.print(f"\n[green]Downloaded {len(paths)} titles[/green]")
    else:
        # Download specific titles
        titles = [int(t) for t in sys.argv[1:]]
        for title in titles:
            download_title(title)


if __name__ == "__main__":
    main()
