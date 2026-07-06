"""
Janus 🗄️ — File Operations Agent
Local file management, cloud storage stubs (Drive, S3), backup automation.
"""
from __future__ import annotations
import logging, os, json, shutil
from pathlib import Path
from typing import Any
from agents.base import BaseAgent

logger = logging.getLogger("agent-hub.agents.fileops")

class FileOpsAgent(BaseAgent):
    name = "Janus"
    emoji = "🗄️"
    color = "#44aacc"
    personality = "Every file has two faces: what it is, and what it could become. I see both."
    codename = "janus"
    description = "File operations — search, organize, backup, cloud storage stubs"

    def get_capabilities(self) -> dict[str, str]:
        return {
            "search_files": "Search for files by name pattern in a directory",
            "file_info": "Get detailed info about a file (size, type, modified)",
            "organize": "Organize files by type, date, or custom rules",
            "backup": "Backup a directory or file to a backup location",
            "cleanup": "Find and remove duplicate or temp files",
            "disk_usage": "Report disk usage for a directory tree",
        }

    async def execute(self, action, params):
        h = getattr(self, f"_h_{action}", None)
        if not h: return self._fail(f"Unknown: {action}")
        return await h(params)

    def _resolve(self, p):
        path = Path(p or os.getcwd()).expanduser().resolve()
        if not path.exists(): return None
        return path

    async def _h_search_files(self, p):
        pattern = p.get("pattern","*") or p.get("query","*")
        directory = self._resolve(p.get("directory","."))
        if not directory: return self._fail(f"Directory not found: {p.get('directory','.')}")
        matches = list(directory.rglob(pattern))[:100]
        lines = [f"🔍 Found {len(matches)} files matching '{pattern}' in {directory}"]
        for m in matches[:20]:
            size = m.stat().st_size if m.is_file() else 0
            lines.append(f"  {'📁' if m.is_dir() else '📄'} {m.name} ({self._fsize(size)})")
        return self._ok(summary="\n".join(lines), data={"count":len(matches),"path":str(directory)})

    async def _h_file_info(self, p):
        fpath = self._resolve(p.get("path","") or p.get("query",""))
        if not fpath: return self._fail("File not found")
        st = fpath.stat()
        import time as _time
        info = {
            "name":fpath.name,"path":str(fpath),"size":st.st_size,"size_fmt":self._fsize(st.st_size),
            "is_dir":fpath.is_dir(),"modified":_time.strftime("%Y-%m-%d %H:%M:%S",_time.localtime(st.st_mtime)),
            "created":_time.strftime("%Y-%m-%d %H:%M:%S",_time.localtime(st.st_ctime)),
        }
        return self._ok(summary=f"📄 {fpath.name}\n  Size: {info['size_fmt']}\n  Modified: {info['modified']}", data=info)

    async def _h_organize(self, p):
        directory = self._resolve(p.get("directory","."))
        rule = p.get("rule","by_type")
        if not directory: return self._fail("Directory not found")
        # Dry run
        files = [f for f in directory.iterdir() if f.is_file()]
        groups = {}
        for f in files:
            ext = f.suffix.lower() or "no_ext"
            groups[ext] = groups.get(ext, []) + [f.name]
        lines = [f"📂 Organization plan for {directory} ({len(files)} files)"]
        for ext, names in sorted(groups.items()):
            lines.append(f"  {ext or '(none)'}: {len(names)} files")
        return self._ok(summary="\n".join(lines[:20]), data={"groups":{k:len(v) for k,v in groups.items()}})

    async def _h_backup(self, p):
        source = self._resolve(p.get("source","") or p.get("query",""))
        dest_str = p.get("destination",str(Path.home()/".agent-hub"/"backups"))
        if not source: return self._fail("source required")
        dest = Path(dest_str).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        # Simple copy
        if source.is_file():
            shutil.copy2(source, dest / source.name)
            return self._ok(summary=f"✅ Backed up: {source.name} → {dest}", data={})
        elif source.is_dir():
            archive_name = dest / f"{source.name}_backup"
            try:
                shutil.make_archive(str(archive_name), 'zip', source)
                return self._ok(summary=f"✅ Backed up directory: {source.name} → {archive_name}.zip", data={"archive":str(archive_name)+".zip"})
            except Exception as e:
                return self._fail(f"Backup failed: {e}")
        return self._fail("Source not found")

    async def _h_cleanup(self, p):
        directory = self._resolve(p.get("directory","."))
        if not directory: return self._fail("Directory not found")
        # Find temp/dup files (dry run)
        temp_exts = {".tmp",".bak",".pyc","~"}
        found = []
        for f in directory.rglob("*"):
            if f.is_file() and (f.suffix in temp_exts or f.name.endswith("~") or f.name.startswith("~")):
                found.append(str(f))
        if not found:
            return self._ok(summary="✅ Nothing to clean up")
        lines = [f"🧹 Found {len(found)} temp/backup files (dry run):"]
        for f in found[:20]:
            lines.append(f"  {Path(f).name}")
        return self._ok(summary="\n".join(lines), data={"files":found,"count":len(found)})

    async def _h_disk_usage(self, p):
        directory = self._resolve(p.get("directory","."))
        if not directory: return self._fail("Directory not found")
        total = 0; count = 0
        for f in directory.rglob("*"):
            if f.is_file():
                total += f.stat().st_size; count += 1
        lines = [f"💾 Disk usage: {directory}"]
        lines.append(f"  Files: {count}")
        lines.append(f"  Total: {self._fsize(total)}")
        return self._ok(summary="\n".join(lines), data={"files":count,"total_bytes":total,"total_fmt":self._fsize(total)})

    def _fsize(self, n):
        for unit in ['B','KB','MB','GB']:
            if n < 1024: return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"
