import json
import pandas as pd
from pathlib import Path
from pypdf import PdfReader
from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import CHUNK_SIZE, CHUNK_OVERLAP

_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

def _split_and_log(text: str, file_type: str) -> list[str]:
    chunks = _splitter.split_text(text)
    print(f"[{file_type.upper()}] Parsed total chunks: {len(chunks)}")
    return chunks

def read_md(filepath: str) -> list[str]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:    
            return _split_and_log(f.read(), "md")
    except Exception as e:
        print(f"[MD] Failed to read {filepath}: {e}")
        return []

def read_pdf(filepath: str) -> list[str]:
    try:
        reader = PdfReader(filepath)
        text = "".join(
            (page.extract_text() or "") + "\n"
            for page in reader.pages
        )
        if not text.strip():    
            print(f"[PDF] Warning: no text extracted from {filepath}")
            return []
        return _split_and_log(text, "pdf")
    except Exception as e:  
        print(f"[PDF] Failed to read {filepath}: {e}")
        return []

def read_docx(filepath: str) -> list[str]:
    try:
        doc = Document(filepath)
        text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return _split_and_log(text, "docx")
    except Exception as e:  
        print(f"[DOCX] Failed to read {filepath}: {e}")
        return []

def read_json(filepath: str) -> list[str]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _split_and_log(json.dumps(data), "json")
    except Exception as e:  
        print(f"[JSON] Failed to read {filepath}: {e}")
        return []

def read_csv(filepath: str) -> list[str]:
    """Optimized row-by-row text chunker for tabular data frames."""
    try:
        print(f"[CSV] Processing dataset streams for: {filepath}")
        df = pd.read_csv(filepath)
        df = df.fillna("")
        
        chunks = []
        for _, row in df.iterrows():
            row_items = [f"{col}: {val}" for col, val in row.items() if str(val).strip() != ""]
            row_text = " | ".join(row_items)
            if row_text.strip():
                chunks.append(row_text)
                
        print(f"[CSV] Built {len(chunks)} independent row data blocks.")
        return chunks
    except Exception as e:  
        print(f"[CSV] Failed to read {filepath}: {e}")
        return []

def read_excel(filepath: str) -> list[str]:
    """Optimized row-by-row excel sheet stream parser."""
    try:
        print(f"[XLSX] Extracting structural rows from: {filepath}")
        df = pd.read_excel(filepath)
        df = df.fillna("")
        
        chunks = []
        for _, row in df.iterrows():
            row_items = [f"{col}: {val}" for col, val in row.items() if str(val).strip() != ""]
            row_text = " | ".join(row_items)
            if row_text.strip():
                chunks.append(row_text)
                
        print(f"[XLSX] Built {len(chunks)} independent row data blocks.")
        return chunks
    except Exception as e:  
        print(f"[XLSX] Failed to read {filepath}: {e}")
        return []

ROUTE_DICT = {
    ".md":   read_md,
    ".pdf":  read_pdf,
    ".docx": read_docx,
    ".json": read_json,
    ".csv":  read_csv,
    ".xlsx": read_excel,
}

def file_read_route(filepath: str) -> list[str]:
    try:
        if not Path(filepath).exists(): print(f"[READER] File not found: {filepath}");  return []
        
        ext = Path(filepath).suffix.lower()
        handler = ROUTE_DICT.get(ext)
        
        if not handler: print(f"[READER] Unsupported file type: {ext}");    return []
        return handler(filepath)
    
    except Exception as e:
        print(f"[READER] Failure for [{filepath}]: {e}")
        return []