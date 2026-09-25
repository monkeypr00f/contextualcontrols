# File della repository

Esclusi ambienti virtuali, cache e metadati Git.

```text
contextual-controls/
├── .github
│   └── workflows
│       └── ci.yml
├── .gitignore
├── .pre-commit-config.yaml
├── ARCHITECTURE.md
├── LICENSE
├── README.md
├── custom_components
│   └── contextual_controls
│       ├── __init__.py
│       ├── config.py
│       ├── config_flow.py
│       ├── const.py
│       ├── context.py
│       ├── coordinator.py
│       ├── diagnostics.py
│       ├── eligibility.py
│       ├── frontend.py
│       ├── frontend
│       │   └── contextual-controls-card.js
│       ├── history.py
│       ├── manifest.json
│       ├── models.py
│       ├── scoring.py
│       ├── sensor.py
│       ├── services.yaml
│       ├── storage.py
│       ├── strings.json
│       ├── tracking.py
│       └── translations
│           ├── en.json
│           └── it.json
├── docs
│   ├── DELIVERY.md
│   ├── FILES.md
│   ├── PHASE2.md
│   ├── UI_PREVIEW.md
│   └── VERIFICATION.md
├── hacs.json
├── pyproject.toml
├── requirements-dev.txt
└── tests
    ├── __init__.py
    ├── runtime_check.py
    ├── test_context.py
    ├── test_history.py
    ├── test_package.py
    ├── test_policy.py
    └── test_scoring.py
```
