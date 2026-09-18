# AFL Assistant Capstone

This folder contains the Week 3 Day 5 submission: a domain-locked AFL assistant with a LangGraph router, real Week 3 prediction/retrieval adapters, a FastAPI wrapper, a small browser UI, evaluation results, monitoring guidance, and stakeholder materials.

## Run the API

Open PowerShell in this folder and run:

```powershell
py -3.14 -m pip install -r requirements.txt
py -3.14 -m uvicorn app:api --reload
```

Then open:

- UI: `http://127.0.0.1:8000/`
- Health check: `http://127.0.0.1:8000/health`
- OpenAPI docs: `http://127.0.0.1:8000/docs`

Example request:

```powershell
$body = @{ message = "What is the probability Geelong Cats will win this AFL match?"; conversation_id = "demo-1" } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/chat -Method Post -ContentType "application/json" -Body $body
```

The app loads the actual Day 2 pipelines through `Day 2/predict.py` and reads the Day 1 feature tables for grounded retrieval. It does not use the notebook demo prediction callback.

The scikit-learn version is pinned because the packaged joblib models were trained with scikit-learn 1.8.0. Loading them with another version can produce private-module or estimator compatibility errors.

## Validate

Compile the app:

```powershell
py -3.14 -m py_compile app.py
```

Run the notebook cells in order to reproduce:

- hardening and abuse tests
- 28-case combined evaluation table
- real model-vs-ladder benchmark
- FastAPI smoke checks
- production Day 2 and Day 3 wiring checks
- monitoring and refresh-plan checks

## Submission files

- `app.py`: standalone LangGraph plus FastAPI application
- `requirements.txt`: reproducible runtime dependencies, including the model-compatible scikit-learn version
- `Week3Day5Tasks.ipynb`: detailed implementation, evaluation, benchmark, and monitoring evidence
- `Week3Day5Report.pdf`: two-page executive report
- `Demo Script  Slide Outline.pdf`: stakeholder demo and presentation outline
