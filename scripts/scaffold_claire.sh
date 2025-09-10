#!/bin/bash

# Root project folder assumed to be already created, run this from inside it.

echo "🔧 Creating folder structure..."

mkdir -p src/core
mkdir -p src/interfaces
mkdir -p src/config
mkdir -p src/utils
mkdir -p tests

touch src/__init__.py
touch src/core/__init__.py
touch src/core/memory.py
touch src/core/reflection.py
touch src/core/planner.py
touch src/core/executor.py

touch src/interfaces/__init__.py
touch src/interfaces/cli.py

touch src/config/__init__.py
touch src/config/settings.py

touch src/utils/__init__.py
touch src/utils/logger.py
touch src/utils/prompts.py

touch tests/test_core.py

echo "📝 Writing run.py..."
cat <<EOF > run.py
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from interfaces.cli import run

if __name__ == "__main__":
    run()
EOF

echo "📦 Writing requirements.txt..."
cat <<EOF > requirements.txt
openai
python-dotenv
tqdm
rich
EOF

echo "🧹 Writing .gitignore..."
cat <<EOF > .gitignore
.env
envs/
__pycache__/
*.pyc
*.log
.vscode/
.DS_Store
EOF

echo "📖 Writing README.md..."
cat <<EOF > README.md
# CLAIRE

**Cognitive Learning Agent for Iterative Reflection and Explanation**

This project contains the core logic, interfaces, and supporting systems for CLAIRE — a reasoning and coordination agent designed to support iterative workflows, reflective reasoning, and transparent execution.
EOF

echo "✅ CLAIRE scaffolding complete!"
