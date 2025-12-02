# OpenHands Development Guidelines

This document provides comprehensive guidelines for developing OpenHands. For AI assistants and developers working with this codebase.

## Project Overview

OpenHands is an AI-powered coding assistant platform. The project consists of:
- **Backend**: Python 3.12 with FastAPI, WebSocket server, and agent orchestration
- **Frontend**: React + TypeScript with Remix SPA mode, Vite, TanStack Query, and Tailwind CSS
- **Runtime**: Docker-based sandboxed execution environment for agents

## Quick Reference Commands

```bash
# Build the project (required first time)
make build

# Run both frontend and backend
make run

# Run servers independently
make start-backend    # Backend only (port 3000)
make start-frontend   # Frontend only (port 3001)

# Run tests
poetry run pytest ./tests/unit/test_*.py           # All unit tests
poetry run pytest ./tests/unit/test_file.py        # Specific test file
poetry run pytest -v ./tests/unit/test_file.py     # Verbose output

# Frontend tests
cd frontend && npm run test                         # All frontend tests
cd frontend && npm run test:coverage                # With coverage
```

## Key Documentation

- `/README.md` - Project overview
- `/Development.md` - Development guide
- `/CONTRIBUTING.md` - Contribution guidelines
- `/openhands/README.md` - Backend architecture
- `/frontend/README.md` - Frontend guide
- `/openhands/server/README.md` - Server API docs
- `/openhands/runtime/README.md` - Runtime documentation
- `/openhands/agenthub/README.md` - Agent implementation guide
- `/tests/unit/README.md` - Testing guide

## External Resources

- [LiteLLM Documentation](https://docs.litellm.ai) - LLM integration
- [OpenHands Documentation](https://docs.all-hands.dev) - User docs
- [SWE-bench](https://www.swebench.com/) - Evaluation benchmark
