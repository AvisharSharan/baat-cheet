import re
from pathlib import Path

def process_file(filepath):
    content = filepath.read_text("utf-8")
    original = content
    
    # 1. Replace typing hints
    content = re.sub(r'\bDict\[', 'dict[', content)
    content = re.sub(r'\bList\[', 'list[', content)
    # Match Optional[...] including nested brackets, non-greedy
    while True:
        new_content = re.sub(r'\bOptional\[([^[\]]+(?:\[[^[\]]+\])*[^[\]]*)\]', r'\1 | None', content)
        if new_content == content:
            break
        content = new_content

    # Fix the typing imports line
    # If the line is like `from typing import Dict, List, Optional` it becomes `from typing import `
    # We will just replace `\bDict\b`, `\bList\b`, `\bOptional\b` with empty strings in import statements
    import_pattern = r'^(from typing import .+)$'
    def fix_imports(match):
        line = match.group(1)
        line = re.sub(r'\b(?:Dict|List|Optional)\b,?\s*', '', line)
        line = line.rstrip(', ')
        if line.endswith('import'):
            return '' # Remove empty import
        return line

    content = re.sub(import_pattern, fix_imports, content, flags=re.MULTILINE)

    # 2. Replace utility usages
    content = content.replace('_env_int(', 'env_int(')
    content = content.replace('_unlink_with_retry(', 'unlink_with_retry(')

    # Remove function definitions of _env_int and _unlink_with_retry
    content = re.sub(r'def _env_int\(.*?:\n(?: {4}.*\n)*', '', content)
    content = re.sub(r'def _unlink_with_retry\(.*?:\n(?: {4}.*\n)*', '', content)

    # Add imports for env_int and unlink_with_retry if needed
    if 'env_int(' in content or 'unlink_with_retry(' in content:
        # Check if already imported
        if 'from app.utils import' not in content:
            imports_to_add = []
            if 'env_int(' in content: imports_to_add.append('env_int')
            if 'unlink_with_retry(' in content: imports_to_add.append('unlink_with_retry')
            
            if imports_to_add:
                import_stmt = f"from app.utils import {', '.join(imports_to_add)}\n"
                # Insert after from __future__ import annotations
                content = content.replace('from __future__ import annotations\n', f'from __future__ import annotations\n{import_stmt}')

    if content != original:
        filepath.write_text(content, "utf-8")
        print(f"Updated {filepath}")

for p in Path("app").rglob("*.py"):
    if p.name != "utils.py":
        process_file(p)
