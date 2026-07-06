"""
Mephisto 📄 — PDF Agent
PDF generation, form filling, data extraction, document merging.
"""
from __future__ import annotations
import logging, os, json
from typing import Any
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.pdf")

class PDFAgent(BaseAgent):
    name = "Mephisto"
    emoji = "📄"
    color = "#cc4444"
    personality = "Contracts, forms, documents. I bind souls to paper with unbreakable clauses."
    codename = "mephisto"
    description = "PDF operations — generation, form filling, data extraction, contracts"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "generate_contract": "Generate a legal contract or agreement as text/PDF-ready",
            "fill_form": "Fill a PDF form with provided data (generates FDF/instructions)",
            "extract_text": "Extract text from a PDF (describe the PDF for AI extraction)",
            "merge_docs": "Generate merge instructions for multiple documents",
            "create_invoice": "Create an invoice with line items, totals, and branding",
            "template_fill": "Fill a document template with custom data",
        }

    async def execute(self, action, params):
        h = getattr(self, f"_h_{action}", None)
        if not h: return self._fail(f"Unknown: {action}")
        return await h(params)

    async def _ai(self, prompt, temp=0.3, tokens=2000):
        try:
            import litellm
            r = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"), messages=[{"role":"user","content":prompt}], temperature=temp, max_tokens=tokens)
            return r.choices[0].message.content.strip()
        except Exception as e: return f"[AI: {e}]"

    async def _h_generate_contract(self, p):
        contract_type = p.get("type","") or p.get("query","")
        parties = p.get("parties","Party A and Party B")
        if not contract_type: return self._fail("contract type required (e.g. NDA, service agreement, lease)")
        prompt = f"""Draft a professional {contract_type} between {parties}.

Include:
- Title and date
- Parties section
- Recitals / Background
- Key terms and conditions (numbered)
- Payment terms (if applicable)
- Term and termination
- Confidentiality (if applicable)
- Governing law
- Signature blocks

Write in clear, enforceable language. Use standard legal formatting with section numbers."""
        contract = await self._ai(prompt, tokens=2500)
        return self._ok(summary=contract, data={"type":contract_type,"parties":parties})

    async def _h_fill_form(self, p):
        form_desc = p.get("form","") or p.get("query","")
        fields = p.get("fields",{})
        if not form_desc: return self._fail("form description required")
        lines = [f"📄 Form fill data for: {form_desc}\n"]
        for k, v in fields.items():
            lines.append(f"  {k}: {v}")
        if not fields:
            lines.append("  (provide 'fields' dict with field_name: value pairs)")
        return self._ok(summary="\n".join(lines), data={"form":form_desc,"fields":fields})

    async def _h_extract_text(self, p):
        doc = p.get("document","") or p.get("query","")
        if not doc: return self._fail("document content required (paste text from PDF)")
        prompt = f"""Extract and structure the key information from this document:

{doc[:4000]}

Return:
- Document type
- Key parties/entities
- Important dates
- Monetary amounts
- Key clauses or terms
- Summary (3-5 sentences)"""
        extraction = await self._ai(prompt, temp=0.2)
        return self._ok(summary=extraction, data={})

    async def _h_merge_docs(self, p):
        docs = p.get("documents",[]) or p.get("query","")
        if not docs: return self._fail("list of documents to merge required")
        if isinstance(docs, str): docs = [docs]
        lines = [f"📑 Merge plan for {len(docs)} documents:"]
        for i, d in enumerate(docs, 1):
            lines.append(f"  {i}. {str(d)[:80]}")
        lines.append(f"\nOrder: {' → '.join(str(i) for i in range(1, len(docs)+1))}")
        lines.append("\nTo merge PDFs programmatically, use: pip install PyPDF2")
        return self._ok(summary="\n".join(lines), data={"count":len(docs)})

    async def _h_create_invoice(self, p):
        client = p.get("client","Client Name") or p.get("query","")
        items = p.get("items",[{"description":"Service","quantity":1,"rate":100}])
        if not items: return self._fail("items list required")
        total = sum(i.get("quantity",1) * i.get("rate",0) for i in items)
        lines = [f"🧾 INVOICE\n\nTo: {client}\nDate: [date]\nInvoice #: [auto]"]
        for i, item in enumerate(items, 1):
            qty = item.get("quantity",1); rate = item.get("rate",0); amt = qty * rate
            lines.append(f"  {i}. {item.get('description','Item')} — {qty} × ${rate:.2f} = ${amt:.2f}")
        lines.append(f"\n  {'─'*40}\n  TOTAL: ${total:.2f}\n\nPayment due: Net 30\nThank you for your business.")
        return self._ok(summary="\n".join(lines), data={"client":client,"items":items,"total":total})

    async def _h_template_fill(self, p):
        template = p.get("template","") or p.get("query","")
        data = p.get("data",{})
        if not template: return self._fail("template description required")
        prompt = f"""Fill this template with the provided data:
Template: {template[:1000]}
Data: {json.dumps(data,indent=2)[:2000]}

Return the completed document with all placeholders filled."""
        filled = await self._ai(prompt, tokens=1500)
        return self._ok(summary=filled, data={})
