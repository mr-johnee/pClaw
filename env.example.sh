#!/usr/bin/env sh

# Copy the lines you need into ~/.zshrc, ~/.bashrc, or another shell startup
# file, then restart the shell or run: source ~/.zshrc
#
# This file only documents environment variables. It does not install Python
# packages — use `pip install -r requirements.txt` (or the conda recipe in
# README.md) for that.

# Required: contact email for the Unpaywall API.
# Unpaywall's terms of use require a real contact address on every request.
export CHEM_PDF_UNPAYWALL_EMAIL="you@example.com"

# Optional overrides for the OA PDF downloader.
# export CHEM_PDF_UNPAYWALL_API_BASE="https://api.unpaywall.org/v2"
# export CHEM_PDF_REQUEST_TIMEOUT_SECONDS="60"
# export CHEM_PDF_ROOT="$HOME/.chemdeep-pdf"

# Optional: override the bundled known-warhead exclusion list.
# Defaults to <skill-root>/data/known_warheads.json.
# export COVALENT_PROBE_KNOWN_WARHEADS="/path/to/your_known_warheads.json"
