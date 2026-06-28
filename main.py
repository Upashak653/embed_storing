# main.py
import sys
import logging
from database import database_setup
from pipeline import run_ingestion_pipeline
from search import hybrid_search
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

def main():
    # 1. Verify DB schema exists
    ok = database_setup()
    if not ok:  logging.error("Database setup failed — aborting."); sys.exit(1)

    # 2. Ingest new documents (skips already embedded chunks automatically)
    # Add or remove files as needed
    files = [
        # r"C:\Users\Upashak.gayen\Downloads\SAP_Restricted_ABAP_Master_Cookbook_v2_1.docx",
        # r"C:\Users\Upashak.gayen\Downloads\sap_api_details_20260521_1435 1.xlsx",
    ]
    for file in files:
        if not Path(file).exists():
            logging.warning(f"File not found, skipping: {file}")
            continue
        run_ingestion_pipeline(file)

    # 3. Test retrieval
    hybrid_search("BAdI vs Implicit Enhancement", top_k=5)
    hybrid_search("Sales Order A2X required POST", top_k=5)

if __name__ == "__main__":
    main()