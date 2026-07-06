"""
Thoth 📊 — Database Agent
SQL queries, data analysis, schema design, CSV/JSON processing.
"""
from __future__ import annotations
import logging, os, json, csv, sqlite3
from pathlib import Path
from typing import Any
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.database")

class DatabaseAgent(BaseAgent):
    name = "Thoth"
    emoji = "📊"
    color = "#4488cc"
    personality = "I see patterns in chaos. Every dataset tells a story — I translate it."
    codename = "thoth"
    description = "Database & data — SQL queries, data analysis, schema design, CSV processing"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "query_csv": "Run SQL-like queries on a CSV file",
            "analyze_data": "Analyze a dataset and produce summary statistics",
            "schema_design": "Design a database schema from a description",
            "generate_sql": "Generate SQL from a natural language description",
            "data_viz_suggestion": "Suggest the best chart types for a dataset",
            "csv_to_json": "Convert CSV data to JSON format",
        }

    async def execute(self, action, params):
        h = getattr(self, f"_h_{action}", None)
        if not h: return self._fail(f"Unknown: {action}")
        return await h(params)

    async def _ai(self, prompt, temp=0.3, tokens=1500):
        try:
            import litellm
            r = litellm.completion(model=os.environ.get("LLM_MODEL","openai/gpt-4o-mini"), messages=[{"role":"user","content":prompt}], temperature=temp, max_tokens=tokens)
            return r.choices[0].message.content.strip()
        except Exception as e: return f"[AI: {e}]"

    async def _h_query_csv(self, p):
        filename = p.get("file","") or p.get("query","")
        query_desc = p.get("sql","") or p.get("question","SELECT * LIMIT 5")
        if not filename: return self._fail("CSV file path required")
        fpath = Path(filename).expanduser()
        if not fpath.exists(): return self._fail(f"File not found: {filename}")
        try:
            conn = sqlite3.connect(":memory:")
            cursor = conn.cursor()
            with open(fpath, newline='', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                headers = next(reader)
                safe_headers = [h.strip().replace(' ','_').replace('-','_') for h in headers]
                cursor.execute(f"CREATE TABLE data ({', '.join(f'{h} TEXT' for h in safe_headers)})")
                for row in reader:
                    cursor.execute(f"INSERT INTO data VALUES ({','.join('?'*len(safe_headers))})", row[:len(safe_headers)])
            if "SELECT" in query_desc.upper() or "select" in query_desc:
                cursor.execute(query_desc)
            else:
                cursor.execute(f"SELECT * FROM data LIMIT 5")
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            lines = [", ".join(cols)]
            for r in rows[:50]:
                lines.append(", ".join(str(v)[:60] for v in r))
            conn.close()
            return self._ok(summary=f"📊 Query results ({len(rows)} rows):\n\n" + "\n".join(lines[:20]), data={"columns":cols,"rows":len(rows)})
        except Exception as e:
            return self._fail(f"Query failed: {e}")

    async def _h_analyze_data(self, p):
        data = p.get("data","") or p.get("query","")
        if not data: return self._fail("data required — paste CSV, JSON, or describe your dataset")
        if len(data) < 50 and '\n' in data:
            # Assume CSV header+rows
            try:
                lines = data.strip().split('\n')
                headers = lines[0].split(',')
                rows = [l.split(',') for l in lines[1:]]
                cols = len(headers)
                numeric_cols = []
                for i in range(cols):
                    try: [float(r[i]) for r in rows if i < len(r)]; numeric_cols.append(headers[i])
                    except: pass
                stats = f"📊 Dataset Analysis\n\nRows: {len(rows)}\nColumns: {cols}\nNumeric columns: {len(numeric_cols)}\n\n{headers}\n\nSample (first 3):\n"
                for r in rows[:3]: stats += f"  {r}\n"
                return self._ok(summary=stats, data={"rows":len(rows),"cols":cols,"headers":headers,"numeric_cols":numeric_cols})
            except: pass
        prompt = f"""Analyze this dataset description and provide summary statistics suggestions:
{data[:3000]}

Provide:
- Data shape (rows × columns if possible)
- Column types (numeric, categorical, text)
- Suggested analyses (correlation, trend, distribution)
- Recommended visualizations"""
        analysis = await self._ai(prompt)
        return self._ok(summary=analysis, data={})

    async def _h_schema_design(self, p):
        description = p.get("description","") or p.get("query","")
        if not description: return self._fail("description required — what is the database for?")
        prompt = f"""Design a database schema for: {description}

Return as SQL CREATE TABLE statements with:
- Table names, columns, types, constraints
- Primary keys, foreign keys
- Indexes on frequently queried columns
- Brief comment above each table explaining its purpose

Use PostgreSQL-compatible syntax."""
        schema = await self._ai(prompt, tokens=2000)
        return self._ok(summary=schema, data={"description":description})

    async def _h_generate_sql(self, p):
        question = p.get("question","") or p.get("query","")
        dialect = p.get("dialect","postgresql")
        if not question: return self._fail("question required — what query do you need?")
        prompt = f"""Write a {dialect} SQL query for: {question}

Include:
- The SQL query
- Brief explanation of what it does
- Any assumptions made about table/column names
- Alternative approach if applicable"""
        sql = await self._ai(prompt)
        return self._ok(summary=sql, data={"question":question,"dialect":dialect})

    async def _h_data_viz_suggestion(self, p):
        data_desc = p.get("data","") or p.get("query","")
        if not data_desc: return self._fail("describe your data or paste it")
        prompt = f"""Given this data: {data_desc[:2000]}

Suggest the best visualization types:
- For each insight or comparison, recommend chart type + brief rationale
- Include: bar, line, scatter, heatmap, pie, histogram, etc.

Format: 1. [Chart Type] — [What it shows] — [Why]"""
        viz = await self._ai(prompt)
        return self._ok(summary=viz, data={})

    async def _h_csv_to_json(self, p):
        data = p.get("data","") or p.get("query","")
        if not data: return self._fail("paste CSV data")
        try:
            lines = data.strip().split('\n')
            reader = csv.DictReader(lines)
            rows = [row for row in reader]
            j = json.dumps(rows, indent=2)
            return self._ok(summary=f"Converted {len(rows)} rows to JSON:\n\n{j[:2000]}", data={"rows":len(rows),"json":j[:5000]})
        except Exception as e:
            return self._fail(f"CSV parsing failed: {e}")
